"""
End-to-end tests for Slack Action Bot.
Tests complete flows: raw input → graph invoke → final response.
Run with: uv run pytest test_e2e.py -v
"""

import json
import os
import sys
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test-secret")
os.environ.setdefault("GITHUB_TOKEN", "ghp_test")
os.environ.setdefault("LLAMA_BASE_URL", "http://localhost:8080")
os.environ.setdefault("LLAMA_PARALLEL", "4")
os.environ.setdefault("MCP_GITHUB_ENABLED", "false")
os.environ.setdefault("MCP_FETCH_ENABLED", "false")
os.environ.setdefault("MCP_SLACK_ENABLED", "false")

sys.path.insert(0, os.path.dirname(__file__))

from graph.workflow import sab_graph
from handlers.shared import build_initial_state


def invoke(raw_input, thread_messages=None, **overrides):
    """Helper: build state and invoke the full graph."""
    state = build_initial_state(
        user_id="U123",
        channel_id="C_TEST",
        message_ts="1700000000.000100",
        raw_input=raw_input,
        thread_messages=thread_messages or [],
    )
    state.update(overrides)
    return sab_graph.invoke(state)


# ══════════════════════════════════════════════════════════════════
# GREETING
# ══════════════════════════════════════════════════════════════════

class TestE2EGreeting:
    @patch("services.llm_service._chat_completion", return_value="Hey! How can I help? 👋")
    def test_greeting_hi(self, mock_llm):
        result = invoke("hi")
        assert result["command_type"] == "greeting"
        assert "Hey" in result["response_message"]

    @patch("services.llm_service._chat_completion", return_value="Good morning! ☀️")
    def test_greeting_good_morning(self, mock_llm):
        result = invoke("good morning")
        assert result["command_type"] == "greeting"
        assert result["response_message"] != ""

    @patch("services.llm_service._chat_completion", return_value="I'm Slack Actions Bot!")
    def test_who_are_you(self, mock_llm):
        result = invoke("who are you")
        assert result["command_type"] == "help"


# ══════════════════════════════════════════════════════════════════
# HELP
# ══════════════════════════════════════════════════════════════════

class TestE2EHelp:
    @patch("services.llm_service._chat_completion", return_value="I can help with summaries and GitHub!")
    def test_empty_input_shows_help(self, mock_llm):
        result = invoke("")
        assert result["command_type"] == "help"
        assert result["response_message"] != ""

    @patch("services.llm_service._chat_completion", return_value="I'm your Slack bot assistant.")
    def test_help_via_llm(self, mock_llm):
        result = invoke("what can you do")
        assert result["command_type"] == "help"
        assert result["response_message"] != ""


# ══════════════════════════════════════════════════════════════════
# TEST LLM
# ══════════════════════════════════════════════════════════════════

class TestE2ETestLLM:
    @patch("services.llm_service._chat_completion", return_value="LLM is working!")
    def test_test_llm(self, mock_llm):
        result = invoke("test")
        assert result["command_type"] == "test_llm"
        assert "LLM is connected" in result["response_message"]
        assert "LLM is working!" in result["response_message"]

    @patch("services.llm_service._chat_completion", return_value="LLM is working!")
    def test_test_llm_variant(self, mock_llm):
        result = invoke("test llm")
        assert result["command_type"] == "test_llm"

    @patch("services.llm_service._chat_completion", return_value="")
    def test_test_llm_failure(self, mock_llm):
        result = invoke("test")
        assert "failed" in result["response_message"].lower()


# ══════════════════════════════════════════════════════════════════
# CHAT (default)
# ══════════════════════════════════════════════════════════════════

class TestE2EChat:
    @patch("services.llm_service._chat_completion", return_value="42")
    def test_random_question(self, mock_llm):
        result = invoke("what is the meaning of life")
        assert result["command_type"] == "chat"
        assert result["response_message"] == "42"

    @patch("services.llm_service._chat_completion", return_value="")
    def test_chat_empty_llm(self, mock_llm):
        result = invoke("tell me a joke")
        assert result["command_type"] == "chat"
        assert "not sure how to help" in result["response_message"].lower()


# ══════════════════════════════════════════════════════════════════
# REMINDER
# ══════════════════════════════════════════════════════════════════

