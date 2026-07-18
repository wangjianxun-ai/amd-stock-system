#!/usr/bin/env python3
"""Update the AMD dashboard data file.

The dashboard never calls paid APIs from the browser. This script runs locally
or on a scheduler, reads API keys from environment variables, then writes the
safe public data file used by index.html.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_JS = ROOT / "data" / "amd_dashboard_data.js"
SYMBOL = os.getenv("AMD_SYMBOL", "AMD")
PROVIDER = os.getenv("AMD_DATA_PROVIDER", "finnhub").lower()
UPDATE_NEWS = os.getenv("UPDATE_NEWS", "0") == "1"


def load_current_data() -> dict:
    script = f"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {{ window: {{}} }};
vm.runInNewContext(fs.readFileSync({json.dumps(str(DATA_JS))}, "utf8"), sandbox);
console.log(JSON.stringify(sandbox.window.AMD_DASHBOARD_DATA));
"""
    result = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def build_dashboard_data() -> dict:
    data = load_current_data()
    data["generatedAt"] = datetime.now(timezone.utc).isoformat()
    status = []

    quote = fetch_quote()
    if quote:
        apply_quote(data, quote)
        status.append(f"{quote['provider']} 行情已更新")
        series = fetch_intraday_series()
        if series:
            data["chart"] = {
                "source": "Finnhub 分钟 K 线",
                "series": series,
            }
            status.append("走势图已更新")
        else:
            data["chart"] = {
                "source": "报价估算走势",
                "series": build_estimated_series(quote),
            }
            status.append("走势图使用实时报价估算")
    else:
        status.append("行情 API 待配置或未返回数据")

    market_news = fetch_market_news() if UPDATE_NEWS else []
    if market_news:
        data["marketNews"] = market_news
        status.append("财经新闻已更新，来源可能为英文")
    else:
        status.append("中文财经新闻沿用上次数据")

    amd_news = fetch_amd_news() if UPDATE_NEWS else []
    if amd_news:
        data["amdNews"] = amd_news
        status.append("AMD 新闻已更新，来源可能为英文")
    else:
        status.append("中文 AMD 新闻沿用上次数据")

    data["dataStatus"] = "；".join(status)
    return data


def fetch_quote() -> dict | None:
    if PROVIDER == "alphavantage":
        return fetch_alpha_vantage_quote()
    return fetch_finnhub_quote()


def fetch_market_news() -> list[dict]:
    if os.getenv("NEWSAPI_KEY"):
        news = fetch_newsapi_news(
            query='(stock market OR Nasdaq OR semiconductor OR AI stocks) AND (AMD OR Nvidia OR chips OR technology)',
            limit=6,
        )
        if news:
            return news
    if PROVIDER == "alphavantage":
        return fetch_alpha_vantage_news(tickers="", topics="technology,financial_markets", limit=6)
    return fetch_finnhub_market_news(limit=6)


def fetch_amd_news() -> list[dict]:
    if PROVIDER == "alphavantage":
        news = fetch_alpha_vantage_news(tickers=SYMBOL, topics="", limit=6)
        if news:
            return news
    news = fetch_finnhub_company_news(limit=6)
    if news:
        return news
    if os.getenv("NEWSAPI_KEY"):
        return fetch_newsapi_news(query="AMD OR Advanced Micro Devices", limit=6)
    return []


def fetch_intraday_series() -> list[dict]:
    if PROVIDER != "finnhub":
        return []
    token = os.getenv("FINNHUB_API_KEY")
    if not token:
        return []
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=8)
    query = urllib.parse.urlencode(
        {
            "symbol": SYMBOL,
            "resolution": "5",
            "from": int(start.timestamp()),
            "to": int(now.timestamp()),
            "token": token,
        }
    )
    raw = fetch_json(f"https://finnhub.io/api/v1/stock/candle?{query}")
    if not isinstance(raw, dict) or raw.get("s") != "ok":
        return []
    closes = raw.get("c") or []
    highs = raw.get("h") or []
    lows = raw.get("l") or []
    opens = raw.get("o") or []
    times = raw.get("t") or []
    rows = []
    for index, timestamp in enumerate(times):
        rows.append(
            {
                "time": datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(),
                "open": round_number(value_at(opens, index)),
                "high": round_number(value_at(highs, index)),
                "low": round_number(value_at(lows, index)),
                "close": round_number(value_at(closes, index)),
            }
        )
    return [row for row in rows if row["close"] is not None][-96:]


def fetch_json(url: str, headers: dict | None = None) -> dict | list | None:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "amd-dashboard/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print(f"API request failed: {exc}")
        return None


