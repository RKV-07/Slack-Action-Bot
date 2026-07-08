import re
from typing import Optional
from config import GITHUB_TOKEN, DEFAULT_GITHUB_REPO


def detect_github_refs(text: str) -> list[str]:
    pattern = r"(?:([\w-]+)/([\w-]+))?#(\d+)"
    matches = re.findall(pattern, text)
    refs = []
    for owner, repo, num in matches:
        if owner and repo:
            refs.append(f"{owner}/{repo}#{num}")
        else:
            refs.append(f"{DEFAULT_GITHUB_REPO}#{num}")
    return refs


def fetch_github_issue(repo: str, issue_number: int) -> Optional[dict]:
    import requests

    if not GITHUB_TOKEN:
        print("GitHub API error: GITHUB_TOKEN is not set")
        return None

    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "title": data["title"],
                "state": data["state"],
                "url": data["html_url"],
                "body": data.get("body", "")[:500],
                "labels": [l["name"] for l in data.get("labels", [])],
                "number": data["number"],
                "repo": repo,
            }
    except Exception as e:
        print(f"GitHub API error: {e}")
    return None


def fetch_latest_issues(repo: str, count: int = 5) -> list[dict]:
    import requests

    if not GITHUB_TOKEN:
        print("GitHub API error: GITHUB_TOKEN is not set")
        return []

    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    params = {"state": "open", "per_page": count, "sort": "updated", "direction": "desc"}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            issues = response.json()
            return [
                {
                    "title": issue["title"],
                    "state": issue["state"],
                    "url": issue["html_url"],
                    "body": issue.get("body", "")[:500],
                    "labels": [l["name"] for l in issue.get("labels", [])],
                    "number": issue["number"],
                    "repo": repo,
                    "is_pr": "pull_request" in issue,
                }
                for issue in issues
            ]
    except Exception as e:
        print(f"GitHub API error: {e}")
    return []


def fetch_latest_prs(repo: str, count: int = 5) -> list[dict]:
    import requests

    if not GITHUB_TOKEN:
        print("GitHub API error: GITHUB_TOKEN is not set")
        return []

    url = f"https://api.github.com/repos/{repo}/pulls"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    params = {"state": "open", "per_page": count, "sort": "updated", "direction": "desc"}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            prs = response.json()
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
    except Exception as e:
        print(f"GitHub API error: {e}")
    return []
