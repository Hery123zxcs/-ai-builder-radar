"""Evidence-grounded semantic analysis through LangChain and ChatDeepSeek."""

from __future__ import annotations

from typing import Any

from langchain_core.output_parsers import PydanticOutputParser
from langchain_deepseek import ChatDeepSeek
from pydantic import ValidationError

from config import ConfigurationError, Settings, get_settings
from schemas import ProjectSemanticAnalysis, RepositoryBundle


ANALYSIS_PROMPT = """你是AI开源项目语义分析器。只能使用下面提供的GitHub公开元数据和README。

严格要求：
- 不得编造Star、Fork、Contributor、Release、增长、融资、收入、客户、团队规模或合作状态。
- 每一个非空判断都必须在evidence中有一条对应claim。
- evidence.quote必须是给定来源中的短连续原文，不得改写。
- source只能是readme、description、topics或homepage。
- 找不到原文证据的字段返回null或空数组。
- 不得把项目名称本身作为技术差异化证据。
- dimension_judgments只允许problem_value、technical_differentiation、ecosystem_fit；
  只有证据充分时才评分，confidence低于0.6时不要输出该判断。
- 未提供目标生态背景时，ecosystem_fit只能是通用初步判断，不能给具体合作结论。
- 输出是生态初筛，不是投资或商业结论。

项目公开数据：
{source_text}

目标生态背景：
{ecosystem_context}
"""


def build_semantic_model(settings: Settings | None = None) -> ChatDeepSeek:
    settings = settings or get_settings()
    return ChatDeepSeek(
        model=settings.require_deepseek_model(),
        api_key=settings.require_deepseek_key(),
        temperature=0,
        max_tokens=2500,
        timeout=settings.request_timeout_seconds,
        max_retries=0,
    )


def analyze_repository(
    bundle: RepositoryBundle,
    ecosystem_context: str | None = None,
    *,
    settings: Settings | None = None,
    model: Any | None = None,
) -> tuple[ProjectSemanticAnalysis | None, str | None]:
    """Return validated analysis or an error; objective GitHub data is never replaced."""
    try:
        base_model = model or build_semantic_model(settings)
    except ConfigurationError as exc:
        return None, str(exc)
    parser = PydanticOutputParser(pydantic_object=ProjectSemanticAnalysis)
    analysis_model = (
        base_model.bind_tools([ProjectSemanticAnalysis])
        if hasattr(base_model, "bind_tools")
        else base_model
    )
    sources = _source_map(bundle)
    prompt = ANALYSIS_PROMPT.format(
        source_text=_source_text(sources),
        ecosystem_context=(ecosystem_context or "未提供具体生态背景"),
    )
    prompt = (
        prompt
        + "\n\n必须调用ProjectSemanticAnalysis工具提交结果。"
        "若无法调用工具，则严格输出下面Schema要求的JSON：\n"
        + parser.get_format_instructions()
    )
    last_error = "LLM analysis failed."
    for attempt in range(2):
        try:
            response = analysis_model.invoke(
                prompt
                if attempt == 0
                else prompt
                + "\n上次输出未通过结构或Evidence校验。"
                "请只输出有效JSON，并删除无逐字证据的判断后重新输出。"
            )
            tool_calls = getattr(response, "tool_calls", []) or []
            if tool_calls:
                analysis = ProjectSemanticAnalysis.model_validate(
                    tool_calls[0].get("args") or {}
                )
            else:
                content = getattr(response, "content", response)
                if not isinstance(content, str):
                    raise TypeError("Model did not return text JSON.")
                analysis = parser.parse(content)
            validated, warnings = validate_evidence(
                analysis, sources, bundle.repository.name
            )
            if validated.evidence:
                return validated, "; ".join(warnings) if warnings else None
            last_error = "LLM evidence insufficient: no quote matched its declared source."
        except (ValidationError, ValueError, TypeError) as exc:
            last_error = f"LLM structured output validation failed: {exc}"
        except Exception as exc:
            last_error = f"LLM analysis request failed: {type(exc).__name__}"
    return None, last_error


