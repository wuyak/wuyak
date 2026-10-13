#!/usr/bin/env python3
"""Refresh the profile's public, merged PR list using the GitHub API."""

import html
import base64
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
ICONS = json.loads((ROOT / "scripts/pr_icons.json").read_text())
# Badge sources verified in the projects' own READMEs.
PROJECT_BADGES = {
    "agentscope-ai/agentscope": "https://trendshift.io/api/badge/repositories/20310",
    "agentscope-ai/QwenPaw": "https://trendshift.io/api/badge/trendshift/repositories/25882/daily",
}


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


def link_text(value):
    # Escape HTML and Markdown syntax so external PR titles stay literal table text.
    value = html.escape(" ".join(value.split()), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|~])", lambda match: f"&#{ord(match[0])};", value)


def fetch_projects(prs, token):
    projects = {}
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "wuyak-profile-updater"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for repo in dict.fromkeys(pr["repo"] for pr in prs):
        with urlopen(Request(f"https://api.github.com/repos/{repo}", headers=headers), timeout=30) as response:
            projects[repo] = {"stars": json.load(response)["stargazers_count"], "badge": ""}
        if repo in PROJECT_BADGES:
            try:
                request = Request(PROJECT_BADGES[repo], headers={"User-Agent": "wuyak-profile-updater"})
                with urlopen(request, timeout=20) as response:
                    badge = response.read()
                if b"<svg" in badge:
                    projects[repo]["badge"] = "data:image/svg+xml;base64," + base64.b64encode(badge).decode()
            except Exception as error:
                print(f"Optional project badge unavailable for {repo}: {type(error).__name__}")
    return projects


def kind(title):
    for prefixes, name in ((('fix', 'bug'), 'fix'), (('feat', 'add', 'implement'), 'feat'),
                           (('doc',), 'docs'), (('test',), 'test'),
                           (('ci', 'build', 'chore', 'refactor', 'perf'), 'tool')):
        if title.lower().lstrip().startswith(prefixes):
            return name
    return 'other'


def stars_label(stars):
    for size, suffix in ((1_000_000, 'm'), (1000, 'k')):
        if stars >= size:
            return f"{stars / size:.1f}".rstrip('0').rstrip('.') + suffix
    return str(stars)


def render_svg(prs, projects, dark=False):
    bg, text, muted, line, green = ('#0d1117', '#e6edf3', '#9dada8', '#334740', '#58c9aa') if dark else (
        '#ffffff', '#26322f', '#52625d', '#dfe7e4', '#16866e')
    height = 100 + max(1, len(prs)) * 62
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img">',
             '<title>Open-source contributions</title>',
             '<!-- Pixelarticons: Gerrit Halfmann, MIT. See PIXELARTICONS-LICENSE.txt. -->',
             f'<rect width="1000" height="{height}" fill="{bg}"/>',
             '<style>text{font-family:Inter,"Segoe UI",Arial,sans-serif}.mono{font-family:SFMono-Regular,Consolas,Liberation Mono,Menlo,monospace}</style>',
             f'<text x="36" y="36" fill="{text}" font-size="14" font-weight="700">{len(prs)} MERGED PRS / {len(projects)} PROJECTS</text>',
             f'<text x="964" y="36" text-anchor="end" class="mono" fill="{green}" font-size="12" font-weight="700">AUTO-SYNC</text>',
             f'<path d="M36 56H964" stroke="{line}"/>']
    if len(prs) > 1:
        parts.append(f'<path d="M66 101V{101 + (len(prs)-1)*62}" stroke="{muted}" stroke-opacity="0.4" stroke-width="2"/>')
    for index, pr in enumerate(prs):
        y = 101 + index * 62
        category = kind(pr['title'])
        label = category.upper() if category != 'other' else 'PR'
        date = datetime.fromisoformat(pr['merged_at'].replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
        title = ' '.join(pr['title'].split())
        title = title if len(title) <= 76 else title[:75].rstrip() + '…'
        parts += [f'<rect x="48" y="{y-18}" width="36" height="36" rx="3" fill="{bg}" stroke="{muted}" stroke-opacity="0.4"/>',
                  f'<g transform="translate(54 {y-12})" fill="{text}">']
        parts.extend(f'<path d="{path}"/>' for path in ICONS['SVG_ICONS'][category])
        parts += ['</g>',
                  f'<text x="104" y="{y-4}" fill="{text}" font-size="15" font-weight="700">{html.escape(pr["repo"])} <tspan fill="{muted}" font-weight="400">/ #{pr["number"]}</tspan></text>',
                  f'<text x="104" y="{y+18}" fill="{muted}" font-size="13">{html.escape(title)}</text>',
                  f'<text x="762" y="{y+6}" text-anchor="end" class="mono" fill="{text}" font-size="16" font-weight="700">{stars_label(projects[pr["repo"]]["stars"])}</text>',
                  f'<path d="{ICONS["STAR_ICON"]}" transform="translate(770 {y-12})" fill="{text}"/>',
                  f'<text x="964" y="{y+5}" text-anchor="end" class="mono" fill="{green}" font-size="12" font-weight="700">[ {label} ] {date}</text>']
        if projects[pr['repo']]['badge']:
            parts.append(f'<image x="564" y="{y-16}" width="144" height="32" href="{projects[pr["repo"]]["badge"]}"/>')
    if not prs:
        parts.append(f'<text x="36" y="104" fill="{muted}" font-size="13">NO MERGED EXTERNAL PRS YET</text>')
    parts += ['</svg>']
    return '\n'.join(parts) + '\n'


def render(prs, username):
    url = "https://github.com/pulls?" + urlencode({"q": search_query(username)})
    lines = ['<picture>',
             '  <source media="(prefers-color-scheme: dark)" srcset="./assets/contributions-dark.svg">',
             '  <img src="./assets/contributions-light.svg" width="100%" alt="已合并的开源 PR：项目、标题、项目 Star 数、类型和合并日期">',
             '</picture>', '', f'[查看全部已合并的 Pull Requests →]({url})', '',
             '<details>', '<summary>逐条打开 PR</summary>', '']
    lines += [f'- [{link_text(pr["repo"])} #{pr["number"]} · {link_text(pr["title"])}]({pr["url"]})' for pr in prs]
    lines += ['', '</details>']
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
    projects = fetch_projects(prs, os.environ.get("GITHUB_TOKEN", ""))
    updated = update_readme(current, render(prs, username))
    assets = ROOT / 'assets'
    assets.mkdir(exist_ok=True)
    for theme in ('light', 'dark'):
        (assets / f'contributions-{theme}.svg').write_text(render_svg(prs, projects, dark=theme == 'dark'), encoding='utf-8')
    if updated != current:
        path.write_text(updated, encoding="utf-8")
    print(f"Profile updated: {len(prs)} merged PRs across {len({pr['repo'] for pr in prs})} projects")


if __name__ == "__main__":
    main()
