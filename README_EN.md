# Qingyan Liangce: Qingxiaoda-Compatible Financial Research Agent

Qingyan Liangce is a financial research agent project for the Tsinghua AI Innovation Competition. It focuses on public A-share market research and supports filing analysis, announcement tracking, market trend analysis, multi-stock screening, backtest validation, chart-based reports, and Qingxiaoda integration through an OpenAI-compatible API.

The project is positioned as research assistance, not investment advisory or automated trading. It does not connect to broker accounts, read personal assets, or place live orders. Outputs separate facts, inferences, and uncertainties, and include compliance risk notices.

## Highlights

- **Qingxiaoda integration**: `POST /v1/chat/completions` plus `x_soda.attachments` report artifacts.
- **Stable A-share data layer**: Tencent, Sina, and Eastmoney quote/K-line providers in fallback order, CNINFO security and announcement lookup, optional AkShare fundamentals, cache, timeout, and structured source status.
- **File and announcement analysis**: Parses user-uploaded `pdf/docx/xlsx/txt/md/csv/json` files and, for announcement requests, downloads recent CNINFO PDFs, extracts page-labelled text, and caches the bounded result.
- **Layered answer length**: `AnswerProfile` supports `concise`, `standard`, and `detailed`; ordinary Qingxiaoda questions default to `standard`, while Markdown/PDF artifacts retain the complete evidence-oriented report.
- **Safe multi-turn context**: Prior user turns are used only when a follow-up genuinely needs target inheritance. The latest user turn independently controls the target, intent, answer profile, and evidence scope; a new company name, mistyped code, or name/code conflict triggers fresh validation instead of silently reusing the previous stock.
- **Structured announcement research**: Each important filing is represented by facts, inferences, potential impacts, risks, verification items, and source pages. Chat responses show only a bounded set of conclusions; raw filing text is kept in the detailed-report appendix.
- **Deduplicated upstream context**: Structured evidence excludes full filing bodies. Raw text is included once through budgeted `source_excerpts`, and exact repeated long blocks are conservatively removed from the final answer.
- **Multi-stock screening**: Scores a default A-share universe using momentum, trend, volatility control, volume activity, financial quality, and data availability.
- **Backtest loop**: Uses an optional external gateway or a local MA10/MA30 simulation with CAGR, volatility, Sharpe, Calmar, win rate, exposure, turnover, benchmark, and excess-return metrics.
- **Auditable research planning**: Generates bounded rule-driven steps and deterministically checks target, quote, technical, fundamental, announcement, image, or backtest evidence by intent.
- **Institutional research standard**: QY-A-SHARE-RESEARCH-2.0 separates raw facts, derived indicators, model labels, analytical inference, and open verification items, with testable scenarios and invalidation conditions.
- **Professional charts and PDF reports**: Combines price, MA5/MA20/MA60, and volume; PDFs include embedded Chinese fonts, research-style tables, running headers/footers, and the Qingyan A-share Research Assistant corner brand.
- **Demo pack**: Includes single-stock research, screening, backtest, and file-analysis request examples.

## Quick Start

```powershell
pip install -r requirements.txt
python run.py
```

Install the optional AkShare fundamentals provider when needed:

```bash
pip install -r requirements-optional.txt
# or
pip install -e '.[fundamentals]'
```

For production, install `deploy/qingyan-agent-fundamentals.conf` as the systemd drop-in
`/etc/systemd/system/qingyan-agent.service.d/10-fundamentals.conf` and
`deploy/qingyan-agent-fundamentals.env` as `/etc/qingyan-agent/fundamentals.env`, followed by
`systemctl daemon-reload` and `systemctl restart qingyan-agent`. The later EnvironmentFile overrides the
default disabled value without modifying or copying other values from the main `.env`. Once enabled, an older
metadata-only “provider disabled” cache entry does not prevent a fresh fundamentals request.

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

On Ubuntu/Debian, install an embeddable CJK font so generated PDFs render consistently in browsers and attachment previewers:

```bash
sudo apt-get install -y fonts-wqy-zenhei
```

```bash
PYTHONPATH=src gunicorn --config gunicorn.conf.py wsgi:app
```

Deployment templates are available in:

- `deploy/qingyan-agent.service`
- `deploy/nginx-qingyan-agent.conf`

For a public Qingxiaoda integration, configure `QINGYAN_PUBLIC_BASE_URL` with an HTTPS URL backed by a valid certificate. Reverse-proxy response buffering should remain disabled for SSE compatibility. Streaming requests establish SSE first and emit additive `x_qingyan` progress events for acceptance, attachment reading, research, artifact generation, and completion. The answer itself is still buffered until evidence and fallback checks finish; upstream tokens are not passed through live.

## Optional Upstream LLM

The service can use any OpenAI-compatible Chat Completions gateway. When it is not configured, or when it times out or fails, the deterministic local research workflow remains available.

