import re
import requests
from typing import Optional
from config import GITHUB_TOKEN, DEFAULT_GITHUB_REPO

_GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    return {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}


def detect_github_refs(text: str) -> list[str]:
    pattern = r'(?:(\w[\w-]*)/(\w[\w-]*))?#(\d+)'
    matches = re.findall(pattern, text)
    refs = []
    for owner, repo, num in matches:
        if owner and repo:
            refs.append(f"{owner}/{repo}#{num}")
        else:
            refs.append(f"{DEFAULT_GITHUB_REPO}#{num}")
    return refs


def fetch_github_issue(repo: str, issue_number: int) -> Optional[dict]:
    if not GITHUB_TOKEN:
        print("[GitHub] GITHUB_TOKEN not set")
        return None

    url = f"{_GITHUB_API}/repos/{repo}/issues/{issue_number}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "title": data["title"],
                "state": data["state"],
                "url": data["html_url"],
                "body": data.get("body", "")[:500],
                "labels": [l["name"] for l in data.get("labels", [])],
                "number": data["number"],
                "repo": repo,
            }
        print(f"[GitHub] {repo}#{issue_number}: HTTP {resp.status_code}")
    except requests.RequestException as e:
        print(f"[GitHub] Error fetching {repo}#{issue_number}: {e}")
    return None


def fetch_latest_issues(repo: str, count: int = 5) -> list[dict]:
    if not GITHUB_TOKEN:
        print("[GitHub] GITHUB_TOKEN not set")
        return []

    url = f"{_GITHUB_API}/repos/{repo}/issues"
    params = {"state": "open", "per_page": count, "sort": "updated", "direction": "desc"}

    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        if resp.status_code == 200:
            items = resp.json()
            return [
                {
                    "title": item["title"],
                    "state": item["state"],
                    "url": item["html_url"],
                    "body": item.get("body", "")[:500],
                    "number": item["number"],
                    "repo": repo,
                    "is_pr": "pull_request" in item,
                }
                for item in items
                if "pull_request" not in item
            ]
        print(f"[GitHub] Latest issues for {repo}: HTTP {resp.status_code}")
    except requests.RequestException as e:
        print(f"[GitHub] Error fetching latest issues: {e}")
    return []


def fetch_latest_prs(repo: str, count: int = 5) -> list[dict]:
    if not GITHUB_TOKEN:
        print("[GitHub] GITHUB_TOKEN not set")
        return []

    url = f"{_GITHUB_API}/repos/{repo}/pulls"
    params = {"state": "open", "per_page": count, "sort": "updated", "direction": "desc"}

    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        if resp.status_code == 200:
            prs = resp.json()
            return [
                {
                    "title": pr["title"],
                    "state": pr["state"],
                    "url": pr["html_url"],
                    "body": pr.get("body", "")[:500],
                    "number": pr["number"],
                    "repo": repo,
                    "user": pr["user"]["login"],
                }
                for pr in prs
            ]
        print(f"[GitHub] Latest PRs for {repo}: HTTP {resp.status_code}")
    except requests.RequestException as e:
        print(f"[GitHub] Error fetching latest PRs: {e}")
    return []
