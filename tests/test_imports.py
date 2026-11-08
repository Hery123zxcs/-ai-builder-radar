import importlib

import pytest

from config import ConfigurationError, Settings


@pytest.mark.parametrize(
    "module_name",
    [
        "config",
        "schemas",
        "github_client",
        "tools",
        "agent",
        "scoring",
        "llm_analyzer",
        "database",
        "reports",
        "utils",
        "app",
    ],
)
def test_core_module_imports(module_name):
    assert importlib.import_module(module_name)


def test_missing_deepseek_key_is_explicit():
    settings = Settings(deepseek_api_key=None)
    assert settings.deepseek_configured is False
    with pytest.raises(ConfigurationError, match="DEEPSEEK_API_KEY is missing"):
        settings.require_deepseek_key()


def test_secret_repr_does_not_expose_value():
    secret = "do-not-print-this-key"
    settings = Settings(deepseek_api_key=secret, github_token=secret)
    assert secret not in repr(settings)


def test_missing_model_is_explicit():
    settings = Settings(deepseek_api_key="placeholder", deepseek_model=None)
    with pytest.raises(ConfigurationError, match="DEEPSEEK_MODEL is missing"):
        settings.require_deepseek_model()


def test_env_is_gitignored():
    gitignore = open(".gitignore", encoding="utf-8").read().splitlines()
    assert ".env" in gitignore


def test_ui_and_debug_sources_do_not_contain_test_secret():
    secret = "do-not-print-this-key"
    combined = open("app.py", encoding="utf-8").read() + open(
        "agent.py", encoding="utf-8"
    ).read()
    assert secret not in combined
