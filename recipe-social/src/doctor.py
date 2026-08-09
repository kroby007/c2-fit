"""Preflight checks for the TikTok pipeline.

Without this, the only way to find out whether the setup is correct is to attempt
a live post and interpret whatever TikTok returns. Every check here is read-only —
nothing is posted, nothing is written — and each failure names its own fix rather
than surfacing a traceback.

The one thing that genuinely cannot be checked from here is URL-prefix ownership
verification, which is a click in the TikTok developer portal. The report says so
rather than implying full coverage.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import requests

from . import config
from .render.slides import FONT_FILES

TIMEOUT = 20
API = "https://open.tiktokapis.com/v2"

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"

_SYMBOL = {PASS: "✓", FAIL: "✗", WARN: "!", SKIP: "-"}


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""
    # On FAIL/WARN this is the fix, rendered with an arrow. On PASS it is a plain
    # explanatory note — an arrow there would read as "something to do".
    fix: str = ""


class Report:
    def __init__(self) -> None:
        self.sections: list[tuple[str, list[Check]]] = []

    def add(self, title: str, checks: list[Check]) -> None:
        self.sections.append((title, checks))

    @property
    def failures(self) -> list[Check]:
        return [c for section in self.sections for c in section[1] if c.status == FAIL]

    @property
    def warnings(self) -> list[Check]:
        return [c for section in self.sections for c in section[1] if c.status == WARN]

    def render(self) -> str:
        width = max(
            (len(c.name) for _, checks in self.sections for c in checks), default=20
        )
        lines: list[str] = []
        for title, checks in self.sections:
            lines.append(f"\n{title}")
            for check in checks:
                lines.append(
                    f"  {_SYMBOL[check.status]} {check.name.ljust(width)}  {check.detail}"
                )
                if check.fix:
                    marker = "->" if check.status in (FAIL, WARN) else "  "
                    for fix_line in check.fix.split("\n"):
                        lines.append(f"      {marker} {fix_line}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# sections
# --------------------------------------------------------------------------- #

def _local() -> list[Check]:
    checks: list[Check] = []

    try:
        checks.append(Check("Chromium", PASS, config.chrome_binary()))
    except RuntimeError as exc:
        checks.append(
            Check("Chromium", FAIL, str(exc),
                  "Install Chrome or Chromium, or set CHROME_BINARY to its path.")
        )

    missing = [name for name in FONT_FILES.values() if not (config.FONTS_DIR / name).is_file()]
    if missing:
        checks.append(
            Check("Slide fonts", FAIL, f"missing: {', '.join(missing)}",
                  "These are committed to the repo — restore them with "
                  "`git checkout -- recipe-social/assets/fonts`.")
        )
    else:
        checks.append(Check("Slide fonts", PASS, f"{len(FONT_FILES)} files present"))

    account = config.brand()["account"]
    handle = account["handle"]
    if handle.strip("@") in ("macroplate", "", "yourhandle"):
        checks.append(
            Check("Brand config", FAIL, f"still the placeholder ({handle})",
                  "Set account.name and account.handle in config/brand.yaml.")
        )
    else:
        checks.append(Check("Brand config", PASS, f"{account['name']} ({handle})"))

    return checks


def _credentials() -> list[Check]:
    """Presence only. Whether they actually work is proven in the TikTok section."""
    required = [
        ("ANTHROPIC_API_KEY", "Recipe generation. Get one at https://console.anthropic.com"),
        ("GEMINI_API_KEY", "Food photography. Free key at https://aistudio.google.com/apikey"),
        ("TIKTOK_CLIENT_KEY", "From your app at https://developers.tiktok.com"),
        ("TIKTOK_CLIENT_SECRET", "From the same app page."),
        ("TIKTOK_REFRESH_TOKEN", "Run `python scripts/tiktok_auth.py` to mint one."),
    ]
    checks = [
        Check(name, PASS, "set") if os.environ.get(name)
        else Check(name, FAIL, "not set", fix)
        for name, fix in required
    ]

    base = os.environ.get("PAGES_BASE_URL")
    if not base:
        checks.append(
            Check("PAGES_BASE_URL", FAIL, "not set",
                  "Set it to your GitHub Pages URL, e.g. https://<user>.github.io/c2-fit")
        )
    elif base.endswith("/"):
        checks.append(
            Check("PAGES_BASE_URL", WARN, base,
                  "Trailing slash is stripped automatically, but remove it to keep this "
                  "value byte-identical to the prefix you verify with TikTok.")
        )
    elif not base.startswith("https://"):
        checks.append(
            Check("PAGES_BASE_URL", FAIL, base,
                  "TikTok only fetches over HTTPS. This must be an https:// URL.")
        )
    else:
        checks.append(Check("PAGES_BASE_URL", PASS, base))

    if not os.environ.get("GH_PAT"):
        checks.append(
            Check("GH_PAT", WARN, "not set",
                  "Optional, but without it the rotated TikTok refresh token cannot be "
                  "written back to Actions secrets and must be copied over by hand.")
        )
    else:
        checks.append(Check("GH_PAT", PASS, "set"))

    return checks


def _pages_site() -> list[Check]:
    base = (os.environ.get("PAGES_BASE_URL") or "").rstrip("/")
    if not base:
        return [Check("Site reachable", SKIP, "PAGES_BASE_URL not set")]

    # /media/README.md is committed, so a 200 there proves Pages serves the exact
    # prefix the publisher will hand TikTok — not merely that the site exists.
    paths = [
        ("/", "App website URL for TikTok registration"),
        ("/privacy.html", "Privacy policy URL for TikTok registration"),
        ("/terms.html", "Terms of service URL for TikTok registration"),
        ("/oauth.html", "OAuth redirect target used by scripts/tiktok_auth.py"),
        ("/media/README.md", "Proves the media prefix is served"),
    ]

    checks: list[Check] = []
    for path, purpose in paths:
        url = f"{base}{path}"
        try:
            status = requests.get(url, timeout=TIMEOUT).status_code
        except requests.RequestException as exc:
            # A connectivity failure hits every URL identically, so report it once
            # rather than repeating the same line five times — and do not blame
            # Pages configuration for what is a network problem.
            checks.append(
                Check("Site reachable", FAIL, f"cannot reach {base} ({type(exc).__name__})",
                      "This is a network problem, not a Pages problem. Check your "
                      "connection, proxy, or firewall.")
            )
            return checks

        if status == 200:
            checks.append(Check(path, PASS, f"200 — {purpose}"))
        elif status == 404:
            checks.append(
                Check(path, FAIL, "404",
                      "Pages has not published this file. Confirm Settings -> Pages is "
                      "set to branch main, folder /docs, that the build finished, and "
                      "that this commit is pushed.")
            )
        else:
            checks.append(Check(path, FAIL, str(status), "Unexpected status for a static file."))

    return checks


def _tiktok() -> list[Check]:
    needed = ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")
    if not all(os.environ.get(n) for n in needed):
        return [Check("API access", SKIP, "TikTok credentials not set")]

    from .state import tokens

    try:
        access_token = tokens.tiktok_access_token()
    except requests.RequestException as exc:
        # Connectivity, not configuration — say so, or the user starts rotating
        # perfectly good credentials chasing a network problem.
        return [
            Check("Token refresh", FAIL, f"could not reach TikTok ({type(exc).__name__})",
                  "This is a network problem, not a credentials problem. Check your "
                  "connection, proxy, or firewall — open.tiktokapis.com must be reachable.")
        ]
    except RuntimeError as exc:
        return [
            Check("Token refresh", FAIL, str(exc)[:160],
                  "The client key, secret, and refresh token must all come from the same "
                  "app and the same authorization. Re-run `python scripts/tiktok_auth.py`.")
        ]

    checks = [Check("Token refresh", PASS, "exchanged a refresh token for an access token")]

    try:
        response = requests.post(
            f"{API}/post/publish/creator_info/query/",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        checks.append(Check("Creator info", FAIL, f"request failed: {exc}"))
        return checks

    body = response.json() if response.content else {}
    error_code = (body.get("error") or {}).get("code", "")

    if response.status_code != 200 or error_code not in ("ok", ""):
        fix = (
            "This endpoint needs the Content Posting API product added to your app "
            "with the video.upload scope approved."
        )
        if "scope" in str(body).lower():
            fix = (
                "The token is missing the required scope. Add video.upload to the app, "
                "wait for approval, then re-run scripts/tiktok_auth.py to reauthorize."
            )
        checks.append(Check("Creator info", FAIL, f"{response.status_code} {body}"[:180], fix))
        return checks

    data = body.get("data", {})
    username = (data.get("creator_username") or "").strip()
    nickname = (data.get("creator_nickname") or "").strip()
    checks.append(
        Check("Creator info", PASS, "Content Posting API scope is live")
    )

    # The failure this catches: authorizing a different TikTok account than the
    # one the slides are branded for. It otherwise only surfaces when a post
    # lands somewhere unexpected.
    configured = config.brand()["account"]["handle"].lstrip("@").lower()
    display = f"@{username}" + (f" ({nickname})" if nickname else "")
    if username and username.lower() != configured:
        checks.append(
            Check("Connected account", FAIL, display,
                  f"config/brand.yaml is branded for @{configured}, but the token "
                  f"authorizes @{username}. Posts would go to the wrong account. "
                  "Re-authorize while logged into the right one, or fix brand.yaml.")
        )
    else:
        checks.append(Check("Connected account", PASS, display or "(username not returned)"))

    options = data.get("privacy_level_options") or []
    if options:
        checks.append(Check("Privacy options", PASS, ", ".join(options)))
    if data.get("comment_disabled"):
        checks.append(
            Check("Comments", WARN, "disabled on this account",
                  "Comments drive reach. Consider enabling them in TikTok settings.")
        )

    return checks


def _post_mode() -> list[Check]:
    mode = config.setting("TIKTOK_POST_MODE", "MEDIA_UPLOAD").upper()
    if mode == "MEDIA_UPLOAD":
        return [
            Check("Post mode", PASS, "MEDIA_UPLOAD — carousels land in your TikTok drafts",
                  "Open the app, pick a trending sound, and post. This is the only way "
                  "to choose the song; no API accepts a sound ID.")
        ]
    if mode == "DIRECT_POST":
        return [
            Check("Post mode", WARN, "DIRECT_POST — posts publish automatically",
                  "TikTok picks the sound via auto_add_music, not you. Until the Content "
                  "Posting API audit passes, every direct post is forced to SELF_ONLY "
                  "and only you can see it.")
        ]
    return [Check("Post mode", FAIL, mode, "Must be MEDIA_UPLOAD or DIRECT_POST.")]


# --------------------------------------------------------------------------- #

def run() -> int:
    """Run every check and print the report. Returns a process exit code."""
    account = config.brand()["account"]
    print(f"{account['name']} — TikTok preflight")

    report = Report()
    report.add("Local environment", _local())
    report.add("Credentials", _credentials())
    report.add("Public site", _pages_site())
    report.add("TikTok", _tiktok() + _post_mode())
    print(report.render())

    failures, warnings = report.failures, report.warnings
    print()

    def plural(n: int, word: str) -> str:
        return f"{n} {word}" if n == 1 else f"{n} {word}s"

    warning_note = f", {plural(len(warnings), 'warning')}" if warnings else ""

    if failures:
        print(f"{plural(len(failures), 'problem')} to fix{warning_note}.")
        print("Each is marked -> above with what to do.")
        return 1

    print(f"All checks passed{warning_note}.")
    print(
        "\nOne thing this cannot check: URL-prefix ownership verification, which is a\n"
        "click in the TikTok portal under Manage URL properties. If it is not verified,\n"
        "publishing fails with url_ownership_unverified.\n"
        "\nReady for a live run:\n"
        "  python -m src.cli run"
    )
    return 0
