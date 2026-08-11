"""The hero-image check and the Gemini retry, both exercised end to end.

These exist because of two real production failures on consecutive days:

  2026-08-10  Gemini returned 503 "experiencing high demand" and the whole
              day's post was lost — one transient blip, no retry.
  2026-08-11  check_hero() raised NameError on a stale call site. Sixty-four
              tests passed, because every one of them tested the helper
              beside it and none of them ever called check_hero.

The lesson in the second is the important one: a function nothing calls in a
test is untested no matter how many tests surround it. Both tests below run
the real function body with only the network boundary replaced.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.images import gemini, verify  # noqa: E402
from src.recipes.schema import Recipe  # noqa: E402

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _recipe() -> Recipe:
    return Recipe.from_dict(json.loads((FIXTURES / "recipe_good.json").read_text()))


class _Block:
    def __init__(self, text: str) -> None:
        self.type, self.text = "text", text


class _Response:
    def __init__(self, verdict: dict, stop_reason: str = "end_turn") -> None:
        self.stop_reason = stop_reason
        self.content = [_Block(json.dumps(verdict))]


def _stub_anthropic(monkeypatch: pytest.MonkeyPatch, response: _Response) -> dict:
    """Replace only the network call; everything else in check_hero runs for real."""
    captured: dict = {}

    class _Messages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return response

    class _Client:
        def __init__(self, *a, **kw) -> None:
            self.messages = _Messages()

    monkeypatch.setattr(verify.anthropic, "Anthropic", _Client)
    return captured


_CLEAN = {"is_food": True, "matches_dish": True, "appetizing": True,
          "has_text": False, "problem": ""}


def test_check_hero_runs_and_passes_a_good_image(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: this call site went stale and raised NameError in production."""
    captured = _stub_anthropic(monkeypatch, _Response(_CLEAN))

    assert verify.check_hero(_recipe(), b"\x89PNG fake bytes") == []

    # The request has to be well-formed, not merely constructed without error.
    assert captured["model"] == verify.MODEL
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert "effort" not in captured["output_config"], "Haiku 4.5 rejects effort"
    image = captured["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["data"]


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ({**_CLEAN, "is_food": False, "problem": "a pile of raw flour"},
         "does not show food"),
        ({**_CLEAN, "matches_dish": False}, "does not match the dish"),
        ({**_CLEAN, "appetizing": False}, "not appetizing"),
        ({**_CLEAN, "has_text": True}, "text baked into it"),
    ],
)
def test_check_hero_holds_a_bad_image(
    verdict: dict, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_anthropic(monkeypatch, _Response(verdict))
    reasons = verify.check_hero(_recipe(), b"fake")
    assert any(expected in r for r in reasons), reasons


def test_check_hero_handles_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal must hold the post, not crash on empty content."""
    _stub_anthropic(monkeypatch, _Response(_CLEAN, stop_reason="refusal"))
    reasons = verify.check_hero(_recipe(), b"fake")
    assert len(reasons) == 1 and "by hand" in reasons[0]


# --------------------------------------------------------------------------- #
# Gemini retry
# --------------------------------------------------------------------------- #

def _api_error(code: int) -> Exception:
    from google.genai import errors

    class _Err(errors.APIError):
        def __init__(self) -> None:  # bypass the SDK's response-parsing ctor
            self.code = code
            self.message = f"stubbed {code}"

    return _Err()


class _Blob:
    data = b"image-bytes"


class _Part:
    inline_data = _Blob()


class _Content:
    parts = [_Part()]


class _Candidate:
    content = _Content()


class _GeminiOk:
    candidates = [_Candidate()]


def _provider(monkeypatch: pytest.MonkeyPatch) -> gemini.GeminiProvider:
    monkeypatch.setattr(gemini.time, "sleep", lambda _: None)  # no real waiting
    provider = gemini.GeminiProvider.__new__(gemini.GeminiProvider)  # skip API-key init
    return provider


def test_gemini_retries_a_transient_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact error that cost a day's post on 2026-08-10."""
    provider = _provider(monkeypatch)
    attempts = []

    def flaky(prompt, aspect_ratio):
        attempts.append(1)
        if len(attempts) < 3:
            raise _api_error(503)
        return _GeminiOk()

    monkeypatch.setattr(provider, "_generate_once", flaky)
    assert provider.generate("a bowl of chili", "3:4") == b"image-bytes"
    assert len(attempts) == 3


def test_gemini_does_not_retry_a_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 400 fails the same way every time; retrying only wastes three minutes."""
    provider = _provider(monkeypatch)
    attempts = []

    def always_400(prompt, aspect_ratio):
        attempts.append(1)
        raise _api_error(400)

    monkeypatch.setattr(provider, "_generate_once", always_400)
    with pytest.raises(Exception):
        provider.generate("a bowl of chili", "3:4")
    assert len(attempts) == 1, "a client error must not be retried"


def test_gemini_gives_up_after_the_last_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    attempts = []

    def always_503(prompt, aspect_ratio):
        attempts.append(1)
        raise _api_error(503)

    monkeypatch.setattr(provider, "_generate_once", always_503)
    with pytest.raises(Exception):
        provider.generate("a bowl of chili", "3:4")
    assert len(attempts) == len(gemini._RETRY_DELAYS) + 1
