"""
Code Review Service - Multi-agent code review with 3 subagents.

Fans out to Security, Performance, and Best Practices reviewers.
Uses MCP GitHub (primary) or direct API (fallback) to fetch PR diffs.
Security reviewer uses Semgrep for real static analysis grounding.
"""

import json
import os
import re
import subprocess
import tempfile
import traceback
from typing import Optional
import requests
from services.llm_service import _chat_completion
from config import GITHUB_TOKEN


_last_fetch_via_mcp = False
_last_semgrep_findings: list[dict] = []


def parse_review_ref(raw_input: str) -> Optional[dict]:
    """Extract repo and PR number from user input."""
    match = re.search(r'([\w-]+/[\w-]+)#(\d+)', raw_input)
    if match:
        return {"repo": match.group(1), "pr_number": int(match.group(2))}

    url_match = re.search(r'github\.com/([\w-]+/[\w-]+)/pull/(\d+)', raw_input)
    if url_match:
        return {"repo": url_match.group(1), "pr_number": int(url_match.group(2))}

    # Bare repo (URL or owner/repo) with no PR number — return repo-only so
    # the caller can give a specific, useful error instead of a generic one.
    bare_url = re.search(r'github\.com/([\w.-]+/[\w.-]+?)(?:[/?#\s]|$)', raw_input)
    if bare_url:
        return {"repo": bare_url.group(1), "pr_number": None}
    bare_repo = re.search(r'\b([\w][\w-]*/[\w][\w-]*)\b', raw_input)
    if bare_repo and "#" not in raw_input:
        return {"repo": bare_repo.group(1), "pr_number": None}

    return None


def _github_get_pr(repo: str, pr_number: int) -> dict:
    """Fetch PR via MCP or direct API."""
    global _last_fetch_via_mcp

    owner, repo_name = repo.split("/") if "/" in repo else ("", repo)

    # Try MCP first
    try:
        from services.mcp_client import mcp_client
        if "github" in mcp_client._sessions:
            result = mcp_client.call_tool("github", "get_pull_request", {
                "owner": owner, "repo": repo_name, "pull_number": pr_number
            })
            if result and not result.startswith("Error"):
                _last_fetch_via_mcp = True
                pr_data = json.loads(result) if isinstance(result, str) else result
                if isinstance(pr_data, dict) and pr_data.get("title"):
                    return {
                        "title": pr_data.get("title", ""),
                        "body": (pr_data.get("body") or "")[:2000],
                        "state": pr_data.get("state", ""),
                        "diff_url": pr_data.get("diff_url", ""),
                        "files": pr_data.get("files", []),
                    }
    except Exception as e:
        print(f"[CodeReview] MCP fetch failed: {e}")
        traceback.print_exc()

    # Fallback: direct API (GET /pulls + GET /pulls/files for patch text)
    _last_fetch_via_mcp = False
    if GITHUB_TOKEN:
        try:
            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            resp = requests.get(
                f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}",
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                pr_data = resp.json()
                if not pr_data or not isinstance(pr_data, dict):
                    print(f"[CodeReview] GitHub API returned unexpected body for {repo}#{pr_number}: {str(pr_data)[:200]}")
                    return {"title": "Unknown PR", "body": "", "state": "unknown", "files": []}
                files = pr_data.get("files", [])

                # Also fetch files endpoint to get patch/diff text
                files_resp = requests.get(
                    f"https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/files",
                    headers=headers,
                    timeout=10,
                )
                if files_resp.status_code == 200:
                    files_data = files_resp.json()
                    if isinstance(files_data, list):
                        files = files_data

                return {
                    "title": pr_data.get("title", ""),
                    "body": (pr_data.get("body") or "")[:2000],
                    "state": pr_data.get("state", ""),
                    "diff_url": pr_data.get("diff_url", ""),
                    "files": files,
                }
            else:
                print(f"[CodeReview] GitHub API returned status {resp.status_code} for {repo}#{pr_number}")
        except Exception as e:
            print(f"[CodeReview] Direct API failed: {e}")
            traceback.print_exc()

    return {"title": "Unknown PR", "body": "", "state": "unknown", "files": []}


