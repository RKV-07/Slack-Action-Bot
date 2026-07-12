import re
import difflib
import threading
import requests
from typing import Optional
from cachetools import TTLCache, cached
from config import GITHUB_TOKEN

_GITHUB_API = "https://api.github.com"

# Rate limit state
_rate_limit_remaining = None
_rate_limit_reset = None


def _headers() -> dict:
    return {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}


def _check_rate_limit(resp: requests.Response):
    """Track GitHub rate limit state from response headers."""
    global _rate_limit_remaining, _rate_limit_reset
    remaining = resp.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        _rate_limit_remaining = int(remaining)
    reset = resp.headers.get("X-RateLimit-Reset")
    if reset is not None:
        _rate_limit_reset = int(reset)


def _strip_suffix(text: str, suffix: str) -> str:
    """Properly strip a suffix from text (not char set like rstrip)."""
    if text.endswith(suffix):
        return text[:-len(suffix)]
    return text


def detect_github_refs(text: str) -> list[str]:
    pattern = r'(?:(\w[\w-]*)/(\w[\w-]*))?#(\d+)'
    matches = re.findall(pattern, text)
    refs = []
    for owner, repo, num in matches:
        if owner and repo:
            refs.append(f"{owner}/{repo}#{num}")
        # Bare #123 not supported — no default repo
    return refs


def extract_repo_from_text(text: str) -> Optional[str]:
    """Extract owner/repo from text, handling GitHub URLs and plain text."""
    # Handle GitHub URLs: https://github.com/owner/repo
    url_match = re.search(r'github\.com/([\w.-]+)/([\w.-]+?)(?:[\s?#/]|$)', text)
    if url_match:
        owner = url_match.group(1)
        repo = _strip_suffix(url_match.group(2), '.git')
        if owner and repo:
            return f"{owner}/{repo}"

    # Handle plain text: owner/repo (must be word-bounded, no dots in segments)
    plain_match = re.search(r'\b([\w][\w-]*/[\w][\w-]*)\b', text)
    if plain_match:
        candidate = plain_match.group(1)
        # Reject if there's a dot immediately before the match (e.g. some.thing/repo)
        start = plain_match.start()
        if start > 0 and text[start - 1] == '.':
            pass  # skip — dot-prefixed means not a standalone owner
        else:
            parts = candidate.split('/')
            if len(parts) == 2 and parts[0] and parts[1]:
                if '.' not in parts[0] and '.' not in parts[1]:
                    return candidate

    return None


_repo_cache = TTLCache(maxsize=1, ttl=120)
_repo_cache_lock = threading.Lock()


@cached(_repo_cache, lock=_repo_cache_lock)
def fetch_all_repos() -> list[dict]:
    """Fetch all repos the token has access to (cached 2 min)."""
    if not GITHUB_TOKEN:
        print("[GitHub] GITHUB_TOKEN not set")
        return []

    repos = []
    page = 1
    while True:
        url = f"{_GITHUB_API}/user/repos"
        params = {"per_page": 100, "page": page, "sort": "updated"}
        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=10)
            _check_rate_limit(resp)
            if resp.status_code == 200:
                items = resp.json()
                if not items:
                    break
                for item in items:
                    repos.append({
                        "name": item["full_name"],
                        "private": item["private"],
                        "updated_at": item["updated_at"],
                    })
                page += 1
            else:
                print(f"[GitHub] Failed to fetch repos: HTTP {resp.status_code}")
                if resp.status_code == 403 and _rate_limit_remaining == 0:
                    print(f"[GitHub] Rate limited. Resets at {_rate_limit_reset}")
                break
        except requests.RequestException as e:
            print(f"[GitHub] Error fetching repos: {e}")
            break
    return repos


def fetch_github_issue(repo: str, issue_number: int) -> Optional[dict]:
    url = f"{_GITHUB_API}/repos/{repo}/issues/{issue_number}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=10)
        _check_rate_limit(resp)
        if resp.status_code == 200:
            data = resp.json()
            if not data or not isinstance(data, dict):
                print(f"[GitHub] Unexpected response for {repo}#{issue_number}: {str(data)[:200]}")
                return None
            return {
                "title": data.get("title", "Untitled"),
                "state": data.get("state", "unknown"),
                "url": data.get("html_url", ""),
                "body": (data.get("body") or "")[:500],
                "labels": [l["name"] for l in data.get("labels", []) if isinstance(l, dict)],
                "number": data.get("number", issue_number),
                "repo": repo,
            }
        print(f"[GitHub] {repo}#{issue_number}: HTTP {resp.status_code}")
        if resp.status_code == 404 and not GITHUB_TOKEN:
            print(f"[GitHub] 404 may mean this is a private repo — set GITHUB_TOKEN in .env")
    except requests.RequestException as e:
        print(f"[GitHub] Error fetching {repo}#{issue_number}: {e}")
    return None


