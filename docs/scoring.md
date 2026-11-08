# AI Builder Radar V0.2 评分规则

## 总原则

数值评分由 `scoring.py` 计算。LLM 只提供有逐字 Evidence、置信度不低于 0.6 的
A/B/G 语义判断；缺少数据的维度 `available=false`，不计 0 分，也不填中性分。

```text
Available Score
= Σ(可用维度 raw_score × weight / 100)
  ÷ Σ(可用维度 weight)
  × 100

Data Coverage = Σ(可用维度 weight) ÷ 100
```

Confidence 是可用维度置信度的权重平均，再乘以 `0.5 + 0.5 × Coverage`。因此即便
有效维度得分较高，覆盖率很低时 Confidence 仍会下降。

## 八个维度

| 维度 | 权重 | 来源 | 规则 |
|---|---:|---|---|
| A 问题价值与市场时机 | 15 | `readme_analysis` | DeepSeek 结构化判断；需原文 Evidence、confidence ≥ 0.6 |
| B 技术差异化 | 15 | `readme_analysis` | 同上；项目名称本身不能作为差异化证据 |
| C 产品化程度 | 15 | `github_metric` | README 20、安装说明 20、使用示例 20、Homepage/Demo 10、License 10、Release 20 |
| D 执行速度与持续性 | 15 | `github_metric` | Push 新鲜度 60、Release 新鲜度 20、近90天 Issue/PR 活动 20；归档仓库为0 |
| E 真实吸引力与增长 | 15 | `github_metric` / `historical_snapshot` | 当前 Stars 对数信号 40、Forks 对数信号 20；有双时间点快照时 Star变化30、Fork变化10；缺失子项按有效子权重归一化 |
| F Builder执行与协作能力 | 10 | `github_metric` | 公开贡献者数量35、近90天 Issue/PR协作30、维护连续性15、本次结果中的相关项目10、公开完成项目10；缺核心协作数据则不可用 |
| G 生态合作价值 | 10 | `readme_analysis` | 有 Evidence 的 DeepSeek 判断；无生态背景时仅允许通用初筛 |
| H 安全、许可与合规 | 5 | `github_metric` | License 50、非归档25、非Fork 15、公开README 10；不推断未公开安全状态 |

### C 产品化程度

README 不存在与 README API 请求失败必须区分：确认 404 时可作为“没有 README”，网络
失败时该子数据视为缺失。安装、使用、部署和贡献说明由 Python 在 README 文本中查找
公开关键词，不由 LLM 猜测。

### D 执行持续性

- Push ≤30天：60；≤90天：45；≤180天：25；更久：5。
- Release ≤90天：20；≤365天：10；更久：3。
- 近90天持续公开活动：20；有活动但不足以说明持续：10；无活动：0。

这些规则说明的是公开维护信号，不代表团队规模或商业执行。

### E 吸引力与真实增长

Stars 和 Forks 只作为当前累计吸引力信号，并使用对数缩放以避免单个超大项目完全支配
结果。它们绝不被称为增长速度。

第一次查询没有历史增长：

```text
growth.available = false
reason = "暂无历史快照"
```

后续仅比较当前值与上一个不同 `captured_at` 的快照：

```text
Star变化 = 当前Stars - 上次Stars
Fork变化 = 当前Forks - 上次Forks
```

必须同时展示起止时间。没有两个时间点时，不填中性增长分，也不生成“增长最快”。

### F Builder执行

第一版只使用 owner 类型、公开主页、贡献者数量、公开 Issue/PR 活动和维护连续性。
不使用 Stars 给 Builder 打高分，不采集或评价学历、公司、年龄、性别、国籍、私人经历、
私人联系方式或未公开团队规模，也不使用无法验证的“贡献者质量”。

## 分组分数

- `Project Potential Score`：A–E 的可用维度归一化。
- `Builder Execution Score`：F；数据不全时显示“数据不足”。
- `Ecosystem Fit Score`：G；无有效语义证据时显示“数据不足”。
- `Overall Priority Score`：A–H 所有可用维度归一化。

## 风险标签

风险只来自客观规则或经校验的语义证据，包括：

- No historical data
- Low data coverage
- New project
- Inactive repository
- Archived repository
- Forked repository
- No license / Commercial use unclear
- No release
- No public demo
- Limited contributors / Single maintainer risk
- Weak documentation
- LLM evidence insufficient

## 为什么不能只看 Stars

Stars 可能反映知名度、历史积累或短期传播，却不能单独证明产品成熟度、持续维护、
Builder协作能力、技术差异化、生态适配、License状态或真实时间增长。因此 Stars 只是
E 维度的一部分，且评分始终同时显示 Coverage、Confidence、分项依据和风险标签。
