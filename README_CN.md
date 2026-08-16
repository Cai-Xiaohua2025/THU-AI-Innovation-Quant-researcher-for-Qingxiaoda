# 清研量策：面向清小搭的合规金融研究智能体

清研量策是为清华大学 AI 创新大赛准备的金融研究 Agent 项目。它面向公开 A 股市场研究场景，支持财报/公告解读、行情趋势分析、多股票候选池筛选、策略回测验证、图表化研究报告生成，并通过 OpenAI-compatible 协议接入清小搭。

项目定位是“金融研究辅助”，不是投资顾问或自动交易系统。系统默认不连接券商账户、不读取个人资产、不执行实盘交易；所有输出都区分事实、推断和待验证事项，并附带合规风险提示。

## 亮点能力

- **清小搭接入**：支持 `POST /v1/chat/completions` 和 `x_soda.attachments` 文件产物协议。
- **稳定 A 股数据源**：内置东方财富实时行情/K 线、巨潮资讯公告检索、可选 akshare 财务字段，并带缓存、超时和降级。
- **财报/公告附件解析**：支持用户上传 `pdf/docx/xlsx/txt/md/csv/json`；公告类请求还会自动下载近期巨潮公告 PDF，按页提取正文并缓存结果。
- **多股票选股池**：内置 A 股演示股票池，按动量、趋势、波动、成交活跃度、财务质量和数据可用性打分。
- **回测闭环**：支持外部回测网关；未配置时自动使用本地 MA10/MA30 均线策略回测兜底。
- **图表报告**：自动生成价格趋势图、选股评分图、回测净值图，并输出 Markdown/PDF 报告。
- **评审演示样例**：提供单股研究、选股池、回测、附件分析四类 JSON 请求。

## 快速启动

Ubuntu/Debian 建议先安装可嵌入的中文字体，确保生成的 PDF 能在浏览器和清小搭附件预览器中稳定显示：

```bash
sudo apt-get install -y fonts-wqy-zenhei
```

```powershell
pip install -r requirements.txt
python run.py
```

默认地址：

```text
http://localhost:8787
```

健康检查：

```powershell
Invoke-RestMethod http://localhost:8787/health
```

运行测试：

```powershell
$env:PYTHONPATH="src"
python -m pytest tests -q
```

## 生产部署

仓库提供 Gunicorn、systemd 和 Nginx 配置，推荐拓扑为：

```text
公网 :8787 -> Nginx -> 127.0.0.1:18787 -> Gunicorn -> Flask
```

安装依赖后，可使用生产入口验证应用：

```bash
PYTHONPATH=src gunicorn --config gunicorn.conf.py wsgi:app
```

服务器部署文件：

- `deploy/qingyan-agent.service`
- `deploy/nginx-qingyan-agent.conf`

正式接入建议为 `QINGYAN_PUBLIC_BASE_URL` 配置带有效证书的 HTTPS 公网域名。反向代理层必须关闭响应缓冲，确保 SSE 流式输出能实时到达清小搭。

## 可选上游大模型

系统支持接入任意 OpenAI-compatible Chat Completions 中转站。未配置上游时，系统继续使用本地行情、指标、回测和确定性模板；上游请求失败、超时或返回空内容时也会自动回退，不影响清小搭接口可用性。

只需在 `.env` 填写：

```dotenv
QINGYAN_LLM_BASE_URL=https://your-gateway.example.com/v1
QINGYAN_LLM_API_KEY=your-upstream-api-key
QINGYAN_LLM_MODEL=your-model-name
```

`QINGYAN_LLM_BASE_URL` 支持三种形式：

```text
https://gateway.example.com
https://gateway.example.com/v1
https://gateway.example.com/v1/chat/completions
```

修改后重启：

```bash
sudo systemctl restart qingyan-agent
```

验证：

```bash
curl http://127.0.0.1:8787/health
```

