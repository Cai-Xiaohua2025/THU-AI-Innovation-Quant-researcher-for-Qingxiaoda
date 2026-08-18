from __future__ import annotations

from pypdf import PdfReader

from qingyan_agent.config import Settings
from qingyan_agent.reporting import ChartService, moving_average, prepare_pdf_markdown, sparse_tick_positions, write_pdf


def test_sparse_tick_positions_keep_endpoints_and_limit_density():
    positions = sparse_tick_positions(90, max_ticks=8)
    assert positions[0] == 0
    assert positions[-1] == 89
    assert len(positions) == 8
    assert positions == sorted(set(positions))


def test_moving_average_keeps_series_alignment():
    assert moving_average([1, 2, 3, 4], 3) == [None, None, 2.0, 3.0]


def test_price_chart_with_many_rows_renders_sparse_date_axis(tmp_path, monkeypatch):
    captured = {}

    def capture_xticks(positions, labels, **kwargs):
        captured["positions"] = list(positions)
        captured["labels"] = list(labels)

    import matplotlib.pyplot as plt

    monkeypatch.setattr(plt, "xticks", capture_xticks)
    settings = Settings(report_dir=tmp_path, cache_dir=tmp_path / "cache")
    rows = [{
        "date": f"2026-01-{(index % 28) + 1:02d}",
        "close": 30 + index * 0.1,
    } for index in range(90)]
    path = ChartService(settings).price_chart("测试价格趋势", rows)
    assert path is not None and path.exists()
    assert len(captured["positions"]) == 8
    assert len(captured["labels"]) == 8


def test_prepare_pdf_markdown_removes_internal_json():
    markdown = """# 测试报告

## 用户问题
分析长江电力

## 结构化元数据
```json
{"payload": {"secret_internal_shape": true}}
```

## 研究结论摘要
这是面向用户的结论。
"""
    prepared = prepare_pdf_markdown(markdown)
    assert "结构化元数据" not in prepared
    assert "secret_internal_shape" not in prepared
    assert "研究结论摘要" in prepared


def test_write_pdf_renders_chinese_markdown(tmp_path):
    markdown = """# 清研量策测试报告

## 用户问题
请分析长江电力600900。

## 结构化元数据
```json
{"payload": {"internal": true}}
```

## 研究结论摘要
当前属于**中性震荡**，数据日期为`2026-08-14`。

### 关键证据
- MA5低于MA20
- 成交量需要继续核验

> 以上内容不构成投资建议。

| 指标 | 数值 |
| --- | --- |
| MA5 | 28.144 |
| MA20 | 28.545 |
"""
    path = tmp_path / "rendered.pdf"
    assert write_pdf(path, markdown, []) is True
    assert path.read_bytes().startswith(b"%PDF-")
    reader = PdfReader(str(path))
    assert len(reader.pages) >= 1
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "清研量策测试报告" in text
    assert "中性震荡" in text
    assert "MA20" in text
    assert "结构化元数据" not in text
    assert '"internal"' not in text
    assert "**" not in text
    assert reader.metadata.title == "清研量策测试报告"
    assert reader.metadata.author == "清研量策"
    assert "清研量策·A股研究助手" in text