def validate_evidence(
    analysis: ProjectSemanticAnalysis,
    sources: dict[str, str],
    project_name: str = "",
) -> tuple[ProjectSemanticAnalysis, list[str]]:
    """Remove unverifiable evidence and every semantic claim that lacks valid evidence."""
    valid = []
    warnings: list[str] = []
    for item in analysis.evidence:
        source_text = sources.get(item.source, "")
        quote = item.quote.strip()
        if quote and quote.casefold() in source_text.casefold():
            valid.append(item)
        else:
            warnings.append(f"Removed unverifiable evidence for: {item.claim}")

    valid_claims = [item.claim.strip() for item in valid if item.claim.strip()]

    def supported(value: str | None) -> bool:
        if not value:
            return False
        normalized = value.strip().casefold()
        return any(
            normalized in claim.casefold() or claim.casefold() in normalized
            for claim in valid_claims
        )

    def supported_list(values: list[str]) -> list[str]:
        return [value for value in values if supported(value)]

    def supported_technical(values: list[str]) -> list[str]:
        kept = []
        for value in values:
            matching = [
                item
                for item in valid
                if value.casefold() in item.claim.casefold()
                or item.claim.casefold() in value.casefold()
            ]
            if matching and not (
                project_name
                and all(
                    item.quote.strip().casefold() == project_name.casefold()
                    for item in matching
                )
            ):
                kept.append(value)
        return kept

    judgments = []
    for judgment in analysis.dimension_judgments:
        claims_valid = judgment.evidence_claims and all(
            claim in valid_claims for claim in judgment.evidence_claims
        )
        name_only = (
            judgment.dimension == "technical_differentiation"
            and project_name
            and all(
                evidence.quote.strip().casefold() == project_name.casefold()
                for evidence in valid
                if evidence.claim in judgment.evidence_claims
            )
        )
        if claims_valid and not name_only and judgment.confidence >= 0.6:
            judgments.append(judgment)
        else:
            warnings.append(f"Removed unsupported judgment: {judgment.dimension}")

    total_evidence = max(1, len(analysis.evidence))
    confidence = min(analysis.confidence, len(valid) / total_evidence)
    cleaned = analysis.model_copy(
        update={
            "project_summary": (
                analysis.project_summary if supported(analysis.project_summary) else None
            ),
            "problem_solved": (
                analysis.problem_solved if supported(analysis.problem_solved) else None
            ),
            "target_users": supported_list(analysis.target_users),
            "categories": supported_list(analysis.categories),
            "technical_stack": supported_list(analysis.technical_stack),
            "technical_differentiation": supported_technical(
                analysis.technical_differentiation
            ),
            "problem_value": (
                analysis.problem_value if supported(analysis.problem_value) else None
            ),
            "product_maturity_explanation": (
                analysis.product_maturity_explanation
                if supported(analysis.product_maturity_explanation)
                else None
            ),
            "strengths": supported_list(analysis.strengths),
            "risks": supported_list(analysis.risks),
            "ecosystem_fit": supported_list(analysis.ecosystem_fit),
            "collaboration_opportunities": supported_list(
                analysis.collaboration_opportunities
            ),
            "outreach_angle": (
                analysis.outreach_angle if supported(analysis.outreach_angle) else None
            ),
            "evidence": valid,
            "dimension_judgments": judgments,
            "confidence": confidence,
        }
    )
    return cleaned, warnings


def _source_map(bundle: RepositoryBundle) -> dict[str, str]:
    repo = bundle.repository
    return {
        "readme": bundle.readme.text or "",
        "description": repo.description or "",
        "topics": ", ".join(repo.topics),
        "homepage": repo.homepage or "",
    }


def _source_text(sources: dict[str, str]) -> str:
    return "\n\n".join(
        f"[{name}]\n{text[:8_000]}" for name, text in sources.items()
    )
