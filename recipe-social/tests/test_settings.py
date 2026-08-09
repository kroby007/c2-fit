"""Environment-driven model selection.

Both behaviours here have the same failure signature — a run that dies at an
API call minutes in — and neither is visible without exercising the exact
env-var shape GitHub Actions produces.
"""
from __future__ import annotations

import importlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "the-default"),
        # How GitHub Actions renders an unset repository variable. os.environ.get
        # with a default returns "" here, which is how a blank model name reaches
        # the API and 404s.
        ("", "the-default"),
        ("   ", "the-default"),
        ("claude-haiku-4-5", "claude-haiku-4-5"),
        ("  claude-opus-5  ", "claude-opus-5"),
    ],
)
def test_setting_treats_blank_as_absent(
    value: str | None, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    if value is None:
        monkeypatch.delenv("A_TEST_SETTING", raising=False)
    else:
        monkeypatch.setenv("A_TEST_SETTING", value)
    assert config.setting("A_TEST_SETTING", "the-default") == expected


def _verify_with_model(model: str, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("IMAGE_CHECK_MODEL", model)
    from src.images import verify

    return importlib.reload(verify)


def test_image_check_defaults_to_haiku(monkeypatch: pytest.MonkeyPatch) -> None:
    """It must not inherit RECIPE_MODEL — that doubled the cost of a post."""
    monkeypatch.delenv("IMAGE_CHECK_MODEL", raising=False)
    monkeypatch.setenv("RECIPE_MODEL", "claude-opus-5")
    from src.images import verify

    reloaded = importlib.reload(verify)
    assert reloaded.MODEL == "claude-haiku-4-5"


@pytest.mark.parametrize("model", ["claude-haiku-4-5", "claude-sonnet-4-5"])
def test_effort_is_omitted_where_it_is_rejected(
    model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Haiku 4.5 returns a 400 for output_config.effort — it must not be sent."""
    verify = _verify_with_model(model, monkeypatch)
    assert "effort" not in verify.output_config()
    assert verify.output_config()["format"]["type"] == "json_schema"


@pytest.mark.parametrize("model", ["claude-opus-5", "claude-sonnet-5"])
def test_effort_is_sent_where_it_is_supported(
    model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    verify = _verify_with_model(model, monkeypatch)
    assert verify.output_config()["effort"] == "low"


def test_verify_module_is_left_at_its_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo the reloads above so later tests see the real default."""
    monkeypatch.delenv("IMAGE_CHECK_MODEL", raising=False)
    from src.images import verify

    assert importlib.reload(verify).MODEL == "claude-haiku-4-5"