Configure these values in `.env`:

```dotenv
QINGYAN_LLM_BASE_URL=https://your-gateway.example.com/v1
QINGYAN_LLM_API_KEY=your-upstream-api-key
QINGYAN_LLM_MODEL=your-model-name
```

The base URL may be a host root, a `/v1` URL, or the complete `/v1/chat/completions` endpoint. Restart `qingyan-agent` after changing the configuration. Market data, indicators, screening scores, backtests, filing fact extraction, and evidence-completeness checks remain local deterministic computations; the upstream model is used only for question understanding, evidence synthesis, attachment-summary analysis, and report writing. Full filing bodies are removed from structured evidence and may be included only once as bounded `source_excerpts`, but attachment summaries and necessary evidence can still be sent to the configured upstream service, so use a trusted provider for sensitive material.

Natural combined questions such as “review the recent trend and also check important announcements” are resolved as full research rather than announcement-only requests. Evidence completeness is calculated once from the intent-specific `ResearchContext`, so an unrequested or disabled fundamentals provider does not incorrectly downgrade a technical-plus-announcement answer.

## Qingxiaoda Setup

- Base URL: deployed public URL, for example `https://your-domain.example.com`
- Chat Completions: `POST /v1/chat/completions`
- Models: `GET /v1/models`
- Auth: optional Bearer Token. If `QINGYAN_API_TOKEN` is set, configure the same token in the client.
- Artifacts: responses include top-level `x_soda.attachments` with PDF, Markdown, and chart PNG files; clickable artifact links are also appended to the message for clients that hide top-level attachment metadata.
- Image input: accepts OpenAI/Qingxiaoda `image_url` content parts. The server downloads public images and forwards them to the vision-capable upstream model for chart analysis.

## A-share Coverage and Market-data Semantics

- Security identity is resolved dynamically through CNINFO rather than being limited to the local demonstration universe.
- SSE, SZSE, and BSE A-shares are supported. Legacy BSE `4/8` codes are normalized to current `920` codes when CNINFO provides the mapping.
- Quotes use Tencent first, then Sina and Eastmoney as fallbacks, with an approximately 30-second short cache.
- Daily bars use Tencent forward-adjusted data first. Sina unadjusted data is used when Tencent history is insufficient, including BSE cases, and the adjustment basis is exposed in the result. K-lines use an approximately 180-second cache.
- An online quote snapshot is not a guaranteed zero-latency exchange feed. Closed markets return the latest trading-day snapshot, and source delay may exist during trading hours.
- Stale validated cache is used only when online sources fail and is explicitly marked with `is_stale=true`.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `QINGYAN_HOST` | `0.0.0.0` | Bind host |
| `QINGYAN_PORT` | `8787` | Bind port |
| `QINGYAN_API_TOKEN` | empty | Optional Bearer Token |
| `QINGYAN_PUBLIC_BASE_URL` | empty | Public URL for attachment links |
| `QINGYAN_REPORT_DIR` | `outputs/reports` | Report output directory |
| `QINGYAN_CACHE_DIR` | `outputs/cache` | Data cache directory |
| `QINGYAN_CONVERSATION_DIR` | `outputs/conversations` | Local JSON archive for successful chats, grouped by date |
| `QINGYAN_SAVE_CONVERSATIONS` | `true` | Persist successful chats locally without authorization headers or API keys |
| `QINGYAN_CONVERSATION_MAX_CHARS` | `200000` | Maximum stored characters for one prompt or response |
| `QINGYAN_CACHE_RETENTION_DAYS` | `0` | Cache retention days; `0` disables automatic deletion |
| `QINGYAN_REPORT_RETENTION_DAYS` | `0` | Report/chart retention days; `0` disables automatic deletion |
| `QINGYAN_CONVERSATION_RETENTION_DAYS` | `0` | Conversation retention days; `0` disables automatic deletion |
| `QINGYAN_MAX_REQUEST_BYTES` | `2097152` | Maximum API request body size |
| `QINGYAN_MAX_DOWNLOAD_BYTES` | `26214400` | Maximum remote attachment size |
| `QINGYAN_MAX_IMAGE_BYTES` | `10485760` | Maximum remote image size; PNG/JPEG/WebP/GIF are supported |
| `QINGYAN_MAX_FILES_PER_REQUEST` | `5` | Maximum attachments per request |
| `QINGYAN_REQUEST_TIMEOUT_SEC` | `12` | External data and attachment request timeout |
| `QINGYAN_DATA_COLLECTION_WORKERS` | `4` | Maximum workers for parallel quote, K-line, fundamental, and announcement collection |
| `QINGYAN_ANNOUNCEMENT_LOOKBACK_DAYS` | `180` | Announcement lookback window |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_FILES` | `3` | Maximum recent announcement PDFs extracted per request; set to `0` to disable |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_BYTES` | `8388608` | Maximum size of one announcement PDF |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_PAGES` | `20` | Maximum pages read from one announcement PDF |
| `QINGYAN_ANNOUNCEMENT_ATTACHMENT_MAX_CHARS` | `9000` | Maximum extracted characters retained per announcement PDF |
| `QINGYAN_ALLOW_PRIVATE_FILE_URLS` | `false` | Allow private-network attachment URLs; not recommended for public deployments |
| `QINGYAN_REQUIRE_FILE_AUTH` | `false` | Require the API Bearer Token for `/files`; disabled by default for Qingxiaoda preview compatibility |
| `QINGYAN_SIGN_ARTIFACT_URLS` | `false` | Use expiring HMAC-signed `/artifacts/<artifact_id>` URLs for newly generated files; disabled by default for compatibility |
| `QINGYAN_ARTIFACT_SIGNING_KEY` | empty | Artifact signing secret; the API token may be used as fallback when signing is enabled |
| `QINGYAN_ARTIFACT_URL_TTL_SEC` | `3600` | Signed artifact URL lifetime |
| `QINGYAN_ARTIFACT_INDEX_PATH` | `outputs/artifacts/index.json` | Metadata index containing random ID, file name, MIME, size, hash, and timestamps, never absolute server paths |
| `QINGYAN_TRUSTED_PROXY_COUNT` | `0` | Number of trusted reverse proxies; use `1` with the provided Nginx configuration |
| `QINGYAN_CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins |
| `QINGYAN_BACKTEST_GATEWAY_URL` | empty | Optional external backtest gateway |
| `QINGYAN_BACKTEST_GATEWAY_TOKEN` | empty | Optional external backtest token |
| `QINGYAN_BACKTEST_FEE_BPS` | `0` | Local simulation fee per side in basis points |
| `QINGYAN_BACKTEST_SLIPPAGE_BPS` | `0` | Local simulation slippage per side in basis points |
| `QINGYAN_BACKTEST_RISK_FREE_RATE` | `0` | Annual risk-free rate used for Sharpe |
| `QINGYAN_LLM_BASE_URL` | empty | OpenAI-compatible upstream address; empty disables the upstream model |
| `QINGYAN_LLM_API_KEY` | empty | Upstream gateway API key |
| `QINGYAN_LLM_MODEL` | empty | Actual upstream model name |
| `QINGYAN_LLM_TIMEOUT_SEC` | `90` | Upstream response timeout |
| `QINGYAN_LLM_MAX_TOKENS` | `3600` | Maximum upstream output tokens for full research reports |
| `QINGYAN_LLM_MAX_INPUT_CHARS` | `60000` | Maximum evidence characters sent upstream |
| `QINGYAN_LLM_TEMPERATURE` | `0.2` | Upstream generation temperature |
| `QINGYAN_ENABLE_AKSHARE` | `false` | Enable optional akshare financial fields; disabled by default for faster demos |

