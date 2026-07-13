import time
import hashlib
from typing import Callable, Optional
from functools import wraps


class SlackBotFeatures:
    def __init__(self, client):
        self.client = client
        self._input_transforms: list[Callable] = []
        self._output_transforms: list[Callable] = []
        self._processing_emoji = "thinking_face"

    def set_processing_emoji(self, emoji: str):
        self._processing_emoji = emoji

    def add_input_transform(self, func: Callable):
        self._input_transforms.append(func)
        return func

    def add_output_transform(self, func: Callable):
        self._output_transforms.append(func)
        return func

    def transform_input(self, message: str, context: dict) -> str:
        result = message
        for transform in self._input_transforms:
            result = transform(result, context)
        return result

    def transform_output(self, message: str, context: dict) -> str:
        result = message
        for transform in self._output_transforms:
            result = transform(result, context)
        return result

    def add_reaction(self, channel: str, timestamp: str, emoji: str = None):
        emoji = emoji or self._processing_emoji
        try:
            self.client.reactions_add(
                channel=channel,
                timestamp=timestamp,
                name=emoji,
            )
        except Exception:
            pass

    def remove_reaction(self, channel: str, timestamp: str, emoji: str = None):
        emoji = emoji or self._processing_emoji
        try:
            self.client.reactions_remove(
                channel=channel,
                timestamp=timestamp,
                name=emoji,
            )
        except Exception:
            pass

    def send_with_feedback(self, channel: str, text: str, thread_ts: str = None,
                           user_id: str = None, include_feedback: bool = True):
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": text}
            }
        ]

        if include_feedback and user_id:
            feedback_id = hashlib.md5(f"{text}{time.time()}".encode()).hexdigest()[:10]
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "👍 Helpful"},
                        "action_id": f"feedback_up_{feedback_id}",
                        "style": "primary",
                        "value": feedback_id,
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "👎 Not helpful"},
                        "action_id": f"feedback_down_{feedback_id}",
                        "style": "danger",
                        "value": feedback_id,
                    },
                ]
            })

        kwargs = {
            "channel": channel,
            "blocks": blocks,
            "text": text,
        }
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        return self.client.chat_postMessage(**kwargs)

    def get_thread_context(self, channel: str, thread_ts: str, limit: int = 20) -> list[dict]:
        try:
            result = self.client.conversations_replies(
                channel=channel,
                ts=thread_ts,
                limit=limit,
            )
            messages = result.get("messages", [])
            return [
                {
                    "user": m.get("user", "unknown"),
                    "text": m.get("text", ""),
                    "is_bot": bool(m.get("bot_id")),
                }
                for m in messages
            ]
        except Exception:
            return []


def with_processing_reaction(func):
    @wraps(func)
    def wrapper(event, say, client, *args, **kwargs):
        channel = event.get("channel", "")
        ts = event.get("ts", "")

        features = SlackBotFeatures(client)
        features.add_reaction(channel, ts)

        try:
            result = func(event, say, client, *args, **kwargs)
            return result
        finally:
            features.remove_reaction(channel, ts)

    return wrapper
