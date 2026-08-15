# Qingyan Liangce: Qingxiaoda-Compatible Financial Research Agent

Qingyan Liangce is a financial research agent project for the Tsinghua AI Innovation Competition. It focuses on public A-share market research and supports filing analysis, announcement tracking, market trend analysis, multi-stock screening, backtest validation, chart-based reports, and Qingxiaoda integration through an OpenAI-compatible API.

The project is positioned as research assistance, not investment advisory or automated trading. It does not connect to broker accounts, read personal assets, or place live orders. Outputs separate facts, inferences, and uncertainties, and include compliance risk notices.

## Highlights

- **Qingxiaoda integration**: `POST /v1/chat/completions` plus `x_soda.attachments` report artifacts.
- **Stable A-share data layer**: Eastmoney quote/K-line APIs, CNInfo announcement search, optional akshare financial fields, cache, timeout, and graceful degradation.
- **File analysis**: Parses user-uploaded `pdf/docx/xlsx/txt/md/csv/json` files from `file.url`.
- **Multi-stock screening**: Scores a default A-share universe using momentum, trend, volatility control, volume activity, financial quality, and data availability.
- **Backtest loop**: Uses an optional external backtest gateway; falls back to a local MA10/MA30 research simulation when unavailable.
- **Chart reports**: Generates price trend charts, screening score charts, backtest equity charts, Markdown reports, and PDF reports.
- **Demo pack**: Includes single-stock research, screening, backtest, and file-analysis request examples.

## Quick Start

```powershell
pip install -r requirements.txt
python run.py
```

Default URL:

```text
http://localhost:8787
```

Health check:

```powershell
Invoke-RestMethod http://localhost:8787/health
```

Run tests:

```powershell
$env:PYTHONPATH="src"
python -m pytest tests -q
```

## Production Deployment

The repository includes Gunicorn, systemd, and Nginx configurations. The recommended topology is:

```text
public :8787 -> Nginx -> 127.0.0.1:18787 -> Gunicorn -> Flask
```

After installing dependencies, validate the production entrypoint with:

```bash
PYTHONPATH=src gunicorn --config gunicorn.conf.py wsgi:app
```

Deployment templates are available in:

- `deploy/qingyan-agent.service`
- `deploy/nginx-qingyan-agent.conf`

For a public Qingxiaoda integration, configure `QINGYAN_PUBLIC_BASE_URL` with an HTTPS URL backed by a valid certificate. Response buffering must remain disabled at the reverse proxy so SSE chunks reach the client immediately.

## Optional Upstream LLM

The service can use any OpenAI-compatible Chat Completions gateway. When it is not configured, or when it times out or fails, the deterministic local research workflow remains available.

Configure these values in `.env`:

```dotenv
QINGYAN_LLM_BASE_URL=https://your-gateway.example.com/v1
QINGYAN_LLM_API_KEY=your-upstream-api-key
QINGYAN_LLM_MODEL=your-model-name
```

The base URL may be a host root, a `/v1` URL, or the complete `/v1/chat/completions` endpoint. Restart `qingyan-agent` after changing the configuration. Market data, indicators, screening scores, and backtests remain local deterministic computations; the upstream model is used only for question understanding, evidence synthesis, attachment-summary analysis, and report writing. Evidence and attachment excerpts are sent to the configured upstream service, so use a trusted provider for sensitive material.

## Qingxiaoda Setup

- Base URL: deployed public URL, for example `https://your-domain.example.com`
- Chat Completions: `POST /v1/chat/completions`
- Models: `GET /v1/models`
- Auth: optional Bearer Token. If `QINGYAN_API_TOKEN` is set, configure the same token in the client.
- Artifacts: responses include top-level `x_soda.attachments` with PDF, Markdown, and chart PNG files.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `QINGYAN_HOST` | `0.0.0.0` | Bind host |
| `QINGYAN_PORT` | `8787` | Bind port |
| `QINGYAN_API_TOKEN` | empty | Optional Bearer Token |
| `QINGYAN_PUBLIC_BASE_URL` | empty | Public URL for attachment links |
| `QINGYAN_REPORT_DIR` | `outputs/reports` | Report output directory |
| `QINGYAN_CACHE_DIR` | `outputs/cache` | Data cache directory |
| `QINGYAN_MAX_REQUEST_BYTES` | `2097152` | Maximum API request body size |
| `QINGYAN_MAX_DOWNLOAD_BYTES` | `26214400` | Maximum remote attachment size |
| `QINGYAN_MAX_FILES_PER_REQUEST` | `5` | Maximum attachments per request |
| `QINGYAN_REQUEST_TIMEOUT_SEC` | `12` | External data and attachment request timeout |
| `QINGYAN_ANNOUNCEMENT_LOOKBACK_DAYS` | `180` | Announcement lookback window |
| `QINGYAN_ALLOW_PRIVATE_FILE_URLS` | `false` | Allow private-network attachment URLs; not recommended for public deployments |
| `QINGYAN_TRUSTED_PROXY_COUNT` | `0` | Number of trusted reverse proxies; use `1` with the provided Nginx configuration |
| `QINGYAN_CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins |
| `QINGYAN_BACKTEST_GATEWAY_URL` | empty | Optional external backtest gateway |
| `QINGYAN_BACKTEST_GATEWAY_TOKEN` | empty | Optional external backtest token |
| `QINGYAN_LLM_BASE_URL` | empty | OpenAI-compatible upstream address; empty disables the upstream model |
| `QINGYAN_LLM_API_KEY` | empty | Upstream gateway API key |
| `QINGYAN_LLM_MODEL` | empty | Actual upstream model name |
| `QINGYAN_LLM_TIMEOUT_SEC` | `90` | Upstream response timeout |
| `QINGYAN_LLM_MAX_TOKENS` | `1800` | Maximum upstream output tokens |
| `QINGYAN_LLM_MAX_INPUT_CHARS` | `60000` | Maximum evidence characters sent upstream |
| `QINGYAN_LLM_TEMPERATURE` | `0.2` | Upstream generation temperature |
| `QINGYAN_ENABLE_AKSHARE` | `false` | Enable optional akshare financial fields; disabled by default for faster demos |

## Demo Requests

```powershell
python scripts/run_demo_requests.py --base-url http://localhost:8787
```

Examples:

- `examples/demo_requests/01_single_stock_research.json`
- `examples/demo_requests/02_screening.json`
- `examples/demo_requests/03_backtest.json`
- `examples/demo_requests/04_file_analysis.json`

## Compliance Boundaries

- No return guarantees.
- No asset management.
- No deterministic buy/sell instructions.
- No automatic order execution.
- No broker account connection.
- No personal asset collection.
- No data-permission bypass.
- Backtest results are historical simulations, not future-performance claims.
