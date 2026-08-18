# 清研量策：面向清小搭的合规金融研究智能体

清研量策是为清华大学 AI 创新大赛准备的金融研究 Agent 项目。它面向公开 A 股市场研究场景，支持财报/公告解读、行情趋势分析、多股票候选池筛选、策略回测验证、图表化研究报告生成，并通过 OpenAI-compatible 协议接入清小搭。

项目定位是“金融研究辅助”，不是投资顾问或自动交易系统。系统默认不连接券商账户、不读取个人资产、不执行实盘交易；所有输出都区分事实、推断和待验证事项，并附带合规风险提示。

## 亮点能力

- **清小搭接入**：支持 `POST /v1/chat/completions` 和 `x_soda.attachments` 文件产物协议。
- **稳定 A 股数据源**：行情与 K 线按腾讯、​新浪、东方财富顺序降级，巨潮资讯负责标的与公告检索，AkShare 财务字段保持可选，并统一处理缓存、超时和结构化状态。
- **财报/公告附件解析**：支持用户上传 `pdf/docx/xlsx/txt/md/csv/json`；公告类请求还会自动下载近期巨潮公告 PDF，按页提取正文并缓存结果。
- **分层回答长度**：提供 `concise`、`standard`、`detailed` 三种 `AnswerProfile`；清小搭普通问法默认使用 `standard`，详细 Markdown/PDF 仍保留完整研究证据。
- **安全多轮上下文**：历史用户轮次只用于必要的标的继承，最新用户轮次独立决定标的、意图、回答长度和证据范围；出现新公司名、错误代码或名称/代码冲突时，优先重新核验，不会静默沿用上一只股票。
- **结构化公告研究**：按公告输出事实、推断、潜在影响、风险、待验证事项和来源页码；普通聊天只展示有限条重要结论，公告原文只进入详细报告附录。
- **上游输入去重**：结构化证据不携带整份公告正文，原始文本只通过有字符预算的 `source_excerpts` 发送一次，并在最终答案阶段保守去除完全重复的长段落。
- **多股票选股池**：内置 A 股演示股票池，按动量、趋势、波动、成交活跃度、财务质量和数据可用性打分。
- **回测闭环**：支持外部回测网关；未配置时使用本地 MA10/MA30 均线策略回测兜底，并报告 CAGR、波动率、Sharpe、Calmar、胜率、暴露度、换手、基准和超额收益。
- **可审计研究计划**：按意图生成有限、规则驱动的研究步骤，并对标的、行情、技术、财务、公告、图片或回测证据执行确定性完整性检查。
- **正式投研标准**：按 QY-A-SHARE-RESEARCH-2.0 分层表达原始事实、派生指标、模型标签、分析推断和待验证事项，并输出可验证情景与失效条件。
- **专业图表与 PDF**：自动生成价格、MA5/MA20/MA60 与成交量联合图，PDF 包含中文字体、机构风表格、页眉页脚和“清研量策·A股研究助手”角标。
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

如需启用 AkShare 财务字段，可额外安装：

```bash
pip install -r requirements-optional.txt
# 或使用项目可选依赖
pip install -e '.[fundamentals]'
```

生产环境安装依赖后，可将 `deploy/qingyan-agent-fundamentals.conf` 作为 systemd drop-in 安装到
`/etc/systemd/system/qingyan-agent.service.d/10-fundamentals.conf`，并将
`deploy/qingyan-agent-fundamentals.env` 安装到 `/etc/qingyan-agent/fundamentals.env`，再执行
`systemctl daemon-reload` 和 `systemctl restart qingyan-agent`。使用额外的、后加载的 EnvironmentFile
可以覆盖主 `.env` 中的默认关闭值，无需修改或复制其中的其他配置。启用后，旧的“模块未启用”元数据缓存不会阻止重新抓取真实财务指标。

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

正式接入建议为 `QINGYAN_PUBLIC_BASE_URL` 配置带有效证书的 HTTPS 公网域名。反向代理层应关闭响应缓冲以兼容 SSE。流式请求会先建立 SSE 并发送 `accepted`、附件读取、研究、产物生成和完成等 `x_qingyan` 进度事件；正文仍在完整研究和事实检查后分块返回，不透传上游 Token。这样可保留完整性检查、短回答合并和确定性失败回退。

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

