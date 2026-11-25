"""3.20 (491) The public roadmap by votes: open feature requests sorted by 👍 → docs/ROADMAP_VOTES.md.

    GITHUB_TOKEN=… python packaging/roadmap_votes.py owner/repo

Runs in the weekly workflow (.github/workflows/roadmap.yml) or by hand."""
from __future__ import annotations

import json
import os
import sys
import urllib.request


def fetch(repo: str, token: str = "") -> list[dict]:
    out, page = [], 1
    while page <= 10:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}/issues?state=open&labels=enhancement&per_page=100&page={page}",
                                     headers={"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 – a fixed GitHub API URL
            items = json.loads(r.read())
        if not items:
            break
        out += [i for i in items if "pull_request" not in i]
        page += 1
    return out


def render(issues: list[dict]) -> str:
    rows = sorted(issues, key=lambda i: -int((i.get("reactions") or {}).get("+1", 0)))
    lines = ["# Roadmapa podle hlasů", "", "Hlasuje se 👍 u issue s nápadem. Aktualizuje se jednou týdně.", "", "| 👍 | Nápad |", "|---:|---|"]
    lines += [f"| {(i.get('reactions') or {}).get('+1', 0)} | [{i['title']}]({i['html_url']}) |" for i in rows[:50]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GITHUB_REPOSITORY", "")
    text = render(fetch(repo, os.environ.get("GITHUB_TOKEN", "")))
    with open(os.path.join(os.path.dirname(__file__), "..", "docs", "ROADMAP_VOTES.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
