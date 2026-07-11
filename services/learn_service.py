"""
Learn Service - Multi-agent learning path generation.

Uses MCP tools (primary) or direct API (fallback) to research topics.
Uses Tavily search API for real web results (prevents hallucinated URLs).
Three agents: Research → Structure → Resources
"""

import json
import requests
from services.llm_service import _chat_completion
from config import GITHUB_TOKEN, TAVILY_API_KEY


def _tavily_search(query: str, count: int = 5) -> list:
    """Search the web via Tavily API for real, verified results."""
    if not TAVILY_API_KEY:
        return []
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": TAVILY_API_KEY, "query": query, "max_results": count},
            timeout=10,
        )
        if resp.status_code == 200:
            return [
                {"type": "web", "title": r["title"], "url": r["url"], "content": r.get("content", "")[:200]}
                for r in resp.json().get("results", [])[:count]
            ]
    except Exception as e:
        print(f"[Learn] Tavily search failed: {e}")
    return []


def _github_search_repos(query: str, count: int = 3) -> list:
    """Search GitHub repos via MCP or direct API."""
    # Try MCP first
    try:
        from services.mcp_client import mcp_client
        if "github" in mcp_client._sessions:
            result = mcp_client.call_tool("github", "search_repositories", {
                "query": query, "sort": "stars", "per_page": count
            })
            if result and not result.startswith("Error"):
                data = json.loads(result) if isinstance(result, str) else result
                if isinstance(data, dict) and "items" in data:
                    return [
                        {
                            "type": "repository",
                            "title": r.get("full_name", ""),
                            "url": r.get("html_url", ""),
                            "description": r.get("description", ""),
                            "stars": r.get("stargazers_count", 0),
                        }
                        for r in data["items"][:count]
                    ]
    except Exception as e:
        print(f"[Learn] MCP GitHub search failed: {e}")

    # Fallback: direct API
    if GITHUB_TOKEN:
        try:
            headers = {"Authorization": f"token {GITHUB_TOKEN}"}
            resp = requests.get(
                "https://api.github.com/search/repositories",
                params={"q": query, "sort": "stars", "per_page": count},
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                return [
                    {
                        "type": "repository",
                        "title": r.get("full_name", ""),
                        "url": r.get("html_url", ""),
                        "description": r.get("description", ""),
                        "stars": r.get("stargazers_count", 0),
                    }
                    for r in resp.json().get("items", [])[:count]
                ]
        except Exception as e:
            print(f"[Learn] Direct GitHub API failed: {e}")

    return []


def research_topic(topic: str) -> dict:
    """Research agent: Gather resources and information about the topic."""
    resources = _github_search_repos(f"{topic} tutorial")

    # Tavily web search for real, verified URLs (prevents hallucinated links)
    web_results = _tavily_search(f"{topic} learning resources tutorial documentation", count=5)
    resources.extend(web_results)

    # Use LLM to supplement with additional context (not URLs)
    llm_resources = _chat_completion(
        f"List 3-5 best types of learning resources for: {topic}\n"
        f"Describe what to search for (not URLs). Include: official docs, tutorials, courses.\n"
        f"Format as JSON array with title and type fields only (no url field).",
        max_tokens=400,
        system_msg="You are a learning resource curator. Do NOT invent URLs. Describe resource types only.",
    )

    if llm_resources:
        try:
            cleaned = llm_resources.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, dict):
                        resources.append({
                            "type": item.get("type", "tutorial"),
                            "title": item.get("title", ""),
                            "url": item.get("url", ""),
                        })
        except (json.JSONDecodeError, TypeError):
            resources.append({
                "type": "text",
                "title": "Learning Resources",
                "content": llm_resources,
            })

    return {"resources": resources}


def structure_learning_path(topic: str, resources: list) -> dict:
    """Structure agent: Organize by skill level and create learning path."""
    resource_text = "\n".join([
        f"- {r.get('title', 'Unknown')}: {r.get('url', r.get('content', '')[:100])}"
        for r in resources[:10]
    ])

    prompt = (
        f"Create a structured learning path for: {topic}\n\n"
        f"Available resources:\n{resource_text}\n\n"
        f"Return JSON with:\n"
        f'{{"levels": [{{"name": "Beginner", "topics": [...], "estimated_hours": N}}, '
        f'{{"name": "Intermediate", "topics": [...], "estimated_hours": N}}, '
        f'{{"name": "Advanced", "topics": [...], "estimated_hours": N}}], '
        f'"total_hours": N}}'
    )

    result = _chat_completion(prompt, max_tokens=800, system_msg=(
        "You are a learning path designer. Create practical, time-efficient paths. "
        "Return only valid JSON."
    ))

    path = {"levels": [], "total_hours": 0}
    if result is not None and result.strip():
        try:
            cleaned = result.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                path = parsed
        except (json.JSONDecodeError, TypeError):
            path = {
                "levels": [
                    {"name": "Beginner", "topics": [topic], "estimated_hours": 10},
                    {"name": "Intermediate", "topics": [f"Advanced {topic}"], "estimated_hours": 20},
                    {"name": "Advanced", "topics": [f"Expert {topic}"], "estimated_hours": 30},
                ],
                "total_hours": 60,
            }

    return path


def curate_resources(topic: str, resources: list, path: dict) -> str:
    """Resource agent: Finalize the learning path with curated resources."""
    resource_text = "\n".join([
        f"- [{r.get('title', 'Unknown')}]({r.get('url', '')})" if r.get("url")
        else f"- {r.get('title', 'Unknown')}: {str(r.get('content', ''))[:150]}"
        for r in resources[:8]
    ])

    levels_text = "\n".join([
        f"**{level.get('name', 'Unknown')}** (~{level.get('estimated_hours', '?')}h)\n"
        + "\n".join(f"  - {t}" for t in level.get("topics", []))
        for level in path.get("levels", [])
    ])

    prompt = (
        f"Create a learning path summary for: {topic}\n\n"
        f"Structured levels:\n{levels_text}\n\n"
        f"Resources:\n{resource_text}\n\n"
        f"Write a concise, encouraging summary with:\n"
        f"1. Quick overview (1-2 sentences)\n"
        f"2. Learning path with time estimates\n"
        f"3. Top 3 resources to start with\n"
        f"4. One practical project idea"
    )

    result = _chat_completion(prompt, max_tokens=600, system_msg=(
        "You are a friendly learning advisor. Be encouraging and practical. "
        "Use emoji sparingly. Keep it concise."
    ))

    if result:
        return result

    return (
        f"**Learning Path: {topic}**\n\n"
        f"**Levels:**\n{levels_text}\n\n"
        f"**Resources:**\n{resource_text}\n\n"
        f"Start with the beginner level and practice regularly!"
    )