当配置完整时，响应中的 `upstream_llm_configured` 为 `true`，`upstream_llm_model` 显示配置的模型名。

本地 Python 代码仍负责行情、技术指标、选股评分和回测等数值计算；上游模型只负责复杂问题理解、证据综合、附件摘要分析和报告表达。附件摘要及结构化研究证据会发送给所配置的上游服务，因此不要使用不可信的中转站处理敏感材料。

## 清小搭接入配置

- Base URL：部署后的公网地址，例如 `https://your-domain.example.com`
- Chat Completions：`POST /v1/chat/completions`
- Models：`GET /v1/models`
- 鉴权：可选 Bearer Token。设置 `QINGYAN_API_TOKEN` 后，清小搭侧需要配置同一 token。
- 文件输出：响应顶层会返回 `x_soda.attachments`，包含 PDF、Markdown 和图表 PNG。
- 图片输入：支持清小搭/OpenAI 的 `image_url` 内容块。服务端会下载公网图片并交给视觉模型，可用于 K 线、行情和技术指标截图分析。

## A股覆盖与行情口径

- 股票身份不是只从本地名单读取：服务会通过巨潮资讯动态解析公司名称、六位代码和公告机构 ID。
- 覆盖上交所、深交所和北交所 A 股；北交所旧 `4/8` 开头代码会优先映射到当前 `920` 代码。
- 行情优先使用腾讯在线快照，失败后依次降级到新浪和东方财富；报价只做约 30 秒短缓存。
- 日线优先使用腾讯前复权 K 线；北交所等腾讯历史不足时使用新浪不复权 K 线，并在输出中明确复权口径；K 线约缓存 180 秒。
- “在线行情快照”不等于交易所直连的零延迟行情：休市时返回最近交易日数据，交易时段也可能存在数据源延迟。
- 在线源全部失败时才使用已校验历史缓存，并将 `is_stale` 标记为 `true`，不会把旧缓存称为实时数据。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `QINGYAN_HOST` | `0.0.0.0` | 服务监听地址 |
| `QINGYAN_PORT` | `8787` | 服务监听端口 |
| `QINGYAN_API_TOKEN` | 空 | 可选 Bearer Token |
| `QINGYAN_PUBLIC_BASE_URL` | 空 | 公网地址，用于生成附件 URL |
| `QINGYAN_REPORT_DIR` | `outputs/reports` | 报告输出目录 |
| `QINGYAN_CACHE_DIR` | `outputs/cache` | 数据缓存目录 |
| `QINGYAN_CONVERSATION_DIR` | `outputs/conversations` | 成功问答的本地 JSON 存档目录，按日期分文件夹 |
| `QINGYAN_SAVE_CONVERSATIONS` | `true` | 是否在服务器本地保存成功问答；不保存鉴权头和 API Key |
| `QINGYAN_CONVERSATION_MAX_CHARS` | `200000` | 单个问题或回答在本地存档中的最大字符数 |
| `QINGYAN_MAX_REQUEST_BYTES` | `2097152` | API 请求体大小上限 |
| `QINGYAN_MAX_DOWNLOAD_BYTES` | `26214400` | 单个远程附件下载上限 |
| `QINGYAN_MAX_IMAGE_BYTES` | `10485760` | 单张远程图片下载上限；支持 PNG/JPEG/WebP/GIF |
| `QINGYAN_MAX_FILES_PER_REQUEST` | `5` | 单次请求允许的附件数量 |
| `QINGYAN_REQUEST_TIMEOUT_SEC` | `12` | 外部数据源和附件请求超时 |
| `QINGYAN_ANNOUNCEMENT_LOOKBACK_DAYS` | `180` | 公告检索回看天数 |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_FILES` | `3` | 单次公告研究最多自动提取的近期 PDF 数量；设为 `0` 可关闭 |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_BYTES` | `8388608` | 单份公告 PDF 下载大小上限 |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_PAGES` | `20` | 单份公告 PDF 最多读取页数 |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_CHARS` | `9000` | 单份公告 PDF 最多保留的正文字符数 |
| `QINGYAN_ALLOW_PRIVATE_FILE_URLS` | `false` | 是否允许下载私网附件 URL；公网部署不建议开启 |
| `QINGYAN_TRUSTED_PROXY_COUNT` | `0` | 可信反向代理层数；使用仓库 Nginx 配置时设为 `1` |
| `QINGYAN_CORS_ORIGINS` | `*` | 允许跨域访问的来源列表 |
| `QINGYAN_BACKTEST_GATEWAY_URL` | 空 | 可选外部回测网关地址 |
| `QINGYAN_BACKTEST_GATEWAY_TOKEN` | 空 | 可选外部回测 token |
| `QINGYAN_LLM_BASE_URL` | 空 | OpenAI-compatible 上游地址；留空则禁用上游模型 |
| `QINGYAN_LLM_API_KEY` | 空 | 上游中转站 API Key |
| `QINGYAN_LLM_MODEL` | 空 | 上游实际模型名称 |
| `QINGYAN_LLM_TIMEOUT_SEC` | `90` | 上游请求总读取超时 |
| `QINGYAN_LLM_MAX_TOKENS` | `1800` | 上游单次最大生成 Token 数 |
| `QINGYAN_LLM_MAX_INPUT_CHARS` | `60000` | 发送给上游的最大证据字符数 |
| `QINGYAN_LLM_TEMPERATURE` | `0.2` | 上游生成温度 |
| `QINGYAN_ENABLE_AKSHARE` | `false` | 是否启用可选 akshare 财务字段；演示时默认关闭以提升稳定性 |