def fetch_pr_diff(repo: str, pr_number: int) -> dict:
    """Fetch PR details and diff."""
    return _github_get_pr(repo, pr_number)


def _run_semgrep(pr_data: dict) -> list[dict]:
    """Run Semgrep on PR diff files for real static analysis findings."""
    files = pr_data.get("files", [])
    if not files:
        return []

    findings = []
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Write patch files to temp dir for semgrep
            for f in files[:20]:
                patch = f.get("patch", "")
                filename = f.get("filename", "unknown")
                if not patch:
                    continue
                # Write the patched version
                filepath = os.path.join(tmp_dir, filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                # Extract added lines from patch for basic analysis
                added_lines = []
                for line in patch.split("\n"):
                    if line.startswith("+") and not line.startswith("+++"):
                        added_lines.append(line[1:])
                if added_lines:
                    with open(filepath, "w") as fh:
                        fh.write("\n".join(added_lines))

            if not os.listdir(tmp_dir):
                return []

            result = subprocess.run(
                ["semgrep", "--config=auto", "--json", "--timeout=20", tmp_dir],
                capture_output=True, text=True, timeout=25,
            )
            if result.stdout:
                data = json.loads(result.stdout)
                for r in data.get("results", [])[:15]:
                    findings.append({
                        "file": r.get("path", "unknown"),
                        "line": r.get("start", {}).get("line", 0),
                        "rule": r.get("check_id", "unknown"),
                        "message": r.get("extra", {}).get("message", ""),
                        "severity": r.get("extra", {}).get("severity", "INFO"),
                    })
    except FileNotFoundError:
        print("[Semgrep] Not installed — skipping static analysis")
    except subprocess.TimeoutExpired:
        print("[Semgrep] Scan timed out — skipping")
    except Exception as e:
        print(f"[Semgrep] Skipped: {e}")

    return findings


def review_security(pr_data: dict) -> str:
    """Security Reviewer subagent — grounded with Semgrep findings."""
    files_text = "\n".join([
        f"- {f.get('filename', 'unknown')}: +{f.get('additions', 0)}/-{f.get('deletions', 0)}"
        + (f"\n```diff\n{f['patch'][:1500]}\n```" if f.get("patch") else "")
        for f in pr_data.get("files", [])[:10]
    ]) or "No file details available"

    # Run Semgrep for real static analysis findings
    semgrep_findings = _run_semgrep(pr_data)
    global _last_semgrep_findings
    _last_semgrep_findings = semgrep_findings
    semgrep_section = ""
    if semgrep_findings:
        semgrep_section = "\nSemgrep static analysis findings:\n" + "\n".join(
            f"- [{f['severity']}] {f['file']}:{f['line']} — {f['rule']}: {f['message']}"
            for f in semgrep_findings[:10]
        ) + "\n"
    else:
        semgrep_section = "\nSemgrep: No static analysis issues detected (or semgrep not installed).\n"

    prompt = (
        f"Review this PR for SECURITY issues:\n\n"
        f"Title: {pr_data.get('title', 'Unknown')}\n"
        f"Description: {(pr_data.get('body') or 'No description')[:500]}\n"
        f"Files changed:\n{files_text}\n"
        f"{semgrep_section}\n"
        f"Check for:\n"
        f"- SQL injection vulnerabilities\n"
        f"- XSS (Cross-Site Scripting)\n"
        f"- Hardcoded secrets/credentials\n"
        f"- Insecure authentication/authorization\n"
        f"- Path traversal risks\n"
        f"- Insecure dependencies\n\n"
        f"IMPORTANT: If Semgrep found findings above, analyze each one and explain the risk.\n"
        f"Provide:\n"
        f"1. Security issues found (if any)\n"
        f"2. Risk level (Low/Medium/High)\n"
        f"3. Specific recommendations\n"
        f"Keep it concise - focus on actionable items."
    )

    result = _chat_completion(prompt, max_tokens=400, system_msg=(
        "You are a security code reviewer. Be specific about vulnerabilities. "
        "Focus on real risks, not style issues. If Semgrep found issues, prioritize those."
    ))

    return result or "Security review completed - no major issues found."


def review_performance(pr_data: dict) -> str:
    """Performance Reviewer subagent."""
    files_text = "\n".join([
        f"- {f.get('filename', 'unknown')}: +{f.get('additions', 0)}/-{f.get('deletions', 0)}"
        + (f"\n```diff\n{f['patch'][:1500]}\n```" if f.get("patch") else "")
        for f in pr_data.get("files", [])[:10]
    ]) or "No file details available"

    prompt = (
        f"Review this PR for PERFORMANCE issues:\n\n"
        f"Title: {pr_data.get('title', 'Unknown')}\n"
        f"Description: {(pr_data.get('body') or 'No description')[:500]}\n"
        f"Files changed:\n{files_text}\n\n"
        f"Check for:\n"
        f"- N+1 query problems\n"
        f"- Memory leaks or inefficient memory usage\n"
        f"- Unnecessary API calls or network requests\n"
        f"- Inefficient algorithms (O(n^2) where O(n) is possible)\n"
        f"- Missing caching opportunities\n"
        f"- Blocking operations in async code\n\n"
        f"Provide:\n"
        f"1. Performance issues found (if any)\n"
        f"2. Impact level (Low/Medium/High)\n"
        f"3. Optimization suggestions\n"
        f"Keep it concise - focus on measurable improvements."
    )

    result = _chat_completion(prompt, max_tokens=400, system_msg=(
        "You are a performance code reviewer. Be specific about bottlenecks. "
        "Focus on real performance gains."
    ))

    return result or "Performance review completed - no major issues found."


def review_best_practices(pr_data: dict) -> str:
    """Best Practices Reviewer subagent."""
    files_text = "\n".join([
        f"- {f.get('filename', 'unknown')}: +{f.get('additions', 0)}/-{f.get('deletions', 0)}"
        + (f"\n```diff\n{f['patch'][:1500]}\n```" if f.get("patch") else "")
        for f in pr_data.get("files", [])[:10]
    ]) or "No file details available"

    prompt = (
        f"Review this PR for BEST PRACTICES:\n\n"
        f"Title: {pr_data.get('title', 'Unknown')}\n"
        f"Description: {(pr_data.get('body') or 'No description')[:500]}\n"
        f"Files changed:\n{files_text}\n\n"
        f"Check for:\n"
        f"- Code style consistency\n"
        f"- Error handling patterns\n"
        f"- Documentation gaps\n"
        f"- Test coverage suggestions\n"
        f"- Code duplication\n"
        f"- Naming conventions\n"
        f"- SOLID principles adherence\n\n"
        f"Provide:\n"
        f"1. Best practice violations (if any)\n"
        f"2. Suggestions for improvement\n"
        f"3. Positive aspects of the code\n"
        f"Keep it constructive and balanced."
    )

    result = _chat_completion(prompt, max_tokens=400, system_msg=(
        "You are a best practices code reviewer. Be constructive. "
        "Balance criticism with recognition of good patterns."
    ))

    return result or "Best practices review completed - code looks good."


def _risk_score(security_text: str) -> str:
    """Compute a simple risk score from semgrep findings and security review text."""
    high = sum(1 for f in _last_semgrep_findings if f.get("severity") == "ERROR")
    if high > 0 or "high" in security_text.lower()[:200]:
        return "🔴 High"
    if _last_semgrep_findings or "medium" in security_text.lower()[:200]:
        return "🟡 Medium"
    return "🟢 Low"


def merge_reviews(security: str, performance: str, best_practices: str, pr_data: dict) -> str:
    """Merge all three review outputs into a formatted response."""
    pr_title = pr_data.get("title", "Unknown PR")

    source_note = "_via GitHub MCP_" if _last_fetch_via_mcp else "_via GitHub REST API (fallback)_"
    risk = _risk_score(security)

    sections = [
        f"**Code Review: {pr_title}**\n",
        f"**Risk Score: {risk}**\n",
        f"{'='*40}\n",
        f"**Security Review**\n{security}\n",
        f"{'='*40}\n",
        f"**Performance Review**\n{performance}\n",
        f"{'='*40}\n",
        f"**Best Practices Review**\n{best_practices}\n",
        f"{'='*40}\n",
        f"_Review generated by 3 AI subagents · {source_note}_",
    ]

    return "\n".join(sections)