class TestE2EReminder:
    @patch("services.reminder_service.scheduler")
    def test_reminder_with_r_flag(self, mock_scheduler):
        result = invoke('-r "standup meeting" @30m')
        assert result["command_type"] == "reminder"
        assert "Reminder set" in result["response_message"]
        assert "standup meeting" in result["response_message"]
        assert "30m" in result["response_message"]
        mock_scheduler.add_job.assert_called_once()

    @patch("services.reminder_service.scheduler")
    def test_reminder_with_remind_keyword(self, mock_scheduler):
        result = invoke('remind me to call mom @1h')
        assert result["command_type"] == "reminder"
        assert "Reminder set" in result["response_message"]
        assert "1h" in result["response_message"]

    @patch("services.reminder_service.scheduler")
    def test_reminder_minutes(self, mock_scheduler):
        result = invoke('-r "lunch" @15m')
        assert "15m" in result["response_message"]

    def test_reminder_bad_format(self):
        result = invoke('-r bad format here')
        assert "Could not parse" in result["response_message"]

    @patch("dateparser.parse")
    @patch("services.reminder_service.scheduler")
    def test_reminder_natural_language(self, mock_scheduler, mock_dp):
        from datetime import datetime, timedelta
        future = datetime.now() + timedelta(hours=2)
        mock_dp.return_value = future
        result = invoke('remind me to check server in 2 hours')
        assert result["command_type"] == "reminder"
        assert "Reminder set" in result["response_message"]


# ══════════════════════════════════════════════════════════════════
# GITHUB REF
# ══════════════════════════════════════════════════════════════════

class TestE2EGithub:
    @patch("graph.nodes.fetch_github_issue")
    def test_issue_lookup(self, mock_fetch):
        mock_fetch.return_value = {
            "title": "Fix login bug",
            "state": "open",
            "url": "https://github.com/fmhy/edit/issues/42",
            "body": "Users can't login",
            "labels": ["bug"],
            "number": 42,
            "repo": "fmhy/edit",
        }
        result = invoke("fmhy/edit#42")
        assert result["command_type"] == "github"
        assert "Fix login bug" in result["response_message"]
        assert "Open" in result["response_message"]

    @patch("graph.nodes.fetch_github_issue")
    def test_multiple_refs(self, mock_fetch):
        mock_fetch.side_effect = [
            {"title": "Issue 1", "state": "open", "url": "http://1", "number": 1, "repo": "a/b"},
            {"title": "Issue 2", "state": "closed", "url": "http://2", "number": 2, "repo": "c/d"},
        ]
        result = invoke("a/b#1 and c/d#2")
        assert "Issue 1" in result["response_message"]
        assert "Issue 2" in result["response_message"]

    @patch("graph.nodes.fetch_github_issue")
    def test_issue_not_found(self, mock_fetch):
        mock_fetch.return_value = None
        result = invoke("fmhy/edit#99999")
        assert "Could not fetch" in result["response_message"]


# ══════════════════════════════════════════════════════════════════
# LATEST GITHUB
# ══════════════════════════════════════════════════════════════════

class TestE2ELatestGithub:
    @patch("graph.nodes.fetch_latest_issues")
    def test_latest_issues(self, mock_fetch):
        mock_fetch.return_value = [
            {"title": "Bug A", "state": "open", "url": "http://a", "number": 1, "repo": "x/y", "type": "Issue"},
        ]
        result = invoke("latest issues")
        assert result["command_type"] == "latest_github"
        assert "Bug A" in result["response_message"]

    @patch("graph.nodes.fetch_latest_prs")
    def test_latest_prs(self, mock_fetch):
        mock_fetch.return_value = [
            {"title": "PR B", "state": "open", "url": "http://b", "number": 2, "repo": "x/y", "type": "PR"},
        ]
        result = invoke("recent prs")
        assert "PR B" in result["response_message"]

    @patch("graph.nodes.fetch_repo_issues")
    def test_latest_issues_specific_repo(self, mock_fetch):
        mock_fetch.return_value = [
            {"title": "Repo Issue", "state": "open", "url": "http://r", "number": 5, "repo": "fmhy/edit", "type": "Issue"},
        ]
        result = invoke("latest issues fmhy/edit")
        assert "Repo Issue" in result["response_message"]


# ══════════════════════════════════════════════════════════════════
# SUMMARIZE (context)
# ══════════════════════════════════════════════════════════════════

