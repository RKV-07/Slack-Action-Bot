from typing import TypedDict, Literal, Optional
from pydantic import BaseModel


class ActionContext(BaseModel):
    user_id: str
    channel_id: str
    message_ts: str
    original_message: Optional[str] = None
    mentioned_by: Optional[str] = None


class ReminderData(BaseModel):
    text: str
    delay_seconds: int
    user_id: str
    channel_id: str


class BotState(TypedDict):
    command_type: Literal[
        "context", "reminder", "github", "mention",
        "latest_github", "greeting", "test_llm", "help", "chat",
        "learn", "codereview"
    ]
    action_context: Optional[ActionContext]
    reminder_data: Optional[ReminderData]
    github_refs: list[str]
    github_results: list[dict]
    user_id: str
    channel_id: str
    message_ts: str
    raw_input: str
    response_message: str
    needs_llm: bool
    llm_summary: Optional[str]
    thread_messages: list[dict]
    max_messages: int
    # Learn command fields
    learn_topic: str
    learn_resources: list[dict]
    learn_path: dict
    # Code review fields
    review_pr_data: dict
    review_security: str
    review_performance: str
    review_best_practices: str
