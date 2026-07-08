import os
import sys
from dotenv import load_dotenv

load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
DEFAULT_GITHUB_REPO = os.environ.get("DEFAULT_GITHUB_REPO", "owner/repo")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
LLAMA_BASE_URL = os.environ.get("LLAMA_BASE_URL", "http://localhost:8080")

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