def fetch_finnhub_quote() -> dict | None:
    token = os.getenv("FINNHUB_API_KEY")
    if not token:
        return None
    query = urllib.parse.urlencode({"symbol": SYMBOL, "token": token})
    raw = fetch_json(f"https://finnhub.io/api/v1/quote?{query}")
    if not isinstance(raw, dict) or not raw.get("c"):
        return None
    return {
        "provider": "Finnhub",
        "price": raw.get("c"),
        "change": raw.get("d"),
        "changePercent": raw.get("dp"),
        "open": raw.get("o"),
        "high": raw.get("h"),
        "low": raw.get("l"),
        "previousClose": raw.get("pc"),
    }


def fetch_finnhub_market_news(limit: int) -> list[dict]:
    token = os.getenv("FINNHUB_API_KEY")
    if not token:
        return []
    query = urllib.parse.urlencode({"category": "general", "token": token})
    raw = fetch_json(f"https://finnhub.io/api/v1/news?{query}")
    if not isinstance(raw, list):
        return []
    return [normalize_finnhub_article(item, "市场新闻") for item in raw[:limit]]


def fetch_finnhub_company_news(limit: int) -> list[dict]:
    token = os.getenv("FINNHUB_API_KEY")
    if not token:
        return []
    today = date.today()
    query = urllib.parse.urlencode(
        {
            "symbol": SYMBOL,
            "from": (today - timedelta(days=7)).isoformat(),
            "to": today.isoformat(),
            "token": token,
        }
    )
    raw = fetch_json(f"https://finnhub.io/api/v1/company-news?{query}")
    if not isinstance(raw, list):
        return []
    return [normalize_finnhub_article(item, "AMD 新闻") for item in raw[:limit]]


def fetch_alpha_vantage_quote() -> dict | None:
    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        return None
    query = urllib.parse.urlencode({"function": "GLOBAL_QUOTE", "symbol": SYMBOL, "apikey": key})
    raw = fetch_json(f"https://www.alphavantage.co/query?{query}")
    quote = raw.get("Global Quote") if isinstance(raw, dict) else None
    if not quote:
        return None
    return {
        "provider": "Alpha Vantage",
        "price": parse_number(quote.get("05. price")),
        "change": parse_number(quote.get("09. change")),
        "changePercent": parse_number(str(quote.get("10. change percent", "")).replace("%", "")),
        "open": parse_number(quote.get("02. open")),
        "high": parse_number(quote.get("03. high")),
        "low": parse_number(quote.get("04. low")),
        "previousClose": parse_number(quote.get("08. previous close")),
    }


def fetch_alpha_vantage_news(tickers: str, topics: str, limit: int) -> list[dict]:
    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        return []
    params = {"function": "NEWS_SENTIMENT", "apikey": key, "limit": str(limit), "sort": "LATEST"}
    if tickers:
        params["tickers"] = tickers
    if topics:
        params["topics"] = topics
    raw = fetch_json(f"https://www.alphavantage.co/query?{urllib.parse.urlencode(params)}")
    feed = raw.get("feed") if isinstance(raw, dict) else None
    if not isinstance(feed, list):
        return []
    return [normalize_alpha_article(item) for item in feed[:limit]]


def fetch_newsapi_news(query: str, limit: int) -> list[dict]:
    key = os.getenv("NEWSAPI_KEY")
    if not key:
        return []
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": str(limit),
        "apiKey": key,
    }
    raw = fetch_json(f"https://newsapi.org/v2/everything?{urllib.parse.urlencode(params)}")
    articles = raw.get("articles") if isinstance(raw, dict) else None
    if not isinstance(articles, list):
        return []
    return [normalize_newsapi_article(item) for item in articles[:limit]]


def apply_quote(data: dict, quote: dict) -> None:
    price = money(quote.get("price"))
    change = signed_number(quote.get("change"))
    change_percent = signed_percent(quote.get("changePercent"))
    data["cards"] = [
        {**card, "value": price, "sub": f"{change} / {change_percent}"}
        if card.get("label") == "行情状态"
        else card
        for card in data.get("cards", [])
    ]
    data["priceTracking"] = [
        ["当前价 / 涨跌幅", price, f"今日变化 {change}，涨跌幅 {change_percent}", "已接入"],
        ["开盘 / 最高 / 最低", f"{money(quote.get('open'))} / {money(quote.get('high'))} / {money(quote.get('low'))}", "观察日内波动范围", "已接入"],
        ["前收盘价", money(quote.get("previousClose")), "用于判断今日跳空和短线情绪", "已接入"],
        ["20/50/200 日均线", "等待历史行情 API", "下一步接入历史 K 线后自动计算", "待接入"],
    ]
    data["quote"] = {
        "symbol": SYMBOL,
        "price": round_number(quote.get("price")),
        "change": round_number(quote.get("change")),
        "changePercent": round_number(quote.get("changePercent")),
        "open": round_number(quote.get("open")),
        "high": round_number(quote.get("high")),
        "low": round_number(quote.get("low")),
        "previousClose": round_number(quote.get("previousClose")),
        "provider": quote.get("provider"),
    }