class TestE2ESummarize:
    @patch("services.llm_service._chat_completion", return_value="The team discussed deploying v2 by Friday.")
    def test_summarize_with_thread(self, mock_llm):
        thread = [
            {"user": "U1", "text": "We need to deploy v2 by Friday"},
            {"user": "U2", "text": "Agreed, let's do it"},
            {"user": "U3", "text": "I'll handle the QA testing"},
        ]
        result = invoke("", thread_messages=thread)
        assert result["command_type"] == "context"
        assert "deploy" in result["response_message"].lower()

    @patch("services.llm_service._chat_completion", return_value="Summary here.")
    def test_summarize_keyword(self, mock_llm):
        result = invoke("summarize")
        assert result["command_type"] == "context"
        assert result["needs_llm"] is True

    @patch("services.llm_service._chat_completion", return_value="Thread summary.")
    def test_fallback_to_channel(self, mock_llm):
        """No thread messages → falls back to channel summarize via Slack MCP."""
        result = invoke("summarize", thread_messages=[])
        # Without Slack MCP, should still produce a response
        assert result["response_message"] != ""


# ══════════════════════════════════════════════════════════════════
# LEARN
# ══════════════════════════════════════════════════════════════════

class TestE2ELearn:
    @patch("services.learn_service._chat_completion")
    def test_full_learn_flow(self, mock_llm):
        """learn → research → structure → resources → response"""
        mock_llm.side_effect = [
            # research_topic: LLM resources
            json.dumps([
                {"title": "Python Docs", "url": "https://docs.python.org", "type": "docs"},
                {"title": "Real Python", "url": "https://realpython.com", "type": "tutorial"},
            ]),
            # structure_learning_path: structured path
            json.dumps({
                "levels": [
                    {"name": "Beginner", "topics": ["Variables", "Loops"], "estimated_hours": 10},
                    {"name": "Intermediate", "topics": ["OOP", "Decorators"], "estimated_hours": 20},
                    {"name": "Advanced", "topics": ["Metaclasses", "Async"], "estimated_hours": 30},
                ],
                "total_hours": 60,
            }),
            # curate_resources: final summary
            "**Python Learning Path**\n\nStart with variables and loops. Then move to OOP.",
        ]
        result = invoke("learn python")
        assert result["command_type"] == "learn"
        assert result["response_message"] != ""
        assert "Python" in result["response_message"]
        # Verify all 3 LLM calls were made
        assert mock_llm.call_count == 3

    def test_learn_empty_topic(self):
        result = invoke("learn")
        assert "specify a topic" in result["response_message"].lower()

    @patch("services.learn_service._chat_completion")
    def test_learn_topic_extraction(self, mock_llm):
        mock_llm.side_effect = ["[]", '{"levels":[],"total_hours":0}', "Summary"]
        result = invoke("learn rust async programming")
        assert result["learn_topic"] == "rust async programming"


# ══════════════════════════════════════════════════════════════════
# CODEREVIEW
# ══════════════════════════════════════════════════════════════════

class TestE2ECodeReview:
    @patch("graph.nodes.merge_reviews")
    @patch("graph.nodes.review_best_practices", return_value="Good practices overall.")
    @patch("graph.nodes.review_performance", return_value="No major issues.")
    @patch("graph.nodes.review_security", return_value="No vulnerabilities found.")
    @patch("graph.nodes.fetch_pr_diff")
    def test_full_codereview_flow(self, mock_fetch, mock_sec, mock_perf, mock_bp, mock_merge):
        """codereview → fetch → [3 subagents] → merge → response"""
        mock_fetch.return_value = {
            "title": "Add login feature",
            "body": "Adds OAuth2 login",
            "state": "open",
            "files": [{"filename": "auth.py", "additions": 50, "deletions": 0, "patch": "+import oauth2"}],
        }
        mock_merge.return_value = "**Code Review: Add login feature**\n\nSecurity: Clean.\nPerf: OK.\nBP: Good."

        result = invoke("codereview fmhy/edit#100")
        assert result["command_type"] == "codereview"
        assert "Code Review" in result["response_message"]
        # All 3 subagents should have been called
        mock_sec.assert_called_once()
        mock_perf.assert_called_once()
        mock_bp.assert_called_once()
        mock_merge.assert_called_once()

    @patch("graph.nodes.fetch_pr_diff")
    def test_codereview_fetch_failure_skips_subagents(self, mock_fetch):
        """If fetch fails, subagents should NOT run."""
        mock_fetch.return_value = {"title": "Unknown PR", "body": "", "state": "unknown", "files": []}
        result = invoke("codereview fmhy/edit#99999")
        assert "Could not fetch" in result["response_message"]

    def test_codereview_no_ref(self):
        result = invoke("codereview")
        assert "Could not parse" in result["response_message"]

    def test_codereview_bare_number(self):
        """Bare #123 should not be parseable as codereview ref."""
        result = invoke("codereview #123")
        assert "Could not parse" in result["response_message"]


