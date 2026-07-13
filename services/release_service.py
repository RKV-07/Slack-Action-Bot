from services.github_service import fetch_merged_prs
from services.llm_service import _chat_completion


def generate_release_notes(repo: str) -> str:
    """Generate release notes from recently merged PRs."""
    prs = fetch_merged_prs(repo)
    if not prs:
        return f"No recently merged PRs found for `{repo}`."

    pr_list = "\n".join(f"- {p['title']} (#{p['number']})" for p in prs)
    result = _chat_completion(
        f"Generate concise release notes from these merged PRs, grouped under "
        f"Features / Fixes / Other:\n\n{pr_list}",
        max_tokens=500,
        system_msg="You write clear, grouped release notes from PR titles.",
    )
    return result or f"Could not generate release notes for `{repo}` (LLM unavailable)."
