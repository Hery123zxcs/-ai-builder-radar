import httpx
import pytest

from config import Settings
from github_client import (
    GitHubAPIError,
    GitHubClient,
    clean_full_name,
    clean_search_keyword,
)


def make_client(handler, token=None):
    settings = Settings(
        github_token=token, github_cache_ttl_seconds=0, github_max_retries=0
    )
    return GitHubClient(
        settings, transport=httpx.MockTransport(handler), sleep_fn=lambda _: None
    )


def test_clean_search_keyword():
    assert clean_search_keyword("  RAG\n language:python  ") == "RAG language:python"
    with pytest.raises(ValueError):
        clean_search_keyword(" \n ")
    assert clean_full_name("owner/repo") == "owner/repo"
    with pytest.raises(ValueError):
        clean_full_name("../secret")


@pytest.mark.parametrize("limit", [0, 11])
def test_limit_range(limit):
    with make_client(lambda request: httpx.Response(200, json={})) as client:
        with pytest.raises(ValueError, match="between 1 and 10"):
            client.search_repositories("RAG", limit)


def test_search_maps_real_api_shape():
    def handler(request):
        assert request.url.params["q"] == "RAG"
        assert request.url.params["per_page"] == "2"
        return httpx.Response(
            200,
            json={
                "total_count": 1,
                "items": [
                    {
                        "name": "demo",
                        "full_name": "owner/demo",
                        "owner": {"login": "owner"},
                        "description": None,
                        "stargazers_count": 12,
                        "forks_count": 3,
                        "open_issues_count": 1,
                        "language": "Python",
                        "topics": ["rag"],
                        "updated_at": "2026-01-01T00:00:00Z",
                        "pushed_at": "2026-01-02T00:00:00Z",
                        "html_url": "https://github.com/owner/demo",
                        "homepage": "",
                    }
                ],
            },
        )

    with make_client(handler) as client:
        result = client.search_repositories("RAG", 2)
    assert result.count == 1
    assert result.repositories[0].stars == 12
    assert result.repositories[0].homepage is None
    assert result.authenticated is False


def test_token_configuration_is_boolean_and_header_is_not_returned():
    def handler(request):
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"total_count": 0, "items": []})

    with make_client(handler, token="test-token") as client:
        result = client.search_repositories("RAG")
    assert result.authenticated is True
    assert "test-token" not in result.model_dump_json()


@pytest.mark.parametrize("status", [401, 403, 422, 429, 500, 503])
def test_known_http_errors_are_safe(status):
    def handler(request):
        return httpx.Response(status, json={"message": "request failed"})

    with make_client(handler) as client:
        with pytest.raises(GitHubAPIError) as error:
            client.search_repositories("RAG")
    assert error.value.status_code == status


def test_rate_limit_has_clear_message():
    def handler(request):
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "123"},
            json={"message": "API rate limit exceeded"},
        )

    with make_client(handler) as client:
        with pytest.raises(GitHubAPIError, match="rate limit reached"):
            client.search_repositories("RAG")


def test_timeout_has_clear_message():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with make_client(handler) as client:
        with pytest.raises(GitHubAPIError, match="timed out"):
            client.search_repositories("RAG")


def test_readme_404_returns_missing_not_fake_text():
    def handler(request):
        return httpx.Response(404, json={"message": "Not Found"})

    with make_client(handler) as client:
        readme = client.get_repository_readme("owner/repo")
    assert readme.text is None
    assert readme.length is None


def test_empty_releases_are_explicit():
    with make_client(lambda request: httpx.Response(200, json=[])) as client:
        releases = client.get_repository_releases("owner/repo")
    assert releases.has_release is False
    assert releases.releases_count == 0


def test_details_map_missing_license_and_archived():
    payload = {
        "name": "repo",
        "full_name": "owner/repo",
        "html_url": "https://github.com/owner/repo",
        "owner": {
            "login": "owner",
            "type": "Organization",
            "html_url": "https://github.com/owner",
        },
        "license": None,
        "archived": True,
        "fork": False,
    }
    with make_client(lambda request: httpx.Response(200, json=payload)) as client:
        repo = client.get_repository_details("owner/repo")
    assert repo.license is None
    assert repo.archived is True
    assert repo.owner_type == "Organization"