## 本地对话存档

成功的 Chat Completions 问答默认保存到：

```text
outputs/conversations/YYYY-MM-DD/HHMMSS_微秒_请求ID.json
```

存档包含角色化问题文本、实际返回给客户端的答案、模型名称、流式标记、结束原因、报告标题和产物文件名。不会保存 Authorization 请求头、服务端配置的 API Key 或附件 URL 查询参数；对话目录和日期子目录使用 `700` 权限，JSON 文件使用 `600` 权限，并且不会通过 `/files` 路由公开。用户主动写入问题正文的内容会作为对话原文保存，因此不要在问题中提交密码、密钥或其他敏感信息。存档默认不会自动过期，如涉及敏感内容，应按服务器的数据保留制度定期归档或删除。连接探针和失败的非法请求不会写入对话目录。

## 演示请求

```powershell
python scripts/run_demo_requests.py --base-url http://localhost:8787
```

也可以直接查看：

- `examples/demo_requests/01_single_stock_research.json`
- `examples/demo_requests/02_screening.json`
- `examples/demo_requests/03_backtest.json`
- `examples/demo_requests/04_file_analysis.json`

图片输入示例：

```json
{
  "model": "qingyan-liangce-agent",
  "messages": [{
    "role": "user",
    "content": [
      {"type": "text", "text": "请分析图中的趋势、量价特征和风险，只使用图中可见信息"},
      {"type": "image_url", "image_url": {"url": "https://example.com/kline.png"}}
    ]
  }]
}
```

## 合规边界

- 不承诺收益。
- 不提供代客理财。
- 不输出确定性买卖指令。
- 不自动下单。
- 不连接券商账户。
- 不采集个人敏感资产信息。
- 不绕过数据源权限。
- 回测结果只代表历史模拟，不代表未来表现。

## 后续可扩展

1. 增加更大的行业股票池和行业中性化筛选。
2. 为扫描版公告增加 OCR，并接入更稳定的财务数据库。
3. 增加 DCF、杜邦分析、盈利质量评分等财务模型。
4. 增加多因子组合回测、交易成本、涨跌停/停牌约束。
5. 增加评审页面或小型 dashboard 展示报告产物。
