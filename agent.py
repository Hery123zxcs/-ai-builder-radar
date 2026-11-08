"""LangChain agent creation, invocation, and secret-safe tool trace extraction."""

from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain_deepseek import ChatDeepSeek

from config import Settings, get_settings
from schemas import AgentRunResult, GitHubRepository, ToolDebugEvent
from tools import AGENT_TOOLS


SYSTEM_PROMPT = """你是AI开发者生态研究助手。

规则：
1. 搜索、发现或推荐项目时必须先调用search_github_repositories，不能依靠模型记忆生成项目。
2. 项目名称、链接和所有数值指标必须来自本次Tool返回值。
3. 语义判断只能基于README、description、topics和homepage等GitHub公开元数据。
4. 缺少证据时返回null、空数组或“数据不足”，不得补造事实。
5. 不得编造融资、收入、客户、合作状态、团队规模、私人联系方式或Builder私人背景。
6. 明确区分GitHub客观指标、模型语义判断和人工评价。
7. 当前Stars/Forks是累计值；无两个不同时间点快照时不得称为增长或增速。
8. 项目潜力与Builder执行能力必须分开；Builder数据不足时明确说明。
9. 所有推荐只是生态初筛，不是投资或商业结论。
10. 输出语言跟随用户输入语言；工具失败或无结果时如实说明。
"""


def build_agent(settings: Settings | None = None) -> Any:
    settings = settings or get_settings()
    model = ChatDeepSeek(
        model=settings.require_deepseek_model(),
        api_key=settings.require_deepseek_key(),
        temperature=0.1,
        timeout=settings.request_timeout_seconds,
        max_retries=2,
    )
    return create_agent(model=model, tools=AGENT_TOOLS, system_prompt=SYSTEM_PROMPT)


def run_agent(
    keyword: str,
    limit: int = 5,
    min_stars: int | None = None,
    language: str | None = None,
    updated_after: str | None = None,
    ecosystem_context: str | None = None,
    settings: Settings | None = None,
) -> AgentRunResult:
    settings = settings or get_settings()
    settings.require_deepseek_key()
    settings.require_deepseek_model()
    filters = []
    if min_stars is not None:
        filters.append(f"stars:>={min_stars}")
    if language and language.strip():
        filters.append(f"language:{language.strip()}")
    if updated_after and updated_after.strip():
        filters.append(f"pushed:>={updated_after.strip()}")
    exact_query = " ".join([keyword.strip(), *filters])
    user_message = (
        f"请发现与“{keyword.strip()}”相关的公开AI项目。必须调用"
        f"search_github_repositories，keyword使用{exact_query!r}，limit使用{limit}。"
        f"目标生态背景：{ecosystem_context or '未提供具体生态背景'}。"
        "只能分析本次工具返回的数据，并说明这是生态初筛。"
    )
    state = build_agent(settings).invoke(
        {"messages": [{"role": "user", "content": user_message}]}
    )
    return _extract_run_result(state.get("messages", []))


def _extract_run_result(messages: list[Any]) -> AgentRunResult:
    pending_calls: dict[str, tuple[str, dict[str, Any]]] = {}
    events: list[ToolDebugEvent] = []
    repositories: list[GitHubRepository] = []
    final_message = ""
    for message in messages:
        for call in getattr(message, "tool_calls", []) or []:
            pending_calls[call.get("id", "")] = (
                call.get("name", "unknown"),
                call.get("args") or {},
            )
        if getattr(message, "type", "") == "tool":
            call_id = getattr(message, "tool_call_id", "")
            tool_name, tool_input = pending_calls.get(
                call_id, (getattr(message, "name", "unknown"), {})
            )
            try:
                payload = json.loads(_message_text(message))
                repo_items = payload.get("repositories") or []
                if not repo_items and isinstance(payload.get("data"), dict):
                    data = payload["data"]
                    if "full_name" in data:
                        repo_items = [data]
                parsed = [GitHubRepository.model_validate(item) for item in repo_items]
                repositories.extend(parsed)
                events.append(
                    ToolDebugEvent(
                        tool=tool_name,
                        input=tool_input,
                        status="success" if payload.get("ok") else "error",
                        returned_count=(
                            payload.get("count")
                            if isinstance(payload.get("count"), int)
                            else len(parsed)
                        ),
                        error=payload.get("error"),
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                events.append(
                    ToolDebugEvent(
                        tool=tool_name,
                        input=tool_input,
                        status="error",
                        error=f"Could not parse tool response: {exc}",
                    )
                )
        if getattr(message, "type", "") == "ai" and not (
            getattr(message, "tool_calls", []) or []
        ):
            text = _message_text(message)
            if text:
                final_message = text
    if not final_message:
        final_message = "Agent did not return a final analysis."
    unique = {repo.full_name: repo for repo in repositories}
    return AgentRunResult(
        final_message=final_message,
        tool_events=events,
        repositories=list(unique.values()),
    )


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        ).strip()
    return str(content or "")
