import os
import sys
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
LLAMA_BASE_URL = os.environ.get("LLAMA_BASE_URL", "http://localhost:8080")
LLAMA_PARALLEL = os.environ.get("LLAMA_PARALLEL")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY")

# LLM: local Qwen3 (primary default) with optional Gemini cross-fallback
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "local").lower()
LLM_FALLBACK_ENABLED = os.environ.get("LLM_FALLBACK_ENABLED", "true").lower() == "true"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

# MCP Server Configuration (MCP primary, direct API as fallback)
MCP_GITHUB_ENABLED = os.environ.get("MCP_GITHUB_ENABLED", "true").lower() == "true"
MCP_FETCH_ENABLED = os.environ.get("MCP_FETCH_ENABLED", "true").lower() == "true"
MCP_SLACK_ENABLED = os.environ.get("MCP_SLACK_ENABLED", "true").lower() == "true"

# Max messages used as context when summarizing Slack conversations
SLACK_SUMMARY_MAX_MESSAGES = int(os.environ.get("SLACK_SUMMARY_MAX_MESSAGES", "25"))

_required = {
    "SLACK_BOT_TOKEN": SLACK_BOT_TOKEN,
    "SLACK_APP_TOKEN": SLACK_APP_TOKEN,
    "SLACK_SIGNING_SECRET": SLACK_SIGNING_SECRET,
}

_missing = [k for k, v in _required.items() if not v]
if _missing:
    print(f"Missing required environment variables: {', '.join(_missing)}")
    print("Copy .env.example to .env and fill in your tokens.")
    sys.exit(1)
