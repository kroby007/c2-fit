"""Suite-wide safety net for the one directory tests must never touch.

`docs/` is not a build output — it is the live site. `docs/today.html` is the
page opened on a phone each morning, and `docs/media/` holds the images TikTok
fetches by URL. Both are written by ordinary pipeline code, so any test that
runs a stage without redirecting `config.DOCS_DIR` and `config.MEDIA_DIR`
silently overwrites a real published post with fixture data.

That is exactly what happened once: a test run replaced a real post's phone page
with 'Chili Crisp Chicken Bowls' pointing at example.github.io, it was committed
along with unrelated work, and the breakage was only visible on the site itself.
Nothing in the suite failed.

So the check lives here rather than in any one test's fixtures: whatever a test
forgets to patch, the leak is caught at session end instead of in a git diff
nobody reads closely.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src import config  # noqa: E402


def _fingerprint() -> dict[str, str]:
    """Digest every file under the real docs/, keyed by relative path."""
    docs = pathlib.Path(config.__file__).resolve().parent.parent.parent / "docs"
    if not docs.is_dir():
        return {}
    return {
        str(p.relative_to(docs)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(docs.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="session", autouse=True)
def docs_directory_is_not_a_test_output():
    before = _fingerprint()
    yield
    after = _fingerprint()

    changed = sorted(
        name for name in before.keys() | after.keys()
        if before.get(name) != after.get(name)
    )
    if changed:
        raise AssertionError(
            "The test suite wrote to the live docs/ directory:\n"
            + "\n".join(f"  {name}" for name in changed)
            + "\n\nThese are published files, not build artifacts. Restore them "
              "(git checkout -- docs/) and monkeypatch config.DOCS_DIR and "
              "config.MEDIA_DIR into tmp_path in the test that ran a pipeline stage."
        )