def build_estimated_series(quote: dict) -> list[dict]:
    open_price = parse_number(quote.get("open")) or parse_number(quote.get("previousClose")) or 0
    current = parse_number(quote.get("price")) or open_price
    high = parse_number(quote.get("high")) or max(open_price, current)
    low = parse_number(quote.get("low")) or min(open_price, current)
    now = datetime.now(timezone.utc)
    start = now.replace(hour=13, minute=30, second=0, microsecond=0)
    if now < start:
        start = now - timedelta(hours=6, minutes=30)
    points = 78
    rows = []
    for index in range(points):
        progress = index / (points - 1)
        wave = ((index % 11) - 5) / 5
        drift = open_price + (current - open_price) * progress
        volatility = (high - low) * 0.08 * wave * (1 - abs(progress - 0.5))
        close = min(high, max(low, drift + volatility))
        rows.append(
            {
                "time": (start + timedelta(minutes=5 * index)).isoformat(),
                "open": round_number(open_price if index == 0 else rows[-1]["close"]),
                "high": round_number(max(close, open_price, low if index == 0 else rows[-1]["close"])),
                "low": round_number(min(close, open_price, high if index == 0 else rows[-1]["close"])),
                "close": round_number(close),
            }
        )
    rows[-1]["close"] = round_number(current)
    return rows


def normalize_finnhub_article(item: dict, fallback_source: str) -> dict:
    published = datetime.fromtimestamp(item.get("datetime", 0), tz=timezone.utc)
    return {
        "date": published.date().isoformat(),
        "source": item.get("source") or fallback_source,
        "title": item.get("headline") or "未命名新闻",
        "summary": item.get("summary") or "暂无摘要。",
        "impact": infer_impact(item.get("headline", "") + " " + item.get("summary", "")),
        "url": item.get("url") or "#",
    }


def normalize_alpha_article(item: dict) -> dict:
    published = parse_alpha_time(item.get("time_published"))
    return {
        "date": published,
        "source": item.get("source") or "Alpha Vantage",
        "title": item.get("title") or "未命名新闻",
        "summary": item.get("summary") or "暂无摘要。",
        "impact": infer_impact(item.get("title", "") + " " + item.get("summary", "")),
        "url": item.get("url") or "#",
    }


def normalize_newsapi_article(item: dict) -> dict:
    source = item.get("source") or {}
    published = item.get("publishedAt", "")[:10] or date.today().isoformat()
    return {
        "date": published,
        "source": source.get("name") or "NewsAPI",
        "title": item.get("title") or "未命名新闻",
        "summary": item.get("description") or "暂无摘要。",
        "impact": infer_impact((item.get("title") or "") + " " + (item.get("description") or "")),
        "url": item.get("url") or "#",
    }


def infer_impact(text: str) -> str:
    lower = text.lower()
    if any(word in lower for word in ["sell-off", "bear", "falls", "drops", "risk", "pressure"]):
        return "偏谨慎"
    if any(word in lower for word in ["earnings", "guidance", "ai", "semiconductor", "chips"]):
        return "重点关注"
    return "一般关注"


def parse_alpha_time(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return datetime.strptime(value[:8], "%Y%m%d").date().isoformat()
    except ValueError:
        return date.today().isoformat()


def parse_number(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def value_at(values: list, index: int):
    return values[index] if index < len(values) else None


def round_number(value) -> float | None:
    number = parse_number(value)
    if number is None:
        return None
    return round(number, 4)


def money(value) -> str:
    number = parse_number(value)
    if number is None:
        return "待更新"
    return f"${number:,.2f}"


def signed_number(value) -> str:
    number = parse_number(value)
    if number is None:
        return "待更新"
    return f"{number:+.2f}"


def signed_percent(value) -> str:
    number = parse_number(value)
    if number is None:
        return "待更新"
    return f"{number:+.2f}%"


def write_data_js(data: dict) -> None:
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    DATA_JS.write_text(f"window.AMD_DASHBOARD_DATA = {payload};\n", encoding="utf-8")


def main() -> None:
    write_data_js(build_dashboard_data())
    print(f"Updated {DATA_JS}")


if __name__ == "__main__":
    main()
