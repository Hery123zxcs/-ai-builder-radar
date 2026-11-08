# AI Builder Radar V0.2

AI Builder Radar 是面向开发者关系、开源生态、技术战略和产品团队的 AI 开发者
生态洞察平台。它通过 GitHub 官方 REST API 获取真实公开数据，用 Python 计算可验证
指标和透明评分，并可选地通过 LangChain + DeepSeek 对 README 与公开元数据做有原文
Evidence 的语义分析。

所有结果都是生态初筛，不是投资或商业结论。

## 设计原则

- 客观字段、时间变化、Coverage 和最终数值由 Python 计算。
- DeepSeek 只负责 README、description、topics、homepage 的语义判断。
- 每项保留的 LLM 判断必须有来源中的短连续原文；无法验证的 Evidence 和结论会被删除。
- 缺少数据的维度显示“数据不足”，不记 0 分，也不填中性分。
- 当前 Stars/Forks 是累计值，不是增速；只有两个不同时间点的本地快照才能计算变化。
- 不采集或推断私人联系方式、收入、融资、客户、团队规模及私人背景。
- 无 DeepSeek Key 时，GitHub 客观采集、评分、历史、人工评价和导出仍然可用。

## 架构

```text
Streamlit app.py
├─ Discover / Ranking / Project Detail / Evaluation / Outreach List
├─ utils.py orchestration
│  ├─ GitHubClient → GitHub REST API
│  ├─ LangChain create_agent → 8 registered @tools
│  ├─ llm_analyzer.py → ChatDeepSeek structured output + Evidence validation
│  ├─ scoring.py → deterministic scoring / coverage / confidence / risks
│  └─ database.py → SQLite snapshots / manual reviews / outreach status
└─ reports.py → CSV / JSON / Markdown weekly report
```

主要文件：

- `app.py`：五个 Streamlit 页面、Debug 和下载入口。
- `agent.py`：`ChatDeepSeek`、`create_agent`、System Prompt 与 Tool 轨迹。
- `tools.py`：8 个 LangChain `@tool`。
- `github_client.py`：搜索、详情、README、Release、Contributor、活动、缓存、重试、限流。
- `scoring.py`：全部确定性数值规则和缺失数据归一化。
- `llm_analyzer.py`：Pydantic 结构化语义分析、原文 Evidence 校验和一次修复重试。
- `database.py`：SQLite 快照、人工评价和外联状态。
- `reports.py`：排行榜、评价、外联 CSV，完整 JSON 和 Markdown 周报。
- `schemas.py`：跨模块 Pydantic Schema。
- `docs/scoring.md`：评分公式、权重和边界。

## LangChain 的职责

`create_agent` 创建带工具调用循环的 DeepSeek Agent。Agent 注册：

1. `search_github_repositories`
2. `get_repository_details`
3. `get_repository_readme`
4. `get_repository_releases`
5. `get_repository_contributors_summary`
6. `get_repository_activity_summary`
7. `save_project_snapshot`
8. `get_project_growth_history`

`llm_analyzer.py` 也通过 LangChain 的 Chat Model 接口执行 Pydantic 结构化输出。LLM 失败
不会删除或替换 GitHub 客观数据。

## 安装

需要 Python 3.11：

```powershell
py -3.11 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

复制配置模板：

```powershell
Copy-Item .env.example .env
```

`.env` 示例：

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash
GITHUB_TOKEN=
GITHUB_API_BASE_URL=https://api.github.com
REQUEST_TIMEOUT_SECONDS=30
GITHUB_MAX_RETRIES=2
GITHUB_CACHE_TTL_SECONDS=300
DATABASE_PATH=ai_builder_radar.db
```

`DEEPSEEK_MODEL` 必须来自环境变量。模板值只是项目初始配置示例，不代表模型一定存在、
账户一定有权限或一定支持 Tool Calling；请改成账号实际可用的模型。`GITHUB_TOKEN`
可选，匿名模式仍能访问公开仓库，但额度更低。不要提交 `.env`。

## 启动与测试

```powershell
python -m streamlit run app.py
```

```powershell
python -m py_compile app.py agent.py tools.py github_client.py scoring.py `
  llm_analyzer.py database.py schemas.py config.py reports.py utils.py
python -m pytest
```

## 数据与评分边界

- Search API 最多返回并分析 10 个项目。
- Release 数量是单次最多 100 条的公开 API 结果，不声称覆盖超过 API 页面上限。
- Contributor、Issue 和 PR 仅使用公开仓库数据，不评价“贡献者质量”。
- `Product Potential`、`Builder Execution`、`Ecosystem Fit` 分开呈现。
- Overall 使用有效维度权重重新归一化，并同时显示 Data Coverage 与 Confidence。
- 首次快照一定显示“暂无历史快照”；Markdown 周报在无双时间点数据时不会生成
  “增长最快”结论。

完整规则见 [docs/scoring.md](docs/scoring.md)。

## 当前限制

- GitHub 匿名配额很低；10 个项目的完整详情采集可能接近匿名小时额度。
- GitHub REST API 不提供商业状态，因此平台不判断融资、收入、客户或合作意愿。
- README 关键词只能验证文档中是否存在安装/使用/部署/贡献说明，不能证明真实采用情况。
- SQLite 是本地单机持久化，V0.2 不包含用户权限和多人并发。
- LLM 结构化输出及 Tool Calling 能否运行取决于配置模型的实际能力和账户权限。
- 第一版外联清单只管理人工状态，不自动发送邮件或私信。
