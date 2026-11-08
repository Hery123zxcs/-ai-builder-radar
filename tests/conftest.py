from datetime import UTC, datetime, timedelta

import pytest

from schemas import (
    ActivitySummary,
    ContributorsSummary,
    GitHubRepository,
    ReadmeInfo,
    ReleaseSummary,
    RepositoryBundle,
)


@pytest.fixture
def complete_bundle():
    now = datetime.now(UTC)
    return RepositoryBundle(
        repository=GitHubRepository(
            name="radar",
            full_name="builder/radar",
            repository_url="https://github.com/builder/radar",
            owner_login="builder",
            owner_type="Organization",
            owner_profile_url="https://github.com/builder",
            description="Evidence-grounded AI project discovery.",
            topics=["ai", "rag"],
            primary_language="Python",
            stars=1200,
            forks=120,
            watchers=30,
            open_issues=12,
            created_at=now - timedelta(days=700),
            updated_at=now,
            pushed_at=now - timedelta(days=10),
            archived=False,
            fork=False,
            homepage="https://example.com/demo",
            license="Apache-2.0",
            default_branch="main",
        ),
        readme=ReadmeInfo(
            text="# Radar\nInstall with pip.\nUsage example.\nDeploy with Docker.",
            length=1000,
            has_installation=True,
            has_usage_examples=True,
            has_deployment=True,
            has_contributing=False,
        ),
        releases=ReleaseSummary(
            has_release=True,
            releases_count=8,
            latest_release_at=now - timedelta(days=30),
        ),
        contributors=ContributorsSummary(
            contributors_count=8,
            top_contributors=["a", "b"],
            single_maintainer_risk=False,
        ),
        activity=ActivitySummary(
            recent_issues_count=8,
            recent_pull_requests_count=5,
            recent_activity_at=now - timedelta(days=2),
            updated_in_last_90_days=True,
            continuously_maintained=True,
        ),
    )
