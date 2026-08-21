---
name: qingyan-a-share-research
description: 面向中国A股的合规、可审计金融研究技能。用于用户要求研究上交所、深交所或北交所股票，查询行情与K线，分析均线、动量、波动和量价，检索并解读巨潮公告，比较候选股票池，执行MA10/MA30历史回测，分析财报或表格附件，或生成带证据状态和风险提示的中文Markdown研究报告时。也适用于用户提到“清研量策”“A股研究”“股票筛选”“公告归因”“策略回测”或六位A股代码的场景；不用于实盘交易、个性化投资建议、收益承诺或代客理财。
---

# 清研量策·A股研究

使用随技能提供的确定性研究程序完成 A 股投研。程序来自“清研量策”实验代码，支持多数据源降级、证据完整性检查、本地回测、附件摘要和报告产物；上游大模型为可选项，未配置时也必须给出确定性结果。

## 执行流程

1. 将包含本文件的目录记为技能目录，不要假定当前工作目录就是技能目录。
2. 首次使用或运行环境变化后，执行：

   ```bash
   python3 <技能目录>/scripts/qingyan_research.py --self-test
   ```

3. 若自检仅提示缺少依赖，在用户允许安装当前环境依赖的前提下，先安装 `<技能目录>/requirements-minimal.txt`。需要 PDF、PNG、PDF/XLSX 解析时安装 `<技能目录>/requirements.txt`。不要要求 API Key 才开始工作。
4. 把用户的原始自然语言问题完整传给 `--question`。不要先把问题改写成可能改变研究范围的交易指令。
5. 将本地附件逐个用 `--file` 传入；将本地行情图逐个用 `--image` 传入。文件必须来自用户给出的路径，不要扫描无关目录。
6. 将 `--output-dir` 指向任务专用目录。解析 stdout 的 JSON；读取 `answer` 作为聊天结论，并把 `artifacts` 中实际存在的文件交付给用户。
7. 检查 `evidence_completeness`、`missing_evidence` 和 `warnings`。网络或数据源失败时，原样披露数据不足，不得补造价格、公告、财务数字或来源。

## 常用调用

单股技术面、基本面、公告或综合研究：

```bash
python3 <技能目录>/scripts/qingyan_research.py \
  --question "请对宁德时代300750做技术面与近期公告综合研究" \
  --output-dir ./qingyan-output
```

候选股票筛选：

```bash
python3 <技能目录>/scripts/qingyan_research.py \
  --question "筛选A股候选池，比较趋势、波动、量能和风险" \
  --output-dir ./qingyan-output
```

本地 MA10/MA30 历史回测：

```bash
python3 <技能目录>/scripts/qingyan_research.py \
  --question "回测贵州茅台600519的MA10/MA30均线策略并说明局限" \
  --fee-bps 3 --slippage-bps 2 \
  --output-dir ./qingyan-output
```

分析用户附件：

```bash
python3 <技能目录>/scripts/qingyan_research.py \
  --question "结合这份财报附件分析300750的经营质量和风险" \
  --file ./report.pdf \
  --output-dir ./qingyan-output
```

## 研究口径

- 只研究 A 股公开信息；股票身份出现名称/代码冲突时停止合并证据，并明确提示重新核验。
- 优先使用在线行情；在线源失败时允许使用程序缓存，但必须保留 `is_stale` 或数据状态提示。
- 将规则生成的趋势标签视为指标归纳，不要当作第二份独立证据重复计权。
- 把均线、阶段高低点称为动态“参考支撑/压力观察位”，同时说明验证条件与失效条件。
- 只有证据中存在成交量序列或变化指标时才讨论量能变化；没有市场/行业对照时，不把绝对收益描述为相对强弱。
- 公告正文读取失败或被截断时，只能依据已成功取得的标题、链接和受限摘录，不得声称覆盖完整公告。
- 回测是历史模拟；必须披露样本期、费用/滑点口径、未强制平仓等限制，不把历史结果解释成未来收益。
- 不输出“必涨”“稳赚”或确定性买卖指令，不连接券商，不自动下单，不收集个人资产数据。

## 输出处理

程序始终在 stdout 返回 UTF-8 JSON。关键字段和故障处理见 [references/interface.md](references/interface.md)。需要解释指标、数据源、回测假设或合规边界时读取 [references/methodology.md](references/methodology.md)。

默认生成 Markdown；完整依赖可用时还会生成 PDF 和 PNG。只交付 `artifacts` 中列出的真实文件，不要承诺因可选依赖缺失而未生成的格式。程序退出码非零时，向用户说明 stderr 中的可操作原因，并保留已生成的文件。

## 可选上游模型

仅当运行环境已经安全配置以下变量时使用上游模型：`QINGYAN_LLM_BASE_URL`、`QINGYAN_LLM_MODEL`，以及网关需要时的 `QINGYAN_LLM_API_KEY`。不要在命令行参数、输出或报告中回显密钥。未配置或调用失败时继续使用本地确定性草稿。
