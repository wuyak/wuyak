#!/usr/bin/env python3
"""Refresh the profile's public, merged PR list using the GitHub API."""

import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- OPEN_SOURCE_PRS:START -->"
END = "<!-- OPEN_SOURCE_PRS:END -->"


def search_query(username):
    return f"is:pr is:merged is:public author:{username} -user:{username}"


def fetch_prs(username, token):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "wuyak-profile-updater",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    items = []
    for page in range(1, 11):
        params = urlencode({
            "q": search_query(username), "sort": "updated", "order": "desc",
            "per_page": 100, "page": page,
        })
        request = Request(f"https://api.github.com/search/issues?{params}", headers=headers)
        with urlopen(request, timeout=45) as response:
            data = json.load(response)
        if data.get("incomplete_results") or data["total_count"] > 1000:
            raise RuntimeError("GitHub returned an incomplete search; preserving the existing README")
        items.extend(data["items"])
        if len(items) >= data["total_count"]:
            break
        if not data["items"]:
            raise RuntimeError("GitHub pagination ended early; preserving the existing README")
    unique = {item["id"]: item for item in items}
    if len(unique) != data["total_count"]:
        raise RuntimeError("Search changed during pagination; retry instead of publishing a partial list")
    result = []
    for item in unique.values():
        repo = item["repository_url"].removeprefix("https://api.github.com/repos/")
        merged = item.get("pull_request", {}).get("merged_at")
        if not merged or repo.split("/")[0].lower() == username.lower():
            raise RuntimeError("Unexpected PR search result; preserving the existing README")
        result.append({"repo": repo, "number": item["number"], "title": item["title"],
                       "url": item["html_url"], "merged_at": merged})
    return sorted(result, key=lambda pr: (pr["merged_at"], pr["url"]), reverse=True)


def table_text(value):
    # Escape HTML and Markdown syntax so external PR titles stay literal table text.
    value = html.escape(" ".join(value.split()), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|~])", lambda match: f"&#{ord(match[0])};", value)


def render(prs, username):
    projects = len({pr["repo"] for pr in prs})
    lines = [f"**{len(prs)} 个已合并 PR · {projects} 个项目**", ""]
    if prs:
        lines += ["| 项目 | Pull Request | 合并日期（北京时间） |", "| --- | --- | --- |"]
        for pr in prs:
            date = datetime.fromisoformat(pr["merged_at"].replace("Z", "+00:00"))
            date = date.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
            repo_url = "https://github.com/" + quote(pr["repo"], safe="/")
            lines.append(f"| [{table_text(pr['repo'])}]({repo_url}) | "
                         f"[#{pr['number']} · {table_text(pr['title'])}]({pr['url']}) | {date} |")
    else:
        lines.append("暂时没有符合条件的已合并 PR。")
    url = "https://github.com/pulls?" + urlencode({"q": search_query(username)})
    lines += ["", f"[查看全部开源 PR →]({url})"]
    return "\n".join(lines)


def update_readme(current, generated):
    if current.count(START) != 1 or current.count(END) != 1:
        raise ValueError("README must contain exactly one pair of PR section markers")
    before, rest = current.split(START, 1)
    if END not in rest:
        raise ValueError("README section markers are reversed")
    _, after = rest.split(END, 1)
    return before + START + "\n" + generated + "\n" + END + after


def main():
    username = os.environ.get("PROFILE_USER", "wuyak").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", username):
        raise ValueError("Invalid GitHub username")
    path = ROOT / "README.md"
    current = path.read_text(encoding="utf-8")
    prs = fetch_prs(username, os.environ.get("GITHUB_TOKEN", ""))
    updated = update_readme(current, render(prs, username))
    if updated != current:
        path.write_text(updated, encoding="utf-8")
    print(f"Profile updated: {len(prs)} merged PRs across {len({pr['repo'] for pr in prs})} projects")


if __name__ == "__main__":
    main()
