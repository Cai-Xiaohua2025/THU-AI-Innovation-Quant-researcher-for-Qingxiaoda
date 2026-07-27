# 清研量策：面向清小搭的合规金融研究智能体

清研量策是为清华大学 AI 创新大赛准备的金融研究 Agent 项目。它面向公开 A 股市场研究场景，支持财报/公告解读、行情趋势分析、多股票候选池筛选、策略回测验证、图表化研究报告生成，并通过 OpenAI-compatible 协议接入清小搭。

项目定位是“金融研究辅助”，不是投资顾问或自动交易系统。系统默认不连接券商账户、不读取个人资产、不执行实盘交易；所有输出都区分事实、推断和待验证事项，并附带合规风险提示。

## 亮点能力

- **清小搭接入**：支持 `POST /v1/chat/completions` 和 `x_soda.attachments` 文件产物协议。
- **稳定 A 股数据源**：内置东方财富实时行情/K 线、巨潮资讯公告检索、可选 akshare 财务字段，并带缓存、超时和降级。
- **财报/公告附件解析**：支持用户上传 `pdf/docx/xlsx/txt/md/csv/json`，自动抽取关键段落。
- **多股票选股池**：内置 A 股演示股票池，按动量、趋势、波动、成交活跃度、财务质量和数据可用性打分。
- **回测闭环**：支持外部回测网关；未配置时自动使用本地 MA10/MA30 均线策略回测兜底。
- **图表报告**：自动生成价格趋势图、选股评分图、回测净值图，并输出 Markdown/PDF 报告。
- **评审演示样例**：提供单股研究、选股池、回测、附件分析四类 JSON 请求。

## 快速启动

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

## 清小搭接入配置

- Base URL：部署后的公网地址，例如 `https://your-domain.example.com`
- Chat Completions：`POST /v1/chat/completions`
- Models：`GET /v1/models`
- 鉴权：可选 Bearer Token。设置 `QINGYAN_API_TOKEN` 后，清小搭侧需要配置同一 token。
- 文件输出：响应顶层会返回 `x_soda.attachments`，包含 PDF、Markdown 和图表 PNG。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `QINGYAN_HOST` | `0.0.0.0` | 服务监听地址 |
| `QINGYAN_PORT` | `8787` | 服务监听端口 |
| `QINGYAN_API_TOKEN` | 空 | 可选 Bearer Token |
| `QINGYAN_PUBLIC_BASE_URL` | 空 | 公网地址，用于生成附件 URL |
| `QINGYAN_REPORT_DIR` | `outputs/reports` | 报告输出目录 |
| `QINGYAN_CACHE_DIR` | `outputs/cache` | 数据缓存目录 |
| `QINGYAN_ANNOUNCEMENT_LOOKBACK_DAYS` | `180` | 公告检索回看天数 |
| `QINGYAN_BACKTEST_GATEWAY_URL` | 空 | 可选外部回测网关地址 |
| `QINGYAN_BACKTEST_GATEWAY_TOKEN` | 空 | 可选外部回测 token |
| `QINGYAN_ENABLE_AKSHARE` | `false` | 是否启用可选 akshare 财务字段；演示时默认关闭以提升稳定性 |

## 演示请求

```powershell
python scripts/run_demo_requests.py --base-url http://localhost:8787
```

也可以直接查看：

- `examples/demo_requests/01_single_stock_research.json`
- `examples/demo_requests/02_screening.json`
- `examples/demo_requests/03_backtest.json`
- `examples/demo_requests/04_file_analysis.json`

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
2. 接入更稳定的财务数据库和公告全文解析。
3. 增加 DCF、杜邦分析、盈利质量评分等财务模型。
4. 增加多因子组合回测、交易成本、涨跌停/停牌约束。
5. 增加评审页面或小型 dashboard 展示报告产物。