# ══════════════════════════════════════════════════════════════════
# THREAD CONTEXT (app_mention in thread)
# ══════════════════════════════════════════════════════════════════

class TestE2EThreadContext:
    @patch("services.llm_service._chat_completion", return_value="The thread is about deployment plans.")
    def test_mention_in_thread_triggers_summarize(self, mock_llm):
        thread = [
            {"user": "U1", "text": "Let's deploy tonight"},
            {"user": "U2", "text": "Sounds good, I'll prep the configs"},
        ]
        result = invoke("what's this thread about", thread_messages=thread)
        assert result["command_type"] == "context"
        assert result["needs_llm"] is True

    @patch("services.llm_service._chat_completion", return_value="Here's a summary.")
    def test_empty_mention_no_thread_goes_to_chat(self, mock_llm):
        result = invoke("hello", thread_messages=[])
        assert result["command_type"] == "greeting"


# ══════════════════════════════════════════════════════════════════
# EDGE CASES
# ══════════════════════════════════════════════════════════════════

class TestE2EEdgeCases:
    @patch("services.llm_service._chat_completion", return_value="OK")
    def test_whitespace_only_input(self, mock_llm):
        result = invoke("   ")
        # Whitespace strips to empty → help (no thread messages)
        assert result["command_type"] == "help"

    @patch("services.llm_service._chat_completion", return_value="OK")
    def test_very_long_input(self, mock_llm):
        result = invoke("x" * 5000)
        assert result["response_message"] != ""

    def test_bare_123_not_github(self):
        """Bare #123 should NOT route to github — goes to chat."""
        with patch("services.llm_service._chat_completion", return_value="I don't understand #123"):
            result = invoke("#123")
            assert result["command_type"] == "chat"

    @patch("services.llm_service._chat_completion", return_value="OK")
    def test_mixed_commands_fallback(self, mock_llm):
        """Unrecognizable input falls back to chat."""
        result = invoke("asdfghjkl")
        assert result["command_type"] == "chat"

    @patch("services.llm_service._chat_completion")
    def test_learn_case_insensitive(self, mock_llm):
        mock_llm.side_effect = ["[]", '{"levels":[],"total_hours":0}', "Summary"]
        result = invoke("LEARN Python")
        assert result["command_type"] == "learn"

    @patch("graph.nodes.fetch_github_issue")
    def test_codereview_not_github_ref(self, mock_fetch):
        """'codereview' with no valid ref → parse error, not github lookup."""
        result = invoke("codereview blah")
        assert "Could not parse" in result["response_message"]
        mock_fetch.assert_not_called()


# ══════════════════════════════════════════════════════════════════
# GRAPH STATE INTEGRITY
# ══════════════════════════════════════════════════════════════════

class TestE2EStateIntegrity:
    @patch("services.llm_service._chat_completion", return_value="hi!")
    def test_state_has_all_required_fields(self, mock_llm):
        result = invoke("hey")
        required_fields = [
            "command_type", "action_context", "reminder_data",
            "github_refs", "github_results", "user_id", "channel_id",
            "message_ts", "raw_input", "response_message", "needs_llm",
            "llm_summary", "thread_messages", "max_messages",
            "learn_topic", "learn_resources", "learn_path",
            "review_pr_data", "review_security", "review_performance",
            "review_best_practices",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    @patch("services.llm_service._chat_completion", return_value="ok")
    def test_user_id_preserved(self, mock_llm):
        result = invoke("hi")
        assert result["user_id"] == "U123"
        assert result["channel_id"] == "C_TEST"

    @patch("services.llm_service._chat_completion", return_value="ok")
    def test_raw_input_preserved(self, mock_llm):
        result = invoke("hello world")
        assert result["raw_input"] == "hello world"


# ══════════════════════════════════════════════════════════════════
# CONCURRENT INVOCATIONS
# ══════════════════════════════════════════════════════════════════

class TestE2EConcurrent:
    @patch("services.llm_service._chat_completion", return_value="ok")
    def test_sequential_invocations_independent(self, mock_llm):
        """Multiple invocations should not share state."""
        r1 = invoke("hi")
        r2 = invoke("test")
        r3 = invoke("what is 2+2")
        assert r1["command_type"] == "greeting"
        assert r2["command_type"] == "test_llm"
        assert r3["command_type"] == "chat"
        # Each should have its own response
        assert r1["response_message"] != r2["response_message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