def fetch_latest_issues(count: int = 5) -> list[dict]:
    """Fetch latest issues from ALL repos the token has access to."""
    if not GITHUB_TOKEN:
        print("[GitHub] GITHUB_TOKEN not set")
        return []

    all_issues = []
    repos = fetch_all_repos()

    for repo_info in repos:
        repo = repo_info["name"]
        url = f"{_GITHUB_API}/repos/{repo}/issues"
        params = {"state": "open", "per_page": count, "sort": "updated", "direction": "desc"}

        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=10)
            _check_rate_limit(resp)
            if resp.status_code == 200:
                items = resp.json()
                for item in items:
                    if "pull_request" not in item:
                        all_issues.append({
                            "title": item["title"],
                            "state": item["state"],
                            "url": item["html_url"],
                            "body": (item.get("body") or "")[:500],
                            "number": item["number"],
                            "repo": repo,
                            "type": "Issue",
                        })
                        if len(all_issues) >= count:
                            break
            if len(all_issues) >= count:
                break
        except requests.RequestException as e:
            print(f"[GitHub] Error fetching issues from {repo}: {e}")

    return all_issues[:count]


def fetch_latest_prs(count: int = 5) -> list[dict]:
    """Fetch latest PRs from ALL repos the token has access to."""
    if not GITHUB_TOKEN:
        print("[GitHub] GITHUB_TOKEN not set")
        return []

    all_prs = []
    repos = fetch_all_repos()

    for repo_info in repos:
        repo = repo_info["name"]
        url = f"{_GITHUB_API}/repos/{repo}/pulls"
        params = {"state": "open", "per_page": count, "sort": "updated", "direction": "desc"}

        try:
            resp = requests.get(url, headers=_headers(), params=params, timeout=10)
            _check_rate_limit(resp)
            if resp.status_code == 200:
                prs = resp.json()
                for pr in prs:
                    all_prs.append({
                        "title": pr["title"],
                        "state": pr["state"],
                        "url": pr["html_url"],
                        "body": (pr.get("body") or "")[:500],
                        "number": pr["number"],
                        "repo": repo,
                        "user": pr["user"]["login"],
                        "type": "PR",
                    })
                    if len(all_prs) >= count:
                        break
            if len(all_prs) >= count:
                break
        except requests.RequestException as e:
            print(f"[GitHub] Error fetching PRs from {repo}: {e}")

    return all_prs[:count]


def fetch_repo_issues(repo: str, count: int = 5) -> list[dict]:
    """Fetch latest issues from a specific repo. Works for public repos without a token."""
    url = f"{_GITHUB_API}/repos/{repo}/issues"
    params = {"state": "open", "per_page": count, "sort": "updated", "direction": "desc"}

    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        _check_rate_limit(resp)
        if resp.status_code == 200:
            items = resp.json()
            return [
                {
                    "title": item["title"],
                    "state": item["state"],
                    "url": item["html_url"],
                    "body": (item.get("body") or "")[:500],
                    "number": item["number"],
                    "repo": repo,
                    "type": "Issue",
                }
                for item in items
                if "pull_request" not in item
            ]
        print(f"[GitHub] Latest issues for {repo}: HTTP {resp.status_code}")
    except requests.RequestException as e:
        print(f"[GitHub] Error fetching latest issues: {e}")
    return []


def fetch_repo_prs(repo: str, count: int = 5) -> list[dict]:
    """Fetch latest PRs from a specific repo. Works for public repos without a token."""
    url = f"{_GITHUB_API}/repos/{repo}/pulls"
    params = {"state": "open", "per_page": count, "sort": "updated", "direction": "desc"}

    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        _check_rate_limit(resp)
        if resp.status_code == 200:
            prs = resp.json()
            return [
                {
                    "title": pr["title"],
                    "state": pr["state"],
                    "url": pr["html_url"],
                    "body": (pr.get("body") or "")[:500],
                    "number": pr["number"],
                    "repo": repo,
                    "user": pr["user"]["login"],
                    "type": "PR",
                }
                for pr in prs
            ]
        print(f"[GitHub] Latest PRs for {repo}: HTTP {resp.status_code}")
    except requests.RequestException as e:
        print(f"[GitHub] Error fetching latest PRs: {e}")
    return []


def find_similar_issues(repo: str, new_title: str, threshold: float = 0.55, count: int = 50) -> list[dict]:
    """Find open issues with similar titles using difflib."""
    issues = fetch_repo_issues(repo, count=count)
    scored = sorted(
        (
            (difflib.SequenceMatcher(None, new_title.lower(), i["title"].lower()).ratio(), i)
            for i in issues
        ),
        key=lambda x: -x[0],
    )
    return [{"score": round(s, 2), **i} for s, i in scored if s >= threshold][:3]


def fetch_merged_prs(repo: str, count: int = 15) -> list[dict]:
    """Fetch recently merged PRs from a repo."""
    if not GITHUB_TOKEN:
        print("[GitHub] GITHUB_TOKEN not set")
        return []

    url = f"{_GITHUB_API}/repos/{repo}/pulls"
    params = {"state": "closed", "per_page": count, "sort": "updated", "direction": "desc"}

    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=10)
        _check_rate_limit(resp)
        if resp.status_code == 200:
            return [
                {
                    "title": p["title"],
                    "number": p["number"],
                    "url": p["html_url"],
                }
                for p in resp.json()
                if p.get("merged_at")
            ]
        print(f"[GitHub] fetch_merged_prs for {repo}: HTTP {resp.status_code}")
    except requests.RequestException as e:
        print(f"[GitHub] Error fetching merged PRs: {e}")
    return []
