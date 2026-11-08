"""Application orchestration that keeps objective collection independent from LLMs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent import run_agent
from config import Settings, get_settings
from database import RadarDatabase
from github_client import GitHubAPIError, GitHubClient
from llm_analyzer import analyze_repository
from schemas import (
    DiscoveryResult,
    GrowthMetrics,
    ProjectEvaluation,
    RepositoryBundle,
    Snapshot,
    ToolDebugEvent,
)
from scoring import calculate_scorecard


def discover_projects(
    keyword: str,
    limit: int,
    min_stars: int | None = None,
    language: str | None = None,
    updated_after: str | None = None,
    ecosystem_context: str | None = None,
    enable_llm: bool = True,
    *,
    settings: Settings | None = None,
) -> DiscoveryResult:
    """Collect, enrich, score, snapshot, and optionally analyze up to ten real repos."""
    settings = settings or get_settings()
    filters = []
    if min_stars is not None:
        filters.append(f"stars:>={min_stars}")
    if language and language.strip():
        filters.append(f"language:{language.strip()}")
    if updated_after and updated_after.strip():
        filters.append(f"pushed:>={updated_after.strip()}")
    query = " ".join([keyword.strip(), *filters])
    errors: list[str] = []
    events: list[ToolDebugEvent] = []
    agent_message: str | None = None

    with GitHubClient(settings) as client:
        try:
            search = client.search_repositories(query, limit)
            events.append(
                ToolDebugEvent(
                    tool="search_github_repositories",
                    input={"keyword": query, "limit": limit},
                    status="success",
                    returned_count=search.count,
                )
            )
        except (ValueError, GitHubAPIError) as exc:
            return DiscoveryResult(
                tool_events=[
                    ToolDebugEvent(
                        tool="search_github_repositories",
                        input={"keyword": query, "limit": limit},
                        status="error",
                        returned_count=0,
                        error=str(exc),
                    )
                ],
                errors=[str(exc)],
                rate_limit=client.rate_limit,
            )
        bundles = [client.collect_repository_bundle(repo) for repo in search.repositories]
        rate_limit = client.rate_limit

    if enable_llm:
        if not settings.deepseek_configured or not settings.deepseek_model_configured:
            errors.append(
                "LLM深度分析未运行：DEEPSEEK_API_KEY或DEEPSEEK_MODEL未配置。"
            )
        else:
            try:
                agent_result = run_agent(
                    keyword=keyword,
                    limit=limit,
                    min_stars=min_stars,
                    language=language,
                    updated_after=updated_after,
                    ecosystem_context=ecosystem_context,
                    settings=settings,
                )
                events.extend(agent_result.tool_events)
                agent_message = agent_result.final_message
            except Exception as exc:
                errors.append(f"LangChain Agent运行失败：{type(exc).__name__}")

    database = RadarDatabase(settings.database_path)
    evaluations: list[ProjectEvaluation] = []
    owner_related: dict[str, int] = {}
    owner_recent: dict[str, int] = {}
    owner_completed: dict[str, int] = {}
    recent_cutoff = datetime.now(UTC) - timedelta(days=90)
    for bundle in bundles:
        owner = bundle.repository.owner_login
        owner_related[owner] = owner_related.get(owner, 0) + 1
        pushed = bundle.repository.pushed_at
        if pushed and pushed >= recent_cutoff:
            owner_recent[owner] = owner_recent.get(owner, 0) + 1
        if bundle.readme.text and (
            bundle.releases.has_release or bundle.repository.homepage
        ):
            owner_completed[owner] = owner_completed.get(owner, 0) + 1
    for bundle in bundles:
        semantic = None
        semantic_error = None
        if enable_llm and settings.deepseek_configured and settings.deepseek_model_configured:
            semantic, semantic_error = analyze_repository(
                bundle, ecosystem_context, settings=settings
            )
        captured_at = datetime.now(UTC)
        previous = database.get_snapshots(bundle.repository.full_name, 1)
        growth = _growth_against_latest(bundle, captured_at, previous)
        owner = bundle.repository.owner_login
        scorecard = calculate_scorecard(
            bundle,
            growth,
            semantic,
            builder_related_projects=owner_related.get(owner),
            builder_recent_projects=owner_recent.get(owner, 0),
            builder_completed_projects=owner_completed.get(owner, 0),
        )
        database.save_snapshot(
            Snapshot(
                repo_full_name=bundle.repository.full_name,
                captured_at=captured_at,
                stars=bundle.repository.stars,
                forks=bundle.repository.forks,
                open_issues=bundle.repository.open_issues,
                contributors_count=bundle.contributors.contributors_count,
                pushed_at=bundle.repository.pushed_at,
                total_score=scorecard.overall_priority_score,
                score_coverage=scorecard.data_coverage,
            )
        )
        evaluations.append(
            ProjectEvaluation(
                bundle=bundle,
                semantic_analysis=semantic,
                semantic_error=semantic_error,
                scorecard=scorecard,
                growth=growth,
            )
        )
        errors.extend(
            f"{bundle.repository.full_name} — {error}"
            for error in bundle.collection_errors
        )
    return DiscoveryResult(
        evaluations=evaluations,
        tool_events=events,
        agent_message=agent_message,
        rate_limit=rate_limit,
        errors=errors,
    )


def _growth_against_latest(
    bundle: RepositoryBundle,
    captured_at: datetime,
    previous: list[Snapshot],
) -> GrowthMetrics:
    if not previous:
        return GrowthMetrics()
    prior = previous[0]
    if prior.captured_at == captured_at:
        return GrowthMetrics(reason="暂无两个不同时间点的历史快照")
    repo = bundle.repository
    return GrowthMetrics(
        available=True,
        reason="当前公开指标与上一次本地快照的变化",
        start_at=prior.captured_at,
        end_at=captured_at,
        star_change=(
            repo.stars - prior.stars
            if repo.stars is not None and prior.stars is not None
            else None
        ),
        fork_change=(
            repo.forks - prior.forks
            if repo.forks is not None and prior.forks is not None
            else None
        ),
    )
