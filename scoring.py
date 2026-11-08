"""Transparent deterministic scoring rules for AI Builder Radar V0.2."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Iterable

from schemas import (
    DimensionScore,
    GrowthMetrics,
    ProjectSemanticAnalysis,
    RepositoryBundle,
    ScoreCard,
)


DIMENSION_WEIGHTS = {
    "A. 问题价值与市场时机": 15.0,
    "B. 技术差异化": 15.0,
    "C. 产品化程度": 15.0,
    "D. 执行速度与持续性": 15.0,
    "E. 真实吸引力与增长": 15.0,
    "F. Builder执行与协作能力": 10.0,
    "G. 生态合作价值": 10.0,
    "H. 安全、许可与合规": 5.0,
}


def calculate_scorecard(
    bundle: RepositoryBundle,
    growth: GrowthMetrics | None = None,
    semantic: ProjectSemanticAnalysis | None = None,
    builder_related_projects: int | None = None,
    builder_recent_projects: int | None = None,
    builder_completed_projects: int | None = None,
) -> ScoreCard:
    """Calculate every numeric score in Python; missing dimensions remain unavailable."""
    growth = growth or GrowthMetrics()
    dimensions = [
        _semantic_dimension(
            "A. 问题价值与市场时机", "problem_value", semantic
        ),
        _semantic_dimension(
            "B. 技术差异化", "technical_differentiation", semantic
        ),
        _product_maturity(bundle),
        _execution_continuity(bundle),
        _traction_and_growth(bundle, growth),
        _builder_execution(
            bundle,
            builder_related_projects,
            builder_recent_projects,
            builder_completed_projects,
        ),
        _semantic_dimension("G. 生态合作价值", "ecosystem_fit", semantic),
        _safety_license(bundle),
    ]
    coverage = sum(item.weight for item in dimensions if item.available) / 100
    confidence = _confidence(dimensions, coverage)
    return ScoreCard(
        dimensions=dimensions,
        project_potential_score=normalized_available_score(dimensions[:5]),
        builder_execution_score=normalized_available_score(dimensions[5:6]),
        ecosystem_fit_score=normalized_available_score(dimensions[6:7]),
        overall_priority_score=normalized_available_score(dimensions),
        data_coverage=round(coverage, 4),
        confidence=round(confidence, 4),
        risk_tags=generate_risk_tags(bundle, growth, semantic, coverage),
    )


def normalized_available_score(
    dimensions: Iterable[DimensionScore],
) -> float | None:
    """Σ(raw × weight/100) ÷ Σ(available weight) × 100."""
    available = [
        item
        for item in dimensions
        if item.available and item.raw_score is not None
    ]
    available_weight = sum(item.weight for item in available)
    if available_weight == 0:
        return None
    weighted = sum((item.raw_score or 0) * item.weight / 100 for item in available)
    return round(weighted / available_weight * 100, 2)


def generate_risk_tags(
    bundle: RepositoryBundle,
    growth: GrowthMetrics,
    semantic: ProjectSemanticAnalysis | None,
    coverage: float,
) -> list[str]:
    repo = bundle.repository
    tags: list[str] = []
    now = datetime.now(UTC)
    if not growth.available:
        tags.append("No historical data")
    if coverage < 0.6:
        tags.append("Low data coverage")
    if repo.created_at and _days_since(repo.created_at, now) < 180:
        tags.append("New project")
    if repo.pushed_at and _days_since(repo.pushed_at, now) > 90:
        tags.append("Inactive repository")
    if repo.archived:
        tags.append("Archived repository")
    if repo.fork:
        tags.append("Forked repository")
    if not repo.license:
        tags.extend(["No license", "Commercial use unclear"])
    if bundle.releases.has_release is False:
        tags.append("No release")
    if not repo.homepage:
        tags.append("No public demo")
    count = bundle.contributors.contributors_count
    if count is not None and count <= 2:
        tags.append("Limited contributors")
    if bundle.contributors.single_maintainer_risk:
        tags.append("Single maintainer risk")
    if not bundle.readme.text or (bundle.readme.length or 0) < 500:
        tags.append("Weak documentation")
    if semantic is None or not semantic.evidence:
        tags.append("LLM evidence insufficient")
    return list(dict.fromkeys(tags))


def _semantic_dimension(
    name: str, judgment_name: str, semantic: ProjectSemanticAnalysis | None
) -> DimensionScore:
    weight = DIMENSION_WEIGHTS[name]
    if semantic is not None:
        judgment = next(
            (
                item
                for item in semantic.dimension_judgments
                if item.dimension == judgment_name
                and item.confidence >= 0.6
                and item.evidence_claims
            ),
            None,
        )
        if judgment:
            return _available(
                name,
                judgment.score,
                weight,
                "readme_analysis",
                judgment.evidence_claims,
                judgment.explanation,
                judgment.confidence,
            )
    return _unavailable(
        name,
        weight,
        "readme_analysis",
        "数据不足：缺少置信度不低于0.6且经过原文校验的语义证据。",
    )


def _product_maturity(bundle: RepositoryBundle) -> DimensionScore:
    name = "C. 产品化程度"
    readme_known = not any(
        error.startswith("README:") for error in bundle.collection_errors
    )
    release_known = not any(
        error.startswith("Releases:") for error in bundle.collection_errors
    )
    if not readme_known and not release_known:
        return _unavailable(
            name, DIMENSION_WEIGHTS[name], "github_metric", "数据不足：README和Release均未获取。"
        )
    checks = [
        (bundle.readme.text is not None, 20, "README"),
        (bundle.readme.has_installation is True, 20, "安装说明"),
        (bundle.readme.has_usage_examples is True, 20, "使用示例"),
        (bundle.repository.homepage is not None, 10, "Homepage/Demo"),
        (bundle.repository.license is not None, 10, "License"),
        (bundle.releases.has_release is True, 20, "Release"),
    ]
    score = sum(points for passed, points, _ in checks if passed)
    evidence = [label for passed, _, label in checks if passed]
    return _available(
        name,
        score,
        DIMENSION_WEIGHTS[name],
        "github_metric",
        evidence,
        "由README、安装/使用说明、Homepage、License和Release等可验证信号计算。",
        0.9 if readme_known and release_known else 0.7,
    )


def _execution_continuity(bundle: RepositoryBundle) -> DimensionScore:
    name = "D. 执行速度与持续性"
    pushed = bundle.repository.pushed_at
    if pushed is None:
        return _unavailable(
            name, DIMENSION_WEIGHTS[name], "github_metric", "数据不足：缺少最近Push时间。"
        )
    days = _days_since(pushed, datetime.now(UTC))
    recency = 60 if days <= 30 else 45 if days <= 90 else 25 if days <= 180 else 5
    release_points = 0
    if bundle.releases.latest_release_at:
        release_days = _days_since(
            bundle.releases.latest_release_at, datetime.now(UTC)
        )
        release_points = 20 if release_days <= 90 else 10 if release_days <= 365 else 3
    activity_points = 20 if bundle.activity.continuously_maintained else (
        10 if bundle.activity.updated_in_last_90_days else 0
    )
    score = max(0, recency + release_points + activity_points)
    if bundle.repository.archived:
        score = 0
    return _available(
        name,
        score,
        DIMENSION_WEIGHTS[name],
        "github_metric",
        [
            f"pushed_at={pushed.isoformat()}",
            f"latest_release_at={bundle.releases.latest_release_at}",
            f"recent_activity={bundle.activity.updated_in_last_90_days}",
        ],
        "Push新鲜度占60%，Release新鲜度占20%，近90天公开Issue/PR活动占20%；归档仓库为0。",
        0.9,
    )


def _traction_and_growth(
    bundle: RepositoryBundle, growth: GrowthMetrics
) -> DimensionScore:
    name = "E. 真实吸引力与增长"
    repo = bundle.repository
    components: list[tuple[float, float, str]] = []
    if repo.stars is not None:
        components.append(
            (min(100, math.log10(repo.stars + 1) / 5 * 100), 40, f"stars={repo.stars}")
        )
    if repo.forks is not None:
        components.append(
            (min(100, math.log10(repo.forks + 1) / 4 * 100), 20, f"forks={repo.forks}")
        )
    if growth.available and growth.star_change is not None:
        growth_score = min(100, max(0, growth.star_change) / 100 * 100)
        components.append(
            (
                growth_score,
                30,
                f"star_change={growth.star_change} ({growth.start_at}→{growth.end_at})",
            )
        )
    if growth.available and growth.fork_change is not None:
        components.append(
            (
                min(100, max(0, growth.fork_change) / 20 * 100),
                10,
                f"fork_change={growth.fork_change} ({growth.start_at}→{growth.end_at})",
            )
        )
    if not components:
        return _unavailable(
            name, DIMENSION_WEIGHTS[name], "github_metric", "数据不足：无吸引力或历史快照数据。"
        )
    available_weight = sum(weight for _, weight, _ in components)
    score = sum(value * weight for value, weight, _ in components) / available_weight
    source = "historical_snapshot" if growth.available else "github_metric"
    explanation = (
        "当前Stars/Forks只作为累计吸引力信号；仅在存在两个不同时间点快照时加入真实变化，"
        "绝不把累计Stars称为增速。缺失子项按有效子权重归一化。"
    )
    return _available(
        name,
        score,
        DIMENSION_WEIGHTS[name],
        source,
        [item[2] for item in components],
        explanation,
        0.9 if growth.available else 0.7,
    )


def _builder_execution(
    bundle: RepositoryBundle,
    related_projects: int | None,
    recent_projects: int | None,
    completed_projects: int | None,
) -> DimensionScore:
    name = "F. Builder执行与协作能力"
    count = bundle.contributors.contributors_count
    issue_count = bundle.activity.recent_issues_count
    pr_count = bundle.activity.recent_pull_requests_count
    if count is None or issue_count is None or pr_count is None:
        return _unavailable(
            name,
            DIMENSION_WEIGHTS[name],
            "github_metric",
            "数据不足：需同时获得公开贡献者数量和近90天Issue/PR活动。",
        )
    contributor_score = min(35, math.log2(count + 1) / math.log2(33) * 35)
    collaboration_score = min(30, (issue_count + pr_count) / 20 * 30)
    continuity_score = 15 if bundle.activity.continuously_maintained else 0
    related_score = min(5, (related_projects or 0) / 3 * 5)
    recent_projects_score = min(5, (recent_projects or 0) / 3 * 5)
    completed_score = min(10, (completed_projects or 0) / 2 * 10)
    return _available(
        name,
        contributor_score
        + collaboration_score
        + continuity_score
        + related_score
        + recent_projects_score
        + completed_score,
        DIMENSION_WEIGHTS[name],
        "github_metric",
        [
            f"contributors_count={count}",
            f"recent_issues={issue_count}",
            f"recent_pull_requests={pr_count}",
            f"related_projects_in_results={related_projects}",
            f"recently_updated_related_projects={recent_projects}",
            f"completed_related_projects={completed_projects}",
        ],
        "只使用公开贡献者数量、近90天Issue/PR活动、维护连续性，以及本次搜索结果中"
        "同一Builder的相关项目数量、近期更新和公开完成度；不使用Stars或私人背景。",
        0.8,
    )


def _safety_license(bundle: RepositoryBundle) -> DimensionScore:
    name = "H. 安全、许可与合规"
    repo = bundle.repository
    if repo.archived is None or repo.fork is None:
        return _unavailable(
            name,
            DIMENSION_WEIGHTS[name],
            "github_metric",
            "数据不足：缺少仓库归档/Fork状态。",
        )
    score = (
        (50 if repo.license else 0)
        + (25 if not repo.archived else 0)
        + (15 if not repo.fork else 0)
        + (10 if bundle.readme.text else 0)
    )
    return _available(
        name,
        score,
        DIMENSION_WEIGHTS[name],
        "github_metric",
        [
            f"license={repo.license}",
            f"archived={repo.archived}",
            f"fork={repo.fork}",
        ],
        "License占50%，非归档25%，非Fork 15%，公开README 10%；不推断未公开安全状态。",
        0.9,
    )


def _available(
    name: str,
    raw_score: float,
    weight: float,
    source_type: str,
    evidence: list[str],
    explanation: str,
    confidence: float,
) -> DimensionScore:
    raw = round(max(0, min(100, raw_score)), 2)
    return DimensionScore(
        dimension_name=name,
        raw_score=raw,
        weight=weight,
        weighted_score=round(raw * weight / 100, 4),
        available=True,
        source_type=source_type,  # type: ignore[arg-type]
        evidence=evidence,
        explanation=explanation,
        confidence=confidence,
    )


def _unavailable(
    name: str, weight: float, source_type: str, explanation: str
) -> DimensionScore:
    return DimensionScore(
        dimension_name=name,
        weight=weight,
        available=False,
        source_type=source_type,  # type: ignore[arg-type]
        evidence=[],
        explanation=explanation,
        confidence=0,
    )


def _confidence(dimensions: list[DimensionScore], coverage: float) -> float:
    available = [item for item in dimensions if item.available]
    weight = sum(item.weight for item in available)
    if not weight:
        return 0
    evidence_confidence = sum(
        item.confidence * item.weight for item in available
    ) / weight
    return evidence_confidence * (0.5 + 0.5 * coverage)


def _days_since(value: datetime, now: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max(0, (now - value).days)
