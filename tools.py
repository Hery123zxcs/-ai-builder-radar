"""LangChain tools for public GitHub data and local, non-secret history."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Callable

from langchain.tools import tool

from config import get_settings
from database import RadarDatabase
from github_client import GitHubAPIError, GitHubClient
from schemas import Snapshot


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _github_call(call: Callable[[GitHubClient], Any]) -> str:
    try:
        with GitHubClient(get_settings()) as client:
            result = call(client)
            rate_limit = client.rate_limit.model_dump(mode="json")
        data = (
            result.model_dump(mode="json")
            if hasattr(result, "model_dump")
            else result
        )
        return _json({"ok": True, "data": data, "rate_limit": rate_limit})
    except (ValueError, GitHubAPIError) as exc:
        return _json(
            {
                "ok": False,
                "data": None,
                "error": str(exc),
                "status_code": getattr(exc, "status_code", None),
            }
        )


@tool
def search_github_repositories(keyword: str, limit: int = 5) -> str:
    """Search real public GitHub repositories; limit must be from 1 through 10."""
    try:
        with GitHubClient(get_settings()) as client:
            result = client.search_repositories(keyword=keyword, limit=limit)
        return _json({"ok": True, **result.model_dump(mode="json")})
    except (ValueError, GitHubAPIError) as exc:
        return _json(
            {
                "ok": False,
                "error": str(exc),
                "status_code": getattr(exc, "status_code", None),
                "repositories": [],
                "count": 0,
            }
        )


@tool
def get_repository_details(full_name: str) -> str:
    """Get verified public metadata for one GitHub repository in owner/name form."""
    return _github_call(lambda client: client.get_repository_details(full_name))


@tool
def get_repository_readme(full_name: str) -> str:
    """Get a bounded README excerpt and deterministic documentation flags."""
    return _github_call(
        lambda client: client.get_repository_readme(full_name, max_chars=12_000)
    )


@tool
def get_repository_releases(full_name: str) -> str:
    """Get public release count and latest release timestamp for a repository."""
    return _github_call(lambda client: client.get_repository_releases(full_name))


@tool
def get_repository_contributors_summary(full_name: str) -> str:
    """Get public contributor count and a short contributor summary; no private data."""
    return _github_call(
        lambda client: client.get_repository_contributors_summary(full_name)
    )


@tool
def get_repository_activity_summary(full_name: str) -> str:
    """Summarize public Issue and Pull Request activity from the last 90 days."""
    return _github_call(
        lambda client: client.get_repository_activity_summary(full_name)
    )


@tool
def save_project_snapshot(
    repo_full_name: str,
    stars: int | None = None,
    forks: int | None = None,
    open_issues: int | None = None,
    contributors_count: int | None = None,
    pushed_at: str | None = None,
    total_score: float | None = None,
    score_coverage: float | None = None,
) -> str:
    """Save one timestamped local snapshot of verified project metrics."""
    try:
        snapshot = Snapshot(
            repo_full_name=repo_full_name,
            captured_at=datetime.now(UTC),
            stars=stars,
            forks=forks,
            open_issues=open_issues,
            contributors_count=contributors_count,
            pushed_at=pushed_at,
            total_score=total_score,
            score_coverage=score_coverage,
        )
        row_id = RadarDatabase(get_settings().database_path).save_snapshot(snapshot)
        return _json({"ok": True, "snapshot_id": row_id})
    except (ValueError, OSError) as exc:
        return _json({"ok": False, "error": f"Could not save snapshot: {exc}"})


@tool
def get_project_growth_history(repo_full_name: str) -> str:
    """Get local snapshot history and changes between two distinct capture times."""
    try:
        database = RadarDatabase(get_settings().database_path)
        history = database.get_snapshots(repo_full_name, limit=20)
        growth = database.get_growth(repo_full_name)
        return _json(
            {
                "ok": True,
                "growth": growth.model_dump(mode="json"),
                "snapshots": [item.model_dump(mode="json") for item in history],
            }
        )
    except (ValueError, OSError) as exc:
        return _json({"ok": False, "error": f"Could not read history: {exc}"})


AGENT_TOOLS = [
    search_github_repositories,
    get_repository_details,
    get_repository_readme,
    get_repository_releases,
    get_repository_contributors_summary,
    get_repository_activity_summary,
    save_project_snapshot,
    get_project_growth_history,
]