本地 Python 代码仍负责行情、技术指标、选股评分、回测、公告事实抽取和证据完整性检查等确定性工作；上游模型只负责复杂问题理解、证据综合、附件摘要分析和报告表达。发送给上游的结构化证据会移除公告整篇原文，原文只会以限量 `source_excerpts` 单独加入一次，但用户附件摘要和必要证据仍可能发送给所配置的上游服务，因此不要使用不可信的中转站处理敏感材料。

对于“看看走势，顺便看看近期公告”一类自然组合问法，系统会识别为综合研究，而不是只执行公告检索。证据完整性统一以 `ResearchContext` 中的实际意图为准：用户没有请求财务研究时，不会仅因 AkShare 未启用而错误降低技术面与公告研究的完整性等级。

## 清小搭接入配置

- Base URL：部署后的公网地址，例如 `https://your-domain.example.com`
- Chat Completions：`POST /v1/chat/completions`
- Models：`GET /v1/models`
- 鉴权：可选 Bearer Token。设置 `QINGYAN_API_TOKEN` 后，清小搭侧需要配置同一 token。
- 文件输出：响应顶层会返回 `x_soda.attachments`，包含 PDF、Markdown 和图表 PNG；聊天正文末尾也会附上可点击的产物链接，以兼容不展示顶层附件元数据的客户端。
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
| `QINGYAN_CACHE_RETENTION_DAYS` | `0` | 缓存保留天数；`0` 表示关闭自动清理 |
| `QINGYAN_REPORT_RETENTION_DAYS` | `0` | 报告和图表保留天数；`0` 表示关闭自动清理 |
| `QINGYAN_CONVERSATION_RETENTION_DAYS` | `0` | 对话存档保留天数；`0` 表示关闭自动清理 |
| `QINGYAN_MAX_REQUEST_BYTES` | `2097152` | API 请求体大小上限 |
| `QINGYAN_MAX_DOWNLOAD_BYTES` | `26214400` | 单个远程附件下载上限 |
| `QINGYAN_MAX_IMAGE_BYTES` | `10485760` | 单张远程图片下载上限；支持 PNG/JPEG/WebP/GIF |
| `QINGYAN_MAX_FILES_PER_REQUEST` | `5` | 单次请求允许的附件数量 |
| `QINGYAN_REQUEST_TIMEOUT_SEC` | `12` | 外部数据源和附件请求超时 |
| `QINGYAN_DATA_COLLECTION_WORKERS` | `4` | 单股行情、K线、财务和公告并行采集的最大工作线程数 |
| `QINGYAN_ANNOUNCEMENT_LOOKBACK_DAYS` | `180` | 公告检索回看天数 |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_FILES` | `3` | 单次公告研究最多自动提取的近期 PDF 数量；设为 `0` 可关闭 |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_BYTES` | `8388608` | 单份公告 PDF 下载大小上限 |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_PAGES` | `20` | 单份公告 PDF 最多读取页数 |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_CHARS` | `9000` | 单份公告 PDF 最多保留的正文字符数 |
| `QINGYAN_ALLOW_PRIVATE_FILE_URLS` | `false` | 是否允许下载私网附件 URL；公网部署不建议开启 |
| `QINGYAN_REQUIRE_FILE_AUTH` | `false` | 是否要求 `/files` 附件下载携带与 API 相同的 Bearer Token；默认关闭以兼容清小搭直接预览 |
| `QINGYAN_SIGN_ARTIFACT_URLS` | `false` | 是否让新产物使用带 HMAC 和过期时间的 `/artifacts/<artifact_id>` URL；默认关闭以兼容现有附件预览 |
| `QINGYAN_ARTIFACT_SIGNING_KEY` | 空 | 附件 URL 签名密钥；未设置时可回退使用 API Token，开启签名时二者至少配置一个 |
| `QINGYAN_ARTIFACT_URL_TTL_SEC` | `3600` | 签名附件 URL 有效期 |
| `QINGYAN_ARTIFACT_INDEX_PATH` | `outputs/artifacts/index.json` | Artifact 元数据索引；仅保存随机 ID、文件名、类型、大小、哈希和时间，不保存绝对路径 |
| `QINGYAN_TRUSTED_PROXY_COUNT` | `0` | 可信反向代理层数；使用仓库 Nginx 配置时设为 `1` |
| `QINGYAN_CORS_ORIGINS` | `*` | 允许跨域访问的来源列表 |
| `QINGYAN_BACKTEST_GATEWAY_URL` | 空 | 可选外部回测网关地址 |
| `QINGYAN_BACKTEST_GATEWAY_TOKEN` | 空 | 可选外部回测 token |
| `QINGYAN_BACKTEST_FEE_BPS` | `0` | 本地回测单边手续费，单位基点；默认 0 保持历史口径 |
| `QINGYAN_BACKTEST_SLIPPAGE_BPS` | `0` | 本地回测单边滑点，单位基点 |
| `QINGYAN_BACKTEST_RISK_FREE_RATE` | `0` | Sharpe 计算使用的年化无风险利率 |
| `QINGYAN_LLM_BASE_URL` | 空 | OpenAI-compatible 上游地址；留空则禁用上游模型 |
| `QINGYAN_LLM_API_KEY` | 空 | 上游中转站 API Key |
| `QINGYAN_LLM_MODEL` | 空 | 上游实际模型名称 |
| `QINGYAN_LLM_TIMEOUT_SEC` | `90` | 上游请求总读取超时 |
| `QINGYAN_LLM_MAX_TOKENS` | `3600` | 上游单次最大生成 Token 数，用于完整正式研究报告 |
| `QINGYAN_LLM_MAX_INPUT_CHARS` | `60000` | 发送给上游的最大证据字符数 |
| `QINGYAN_LLM_TEMPERATURE` | `0.2` | 上游生成温度 |
| `QINGYAN_ENABLE_AKSHARE` | `false` | 是否启用可选 akshare 财务字段；演示时默认关闭以提升稳定性 |

