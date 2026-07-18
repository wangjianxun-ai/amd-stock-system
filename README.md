# AMD 股票跟踪及分析系统

这是一个可发布到 GitHub Pages 的静态网页系统。网页不会暴露 API key；GitHub Actions 会在后台读取 `FINNHUB_API_KEY`，更新公开数据文件 `data/amd_dashboard_data.js`。

## 文件说明

- `index.html`：手机和电脑访问的网页
- `data/amd_dashboard_data.js`：网页读取的数据
- `scripts/update_amd_dashboard_data.py`：自动更新行情数据
- `.github/workflows/update-and-pages.yml`：GitHub Pages 发布和定时更新配置

## 上线步骤

1. 在 GitHub 新建一个仓库，例如 `amd-stock-system`。
2. 把这个文件夹里的所有文件上传到仓库根目录。
3. 进入仓库的 `Settings` -> `Secrets and variables` -> `Actions`。
4. 新增一个 secret：
   - 名称：`FINNHUB_API_KEY`
   - 值：你的 Finnhub API key
5. 进入 `Settings` -> `Pages`。
6. Source 选择 `GitHub Actions`。
7. 进入 `Actions` 页面，手动运行 `Update AMD dashboard and publish`。
8. 等运行成功后，GitHub Pages 会给你一个网址，手机打开即可访问。

## 每天自动更新

工作流默认在美股交易日收盘后附近运行一次：

```text
0 22 * * 1-5
```

这个时间是 UTC，对应美东下午/傍晚。你也可以在 GitHub Actions 页面手动点击运行。

## 中文新闻说明

为了保持页面中文显示，自动任务默认只更新行情，不覆盖当前整理好的中文新闻：

```yaml
UPDATE_NEWS: "0"
```

如果改成 `UPDATE_NEWS: "1"`，系统会自动抓取 Finnhub 新闻，但新闻标题和摘要可能会变成英文。后续如果接入翻译服务，可以再改成自动抓取并翻译。

## 安全提醒

不要把 Finnhub API key 写进 `index.html` 或 `data/amd_dashboard_data.js`。只放到 GitHub Secrets。

本系统只用于信息跟踪和分析，不构成投资建议。