## Local Conversation Archive

Successful Chat Completions are stored by default under:

```text
outputs/conversations/YYYY-MM-DD/HHMMSS_microseconds_request-id.json
```

Each JSON record contains the role-prefixed prompt, the response actually returned to the client, model and streaming metadata, finish reason, report title, and artifact file names. Authorization headers, server-configured API keys, and attachment URL query parameters are not stored. User-supplied message text is archived as conversation content, so users should not place passwords, keys, or other secrets in prompts. Conversation directories use mode `700`, JSON files use mode `600`, and the archive is not exposed by the `/files` route. Retention defaults to `0`, so nothing is automatically deleted. Deployments may explicitly configure cache, report, and conversation retention days; cleanup is limited to known generated file types and skips symlinks, `.env`, `.orig`, and `.rej` files. Connection probes and rejected invalid requests are not archived.

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

## Development Architecture

The main boundaries are API, research orchestration, deterministic domain calculations, infrastructure adapters, and report artifacts:

```text
qingyan_agent/
├── app.py
├── research_agent.py
├── research_planning.py
├── deterministic_analysis.py
├── announcement_analysis.py  # structured filing facts, inferences, impacts, risks, and page evidence
├── contracts.py
├── domain/indicators/
├── market_data/              # provider protocols, CNInfo, quote/K-line and fundamentals adapters
├── infrastructure/
├── artifacts.py
├── retention.py
├── report_composer.py
└── reporting.py
```

Development checks:

```bash
python -m pip install -e '.[dev]'
ruff check src tests
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m pytest tests -q
```

Filesystem JSON cache writes are atomic and schema-versioned while remaining compatible with legacy cache files. Independent single-stock data sources are collected with a bounded thread pool. SSE establishes the connection early and emits research progress; answer content remains compatibility-buffered after completeness checks, and `/health` reports `upstream_token_passthrough=false`.
