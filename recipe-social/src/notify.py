"""Surfacing held posts.

A post the gate holds is only useful if someone finds out about it, so held runs
open a GitHub issue. Outside Actions (or without a token) this degrades to
printing — the post is still on disk in out/held/ either way.
"""
from __future__ import annotations

import os

import requests

TIMEOUT = 30


def report_held(title: str, reasons: list[str], post_dir: str) -> None:
    body = "\n".join(
        [
            f"Held before publishing: **{title}**",
            "",
            "**Why:**",
            *(f"- {r}" for r in reasons),
            "",
            f"Slides and caption are in `{post_dir}`.",
            "",
            "Fix the recipe and re-run the publish stage, or delete the folder to skip it.",
        ]
    )

    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not (token and repo):
        print(f"\n--- POST HELD ---\n{body}\n")
        return

    response = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"title": f"Recipe post held: {title}", "body": body, "labels": ["held-post"]},
        timeout=TIMEOUT,
    )
    if response.status_code >= 300:
        print(f"Could not open an issue ({response.status_code}): {response.text}")
        print(f"\n--- POST HELD ---\n{body}\n")
    else:
        print(f"Opened issue: {response.json().get('html_url')}")
