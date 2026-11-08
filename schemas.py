"""Typed contracts shared by collection, scoring, analysis, persistence, and UI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


SourceType = Literal[
    "github_metric", "historical_snapshot", "readme_analysis", "manual_review"
]
EvidenceSource = Literal["readme", "description", "topics", "homepage"]


class RateLimitInfo(BaseModel):
    remaining: int | None = None
    limit: int | None = None
    reset_at: datetime | None = None


class GitHubRepository(BaseModel):
    name: str
    full_name: str
    repository_url: str
    owner_login: str
    owner_type: str | None = None
    owner_profile_url: str | None = None
    description: str | None = None
    topics: list[str] = Field(default_factory=list)
    primary_language: str | None = None
    stars: int | None = None
    forks: int | None = None
    watchers: int | None = None
    open_issues: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    pushed_at: datetime | None = None
    archived: bool | None = None
    fork: bool | None = None
    homepage: str | None = None
    license: str | None = None
    default_branch: str | None = None

    @property
    def owner(self) -> str:
        """Backward-compatible owner name used by V0.1 callers."""
        return self.owner_login


class GitHubSearchResult(BaseModel):
    query: str
    count: int
    total_count: int
    authenticated: bool
    rate_limit: RateLimitInfo = Field(default_factory=RateLimitInfo)
    repositories: list[GitHubRepository]


class ReadmeInfo(BaseModel):
    text: str | None = None
    length: int | None = None
    has_installation: bool | None = None
    has_usage_examples: bool | None = None
    has_deployment: bool | None = None
    has_contributing: bool | None = None


class ReleaseSummary(BaseModel):
    has_release: bool | None = None
    releases_count: int | None = None
    latest_release_at: datetime | None = None


class ContributorsSummary(BaseModel):
    contributors_count: int | None = None
    top_contributors: list[str] = Field(default_factory=list)
    single_maintainer_risk: bool | None = None


class ActivitySummary(BaseModel):
    recent_issues_count: int | None = None
    recent_pull_requests_count: int | None = None
    recent_activity_at: datetime | None = None
    updated_in_last_90_days: bool | None = None
    continuously_maintained: bool | None = None


class RepositoryBundle(BaseModel):
    repository: GitHubRepository
    readme: ReadmeInfo = Field(default_factory=ReadmeInfo)
    releases: ReleaseSummary = Field(default_factory=ReleaseSummary)
    contributors: ContributorsSummary = Field(default_factory=ContributorsSummary)
    activity: ActivitySummary = Field(default_factory=ActivitySummary)
    rate_limit: RateLimitInfo = Field(default_factory=RateLimitInfo)
    collection_errors: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    claim: str
    source: EvidenceSource
    quote: str = Field(min_length=1, max_length=500)


class SemanticDimensionJudgment(BaseModel):
    dimension: Literal["problem_value", "technical_differentiation", "ecosystem_fit"]
    score: float = Field(ge=0, le=100)
    explanation: str
    evidence_claims: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ProjectSemanticAnalysis(BaseModel):
    project_summary: str | None = None
    problem_solved: str | None = None
    target_users: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    technical_stack: list[str] = Field(default_factory=list)
    technical_differentiation: list[str] = Field(default_factory=list)
    problem_value: str | None = None
    product_maturity_explanation: str | None = None
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    ecosystem_fit: list[str] = Field(default_factory=list)
    collaboration_opportunities: list[str] = Field(default_factory=list)
    outreach_angle: str | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    dimension_judgments: list[SemanticDimensionJudgment] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class DimensionScore(BaseModel):
    dimension_name: str
    raw_score: float | None = Field(default=None, ge=0, le=100)
    weight: float = Field(gt=0, le=100)
    weighted_score: float | None = Field(default=None, ge=0)
    available: bool
    source_type: SourceType
    evidence: list[str] = Field(default_factory=list)
    explanation: str
    confidence: float = Field(ge=0, le=1)

class GrowthMetrics(BaseModel):
    available: bool = False
    reason: str = "暂无历史快照"
    start_at: datetime | None = None
    end_at: datetime | None = None
    star_change: int | None = None
    fork_change: int | None = None


class ScoreCard(BaseModel):
    dimensions: list[DimensionScore]
    project_potential_score: float | None = None
    builder_execution_score: float | None = None
    ecosystem_fit_score: float | None = None
    overall_priority_score: float | None = None
    data_coverage: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    risk_tags: list[str] = Field(default_factory=list)


class Snapshot(BaseModel):
    id: int | None = None
    repo_full_name: str
    captured_at: datetime
    stars: int | None = None
    forks: int | None = None
    open_issues: int | None = None
    contributors_count: int | None = None
    pushed_at: datetime | None = None
    total_score: float | None = None
    score_coverage: float | None = None


class ManualReview(BaseModel):
    repo_full_name: str
    relevant: bool
    worth_following: bool
    priority: Literal["High", "Medium", "Low"]
    notes: str = ""
    reviewed_at: datetime


class OutreachRecord(BaseModel):
    repo_full_name: str
    builder: str
    why_relevant: str | None = None
    potential_collaboration: str | None = None
    suggested_outreach_angle: str | None = None
    public_profile_url: str | None = None
    status: Literal[
        "Not Reviewed", "Interested", "Contacted", "Replied", "Follow-up", "Closed"
    ] = "Not Reviewed"
    notes: str = ""
    updated_at: datetime


class ProjectEvaluation(BaseModel):
    bundle: RepositoryBundle
    semantic_analysis: ProjectSemanticAnalysis | None = None
    semantic_error: str | None = None
    scorecard: ScoreCard
    growth: GrowthMetrics = Field(default_factory=GrowthMetrics)


class ToolDebugEvent(BaseModel):
    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    status: Literal["success", "error"] = "success"
    returned_count: int | None = None
    error: str | None = None


class AgentRunResult(BaseModel):
    final_message: str
    tool_events: list[ToolDebugEvent] = Field(default_factory=list)
    repositories: list[GitHubRepository] = Field(default_factory=list)


class DiscoveryResult(BaseModel):
    evaluations: list[ProjectEvaluation] = Field(default_factory=list)
    tool_events: list[ToolDebugEvent] = Field(default_factory=list)
    agent_message: str | None = None
    rate_limit: RateLimitInfo = Field(default_factory=RateLimitInfo)
    errors: list[str] = Field(default_factory=list)
