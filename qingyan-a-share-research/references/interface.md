# 命令行与输出接口

## 输入参数

| 参数 | 是否必需 | 说明 |
| --- | --- | --- |
| `--question TEXT` | 正常研究必需 | 原始自然语言问题；支持股票名称、六位代码和研究范围词。 |
| `--file PATH` | 否，可重复 | 本地 `pdf/docx/xlsx/txt/md/csv/json` 附件。单文件上限默认 25 MiB。 |
| `--image PATH` | 否，可重复 | 本地 PNG/JPEG/WebP/GIF。精确数值应以结构化行情为准。 |
| `--output-dir PATH` | 否 | 产物目录，默认当前目录下的 `qingyan-output`。 |
| `--fee-bps N` | 否 | 回测单边手续费，单位基点，范围 0–500。 |
| `--slippage-bps N` | 否 | 回测单边滑点，单位基点，范围 0–500。 |
| `--risk-free-rate N` | 否 | 回测年化无风险利率，小数，范围 -0.1–0.3。 |
| `--timeout N` | 否 | 单次外部数据请求超时秒数，范围 1–120。 |
| `--self-test` | 否 | 不访问网络，验证导入、技术指标、回测、意图识别和合规守卫。 |

## stdout JSON

正常研究成功时返回一个 JSON 对象：

```json
{
  "ok": true,
  "mode": "research",
  "title": "宁德时代走势与技术指标研究报告",
  "answer": "聊天用研究结论……",
  "artifacts": [
    {
      "path": "/absolute/path/report.md",
      "mime_type": "text/markdown",
      "size": 12345,
      "sha256": "..."
    }
  ],
  "evidence_completeness": {},
  "missing_evidence": [],
  "warnings": [],
  "data_statuses": [],
  "model_metadata": {}
}
```

- `answer`：适合直接回复用户的中文 Markdown。
- `artifacts`：仅列出已落盘、可读取且做过 SHA-256 的文件。以此字段为交付依据。
- `evidence_completeness`：研究计划的证据完整性结果。
- `missing_evidence`：缺失证据；非空不一定代表程序失败，但必须向用户披露。
- `warnings`：标的纠错、身份冲突、证据限制等警告。
- `data_statuses`：每个数据源的成功/失败与原因。不得删除失败状态后伪装成完整研究。
- `model_metadata`：上游模型是否配置、是否实际使用和是否回退。

自检成功时返回 `{"ok": true, "mode": "self-test", ...}`。自检不证明外部数据源当前可用，只证明技能本体的本地可执行路径正常。

## 错误规则

- 参数、路径、文件大小或依赖错误：退出码 `2`，stdout 返回 `ok: false`，stderr 给出简短原因。
- 运行时意外错误：退出码 `1`，stdout 返回 `ok: false`；不会输出密钥或完整环境变量。
- 行情、公告等单一外部源失败：通常仍以退出码 `0` 返回降级研究，并在证据字段中标记失败。

## 问题到研究模式的映射

程序沿用实验代码的规则意图识别：

- “走势、均线、技术、支撑、压力、量价” → 技术研究。
- “财报、营收、利润、现金流、ROE、基本面” → 基本面研究。
- “公告、消息、事件、原因” → 公告研究。
- “筛选、候选池、选股池、排名” → 多股票筛选。
- “回测、策略、MA10/MA30” → 回测。
- 同时明确多个主题或要求“综合/全面” → 综合研究。

若用户只给出图片而没有股票，技能可以做图片安全读取；没有视觉模型时必须明确说明无法可靠识别图中内容，不能猜测刻度。
