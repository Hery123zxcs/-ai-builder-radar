"""GitHub REST client with safe errors, bounded retries, caching, and enrichment."""

from __future__ import annotations

import base64
import re
import time
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

import httpx

from config import Settings
from schemas import (
    ActivitySummary,
    ContributorsSummary,
    GitHubRepository,
    GitHubSearchResult,
    RateLimitInfo,
    ReadmeInfo,
    ReleaseSummary,
    RepositoryBundle,
)


class GitHubAPIError(RuntimeError):
    """A secret-safe GitHub API failure suitable for UI and tool output."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def clean_search_keyword(keyword: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", keyword or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        raise ValueError("Search keyword must not be empty.")
    if len(cleaned) > 256:
        raise ValueError("Search keyword must be 256 characters or fewer.")
    return cleaned


def clean_full_name(full_name: str) -> str:
    value = (full_name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        raise ValueError("Repository must use the owner/name format.")
    owner, repository = value.split("/", 1)
    if owner in {".", ".."} or repository in {".", ".."}:
        raise ValueError("Repository must use the owner/name format.")
    return value


class GitHubClient:
    _cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, Any, dict[str, str]]] = {}
    _cache_lock = Lock()

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep_fn: Any = time.sleep,
    ) -> None:
        self.settings = settings
        self._sleep = sleep_fn
        self.rate_limit = RateLimitInfo()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AI-Builder-Radar/0.2",
        }
        if settings.github_token:
            headers["Authorization"] = (
                f"Bearer {settings.github_token.get_secret_value()}"
            )
        self._client = httpx.Client(
            base_url=settings.github_api_base_url,
            headers=headers,
            timeout=settings.request_timeout_seconds,
            transport=transport,
        )

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def search_repositories(self, keyword: str, limit: int = 5) -> GitHubSearchResult:
        query = clean_search_keyword(keyword)
        if not 1 <= limit <= 10:
            raise ValueError("limit must be between 1 and 10.")
        payload, _ = self._request_json(
            "/search/repositories",
            params={"q": query, "per_page": limit, "sort": "stars", "order": "desc"},
        )
        repositories = [_repository_from_api(item) for item in payload.get("items") or []]
        return GitHubSearchResult(
            query=query,
            count=len(repositories),
            total_count=payload.get("total_count") or 0,
            authenticated=self.settings.github_authenticated,
            rate_limit=self.rate_limit,
            repositories=repositories,
        )

    def get_repository_details(self, full_name: str) -> GitHubRepository:
        full_name = clean_full_name(full_name)
        payload, _ = self._request_json(f"/repos/{full_name}")
        return _repository_from_api(payload)

    def get_repository_readme(self, full_name: str, max_chars: int = 20_000) -> ReadmeInfo:
        full_name = clean_full_name(full_name)
        payload, _ = self._request_json(
            f"/repos/{full_name}/readme", allow_404=True
        )
        if payload is None:
            return ReadmeInfo()
        try:
            raw = base64.b64decode(payload.get("content") or "", validate=False)
            text = raw.decode("utf-8", errors="replace")
        except (ValueError, TypeError):
            return ReadmeInfo()
        text = text[:max_chars]
        lowered = text.lower()
        return ReadmeInfo(
            text=text,
            length=len(text),
            has_installation=_contains_heading_or_phrase(
                lowered, ("install", "installation", "getting started", "setup")
            ),
            has_usage_examples=_contains_heading_or_phrase(
                lowered, ("usage", "example", "quickstart", "quick start")
            ),
            has_deployment=_contains_heading_or_phrase(
                lowered, ("deploy", "deployment", "docker", "kubernetes")
            ),
            has_contributing=_contains_heading_or_phrase(
                lowered, ("contributing", "contribution guide", "how to contribute")
            ),
        )

    def get_repository_releases(self, full_name: str) -> ReleaseSummary:
        full_name = clean_full_name(full_name)
        payload, _ = self._request_json(
            f"/repos/{full_name}/releases", params={"per_page": 100}, allow_404=True
        )
        releases = payload or []
        published = [
            _parse_datetime(item.get("published_at"))
            for item in releases
            if item.get("published_at")
        ]
        return ReleaseSummary(
            has_release=bool(releases),
            releases_count=len(releases),
            latest_release_at=max(published) if published else None,
        )

    def get_repository_contributors_summary(
        self, full_name: str
    ) -> ContributorsSummary:
        full_name = clean_full_name(full_name)
        payload, headers = self._request_json(
            f"/repos/{full_name}/contributors",
            params={"per_page": 1, "anon": "true"},
            allow_404=True,
        )
        contributors = payload or []
        count = _count_from_link_header(headers.get("link")) or len(contributors)
        names = [
            str(item.get("login") or item.get("name"))
            for item in contributors[:5]
            if item.get("login") or item.get("name")
        ]
        return ContributorsSummary(
            contributors_count=count,
            top_contributors=names,
            single_maintainer_risk=(count <= 1) if count is not None else None,
        )

    def get_repository_activity_summary(self, full_name: str) -> ActivitySummary:
        full_name = clean_full_name(full_name)
        since = datetime.now(UTC) - timedelta(days=90)
        payload, _ = self._request_json(
            f"/repos/{full_name}/issues",
            params={
                "state": "all",
                "since": since.isoformat(),
                "per_page": 100,
                "sort": "updated",
                "direction": "desc",
            },
            allow_404=True,
        )
        items = payload or []
        prs = sum(bool(item.get("pull_request")) for item in items)
        issues = len(items) - prs
        updated_dates = [
            _parse_datetime(item.get("updated_at"))
            for item in items
            if item.get("updated_at")
        ]
        latest = max(updated_dates) if updated_dates else None
        return ActivitySummary(
            recent_issues_count=issues,
            recent_pull_requests_count=prs,
            recent_activity_at=latest,
            updated_in_last_90_days=bool(items),
            continuously_maintained=(len(items) >= 2) if items else False,
        )

    def collect_repository_bundle(
        self, repository: GitHubRepository
    ) -> RepositoryBundle:
        errors: list[str] = []
        details = repository
        collectors: list[tuple[str, Any, Any]] = [
            ("README", self.get_repository_readme, ReadmeInfo),
            ("Releases", self.get_repository_releases, ReleaseSummary),
            (
                "Contributors",
                self.get_repository_contributors_summary,
                ContributorsSummary,
            ),
            ("Activity", self.get_repository_activity_summary, ActivitySummary),
        ]
        values: dict[str, Any] = {}
        try:
            details = self.get_repository_details(repository.full_name)
        except GitHubAPIError as exc:
            errors.append(f"Details: {exc}")
        for label, collector, fallback in collectors:
            try:
                values[label] = collector(repository.full_name)
            except GitHubAPIError as exc:
                errors.append(f"{label}: {exc}")
                values[label] = fallback()
        return RepositoryBundle(
            repository=details,
            readme=values["README"],
            releases=values["Releases"],
            contributors=values["Contributors"],
            activity=values["Activity"],
            rate_limit=self.rate_limit,
            collection_errors=errors,
        )

    def _request_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> tuple[Any, dict[str, str]]:
        normalized = tuple(
            sorted((str(key), str(value)) for key, value in (params or {}).items())
        )
        cache_key = (f"{self.settings.github_api_base_url}{path}", normalized)
        cached = self._get_cache(cache_key)
        if cached is not None:
            payload, headers = cached
            self._update_rate_limit(headers)
            return payload, headers

        last_error: Exception | None = None
        for attempt in range(self.settings.github_max_retries + 1):
            try:
                response = self._client.get(path, params=params)
            except httpx.TimeoutException as exc:
                last_error = GitHubAPIError(
                    "GitHub request timed out. Please try again later."
                )
            except httpx.RequestError as exc:
                last_error = GitHubAPIError(
                    "Could not reach GitHub API. Check the network and try again."
                )
            else:
                headers = {key.lower(): value for key, value in response.headers.items()}
                self._update_rate_limit(headers)
                if response.status_code == 404 and allow_404:
                    return None, headers
                if response.is_success:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise GitHubAPIError(
                            "GitHub returned an invalid JSON response.",
                            response.status_code,
                        ) from exc
                    self._set_cache(cache_key, payload, headers)
                    return payload, headers
                if 500 <= response.status_code <= 599:
                    last_error = GitHubAPIError(
                        "GitHub API is temporarily unavailable. Please try again later.",
                        response.status_code,
                    )
                else:
                    self._raise_for_status(response)
            if attempt < self.settings.github_max_retries:
                self._sleep(0.25 * (2**attempt))
        assert last_error is not None
        raise last_error

    def _get_cache(
        self, key: tuple[str, tuple[tuple[str, str], ...]]
    ) -> tuple[Any, dict[str, str]] | None:
        if self.settings.github_cache_ttl_seconds <= 0:
            return None
        with self._cache_lock:
            item = self._cache.get(key)
            if not item:
                return None
            captured, payload, headers = item
            if time.monotonic() - captured > self.settings.github_cache_ttl_seconds:
                self._cache.pop(key, None)
                return None
            return payload, headers

    def _set_cache(
        self,
        key: tuple[str, tuple[tuple[str, str], ...]],
        payload: Any,
        headers: dict[str, str],
    ) -> None:
        if self.settings.github_cache_ttl_seconds <= 0:
            return
        with self._cache_lock:
            self._cache[key] = (time.monotonic(), payload, headers)

    def _update_rate_limit(self, headers: dict[str, str]) -> None:
        self.rate_limit = RateLimitInfo(
            remaining=_optional_int(headers.get("x-ratelimit-remaining")),
            limit=_optional_int(headers.get("x-ratelimit-limit")),
            reset_at=_timestamp_to_datetime(headers.get("x-ratelimit-reset")),
        )

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        try:
            detail = response.json().get("message", "")
        except (ValueError, AttributeError):
            detail = ""
        if status in (403, 429) and (
            remaining == "0" or "rate limit" in detail.lower()
        ):
            suffix = f" Reset timestamp: {reset}." if reset else ""
            raise GitHubAPIError(
                "GitHub API rate limit reached. Add GITHUB_TOKEN for a higher limit "
                f"or retry after the reset.{suffix}",
                status,
            )
        messages = {
            401: "GitHub authentication failed. Check GITHUB_TOKEN or use anonymous access.",
            403: "GitHub denied the request. Check permissions or rate limits.",
            404: "GitHub repository or resource was not found.",
            422: "GitHub rejected the query. Simplify the input and try again.",
            429: "GitHub is rate limiting requests. Please retry later.",
        }
        if status in messages:
            raise GitHubAPIError(messages[status], status)
        if 500 <= status <= 599:
            raise GitHubAPIError(
                "GitHub API is temporarily unavailable. Please try again later.", status
            )
        raise GitHubAPIError(f"GitHub API request failed with HTTP {status}.", status)


def _repository_from_api(item: dict[str, Any]) -> GitHubRepository:
    owner = item.get("owner") or {}
    license_data = item.get("license") or {}
    return GitHubRepository(
        name=item.get("name") or "",
        full_name=item.get("full_name") or "",
        repository_url=item.get("html_url") or "",
        owner_login=owner.get("login") or "",
        owner_type=owner.get("type"),
        owner_profile_url=owner.get("html_url"),
        description=item.get("description"),
        topics=item.get("topics") or [],
        primary_language=item.get("language"),
        stars=item.get("stargazers_count"),
        forks=item.get("forks_count"),
        watchers=item.get("subscribers_count", item.get("watchers_count")),
        open_issues=item.get("open_issues_count"),
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at"),
        pushed_at=item.get("pushed_at"),
        archived=item.get("archived"),
        fork=item.get("fork"),
        homepage=item.get("homepage") or None,
        license=license_data.get("spdx_id") or license_data.get("name"),
        default_branch=item.get("default_branch"),
    )


def _contains_heading_or_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _timestamp_to_datetime(value: str | None) -> datetime | None:
    parsed = _optional_int(value)
    return datetime.fromtimestamp(parsed, UTC) if parsed is not None else None


def _count_from_link_header(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"[?&]page=(\d+)[^>]*>;\s*rel=\"last\"", value)
    return int(match.group(1)) if match else None