## 本地对话存档

成功的 Chat Completions 问答默认保存到：

```text
outputs/conversations/YYYY-MM-DD/HHMMSS_微秒_请求ID.json
```

存档包含角色化问题文本、实际返回给客户端的答案、模型名称、流式标记、结束原因、报告标题和产物文件名。不会保存 Authorization 请求头、服务端配置的 API Key 或附件 URL 查询参数；对话目录和日期子目录使用 `700` 权限，JSON 文件使用 `600` 权限，并且不会通过 `/files` 路由公开。用户主动写入问题正文的内容会作为对话原文保存，因此不要在问题中提交密码、密钥或其他敏感信息。默认保留策略为 `0`，不会自动删除；部署者可显式设置缓存、报告和对话保留天数。清理器只处理对应目录中的已知生成文件类型，并跳过符号链接、`.env`、`.orig` 和 `.rej`。连接探针和失败的非法请求不会写入对话目录。

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

## 开发与架构

核心边界按“API → 研究编排 → 领域计算 → 基础设施适配 → 报告产物”组织：

```text
qingyan_agent/
├── app.py                     # Flask/OpenAI-compatible 接口
├── research_agent.py          # 兼容门面与研究编排
├── research_planning.py       # 规则研究计划与证据完整性检查
├── deterministic_analysis.py  # 不依赖大模型的证据化研究表达
├── announcement_analysis.py   # 公告事实、推断、影响、风险与页码证据的结构化分析
├── contracts.py               # 跨模块数据契约与研究步骤状态
├── domain/indicators/         # 不依赖网络的确定性技术指标
├── market_data/               # Provider Protocol、CNInfo、腾讯/新浪/东方财富/AkShare 适配器
├── infrastructure/            # 原子文件缓存与统一 HTTP 客户端
├── artifacts.py               # Artifact 索引、哈希和可选签名 URL
├── retention.py               # 默认关闭的本地生成数据保留策略
├── report_composer.py         # 研究报告内容和元数据组装
└── reporting.py               # 图表、Markdown/PDF 产物
```

开发检查：

```bash
python -m pip install -e '.[dev]'
ruff check src tests
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m pytest tests -q
```

本地缓存采用带 Schema 版本的兼容 JSON 和原子替换写入；旧缓存仍可读取。单股行情、K线、财务和公告默认使用有限线程池并行采集。SSE 会立即发送研究进度，但正文仍是经过完整证据检查后的兼容分块；`/health` 明确返回 `upstream_token_passthrough=false`。

## 后续可扩展

1. 增加更大的行业股票池和行业中性化筛选。
2. 为扫描版公告增加 OCR，并接入更稳定的财务数据库。
3. 增加 DCF、杜邦分析、盈利质量评分等财务模型。
4. 增加多因子组合回测、成交量冲击模型和更精细的 A 股交易日历/除权除息处理。
5. 增加评审页面或小型 dashboard 展示报告产物。
