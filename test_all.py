"""
Unit tests for Slack Action Bot.
Run with: uv run pytest test_all.py -v
"""

import json
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

# ── Patch env before any project imports ──────────────────────────
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


# ══════════════════════════════════════════════════════════════════
# handlers/shared.py
# ══════════════════════════════════════════════════════════════════

class TestIsRealMessage:
    def test_real_human_message(self):
        from handlers.shared import is_real_message
        assert is_real_message({"text": "hello", "user": "U1"}) is True

    def test_bot_id_filtered(self):
        from handlers.shared import is_real_message
        assert is_real_message({"bot_id": "B123", "text": "hi", "user": "U1"}) is False

    def test_subtype_bot_message_filtered(self):
        from handlers.shared import is_real_message
        assert is_real_message({"subtype": "bot_message", "text": "hi", "user": "U1"}) is False

    def test_subtype_bot_add_filtered(self):
        from handlers.shared import is_real_message
        assert is_real_message({"subtype": "bot_add", "text": "hi", "user": "U1"}) is False

    def test_empty_text_filtered(self):
        from handlers.shared import is_real_message
        assert is_real_message({"text": "", "user": "U1"}) is False
        assert is_real_message({"text": "   ", "user": "U1"}) is False

    def test_bot_user_id_filtered(self):
        from handlers.shared import is_real_message
        assert is_real_message({"text": "hi", "user": "U_BOT"}, "U_BOT") is False
        assert is_real_message({"text": "hi", "user": "U_OTHER"}, "U_BOT") is True

    def test_no_user_field(self):
        from handlers.shared import is_real_message
        assert is_real_message({"text": "hello"}) is True

    def test_unknown_subtype_not_filtered(self):
        from handlers.shared import is_real_message
        assert is_real_message({"subtype": "channel_join", "text": "hi", "user": "U1"}) is True

    def test_message_changed_not_filtered(self):
        from handlers.shared import is_real_message
        assert is_real_message({"subtype": "message_changed", "text": "updated", "user": "U1"}) is True


class TestBuildInitialState:
    def test_minimal(self):
        from handlers.shared import build_initial_state
        state = build_initial_state(
            user_id="U1", channel_id="C1", message_ts="123.456", raw_input="hello"
        )
        assert state["user_id"] == "U1"
        assert state["channel_id"] == "C1"
        assert state["raw_input"] == "hello"
        assert state["command_type"] == "help"
        assert state["response_message"] == ""
        assert state["thread_messages"] == []
        assert state["max_messages"] == 25

    def test_with_thread_messages(self):
        from handlers.shared import build_initial_state
        msgs = [{"user": "U1", "text": "hey"}, {"user": "U2", "text": "yo"}]
        state = build_initial_state(
            user_id="U1", channel_id="C1", message_ts="123",
            raw_input="summarize", thread_messages=msgs,
        )
        assert len(state["thread_messages"]) == 2

    def test_action_context_created(self):
        from handlers.shared import build_initial_state
        state = build_initial_state(
            user_id="U1", channel_id="C1", message_ts="123",
            raw_input="hi", original_message="Hello bot",
        )
        assert state["action_context"] is not None
        assert state["action_context"].original_message == "Hello bot"

    def test_no_action_context_without_original(self):
        from handlers.shared import build_initial_state
        state = build_initial_state(
            user_id="U1", channel_id="C1", message_ts="123", raw_input="hi"
        )
        assert state["action_context"] is None

    def test_learn_fields_present(self):
        from handlers.shared import build_initial_state
        state = build_initial_state(
            user_id="U1", channel_id="C1", message_ts="1", raw_input="learn python"
        )
        assert "learn_topic" in state
        assert "learn_resources" in state
        assert "learn_path" in state

    def test_codereview_fields_present(self):
        from handlers.shared import build_initial_state
        state = build_initial_state(
            user_id="U1", channel_id="C1", message_ts="1", raw_input="codereview owner/repo#1"
        )
        assert "review_pr_data" in state
        assert "review_security" in state
        assert "review_performance" in state
        assert "review_best_practices" in state


# ══════════════════════════════════════════════════════════════════
# services/github_service.py
# ══════════════════════════════════════════════════════════════════

class TestDetectGithubRefs:
    def test_owner_repo_number(self):
        from services.github_service import detect_github_refs
        refs = detect_github_refs("Check fmhy/edit#5758 please")
        assert "fmhy/edit#5758" in refs

    def test_bare_number_not_returned(self):
        """Bare #123 should NOT produce a ref — no default repo."""
        from services.github_service import detect_github_refs
        refs = detect_github_refs("What about #123?")
        assert refs == []

    def test_multiple_refs(self):
        from services.github_service import detect_github_refs
        refs = detect_github_refs("fmhy/edit#5758 and RKV-07/Slack-Action-Bot#2")
        assert "fmhy/edit#5758" in refs
        assert "RKV-07/Slack-Action-Bot#2" in refs

    def test_no_refs(self):
        from services.github_service import detect_github_refs
        refs = detect_github_refs("Hello world")
        assert refs == []

    def test_url_no_ref(self):
        from services.github_service import detect_github_refs
        refs = detect_github_refs("https://github.com/fmhy/edit")
        # URLs with no # don't produce refs via this regex
        assert len(refs) == 0

    def test_owner_with_hyphen(self):
        from services.github_service import detect_github_refs
        refs = detect_github_refs("RKV-07/Slack-Action-Bot#2")
        assert "RKV-07/Slack-Action-Bot#2" in refs


class TestExtractRepoFromText:
    def test_github_url(self):
        from services.github_service import extract_repo_from_text
        assert extract_repo_from_text("https://github.com/fmhy/edit/issues") == "fmhy/edit"

    def test_github_url_with_trailing_slash(self):
        from services.github_service import extract_repo_from_text
        assert extract_repo_from_text("https://github.com/fmhy/edit/") == "fmhy/edit"

    def test_github_url_with_query(self):
        from services.github_service import extract_repo_from_text
        assert extract_repo_from_text("https://github.com/fmhy/edit?q=1") == "fmhy/edit"

    def test_plain_owner_repo(self):
        from services.github_service import extract_repo_from_text
        assert extract_repo_from_text("Check fmhy/edit for updates") == "fmhy/edit"

    def test_plain_with_git_suffix(self):
        from services.github_service import extract_repo_from_text
        result = extract_repo_from_text("git clone https://github.com/fmhy/edit.git")
        assert result == "fmhy/edit"

    def test_no_repo(self):
        from services.github_service import extract_repo_from_text
        assert extract_repo_from_text("Hello world") is None

    def test_dot_rejected_in_segments(self):
        from services.github_service import extract_repo_from_text
        # "some.thing/repo" should not match
        assert extract_repo_from_text("some.thing/repo is a repo") is None

    def test_owner_with_hyphen(self):
        from services.github_service import extract_repo_from_text
        assert extract_repo_from_text("RKV-07/Slack-Action-Bot") == "RKV-07/Slack-Action-Bot"


class TestFetchGithubIssue:
    @patch("services.github_service.requests.get")
    def test_success(self, mock_get):
        from services.github_service import fetch_github_issue
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "title": "Bug report",
                "state": "open",
                "html_url": "https://github.com/fmhy/edit/issues/1",
                "body": "Description here",
                "labels": [{"name": "bug"}],
                "number": 1,
            },
        )
        result = fetch_github_issue("fmhy/edit", 1)
        assert result is not None
        assert result["title"] == "Bug report"
        assert result["state"] == "open"
        assert result["labels"] == ["bug"]
        assert result["repo"] == "fmhy/edit"

    @patch("services.github_service.requests.get")
    def test_404_returns_none(self, mock_get):
        from services.github_service import fetch_github_issue
        mock_get.return_value = MagicMock(status_code=404)
        assert fetch_github_issue("fmhy/edit", 99999) is None

    def test_no_token_returns_none(self):
        """Public repos now work without token — this should succeed."""
        from services.github_service import fetch_github_issue
        with patch("services.github_service.GITHUB_TOKEN", None):
            result = fetch_github_issue("fmhy/edit", 1)
            assert result is not None


# ══════════════════════════════════════════════════════════════════
# services/codereview_service.py
# ══════════════════════════════════════════════════════════════════

class TestParseReviewRef:
    def test_owner_repo_number(self):
        from services.codereview_service import parse_review_ref
        ref = parse_review_ref("codereview fmhy/edit#5758")
        assert ref["repo"] == "fmhy/edit"
        assert ref["pr_number"] == 5758

    def test_url_format(self):
        from services.codereview_service import parse_review_ref
        ref = parse_review_ref("https://github.com/fmhy/edit/pull/5758")
        assert ref["repo"] == "fmhy/edit"
        assert ref["pr_number"] == 5758

    def test_no_match(self):
        from services.codereview_service import parse_review_ref
        assert parse_review_ref("no pr here") is None

    def test_bare_number_no_repo(self):
        from services.codereview_service import parse_review_ref
        ref = parse_review_ref("#123")
        assert ref is None  # no owner/repo part

    def test_hyphenated_owner(self):
        from services.codereview_service import parse_review_ref
        ref = parse_review_ref("RKV-07/Slack-Action-Bot#2")
        assert ref["repo"] == "RKV-07/Slack-Action-Bot"
        assert ref["pr_number"] == 2

    def test_bare_repo_url_no_pr(self):
        from services.codereview_service import parse_review_ref
        ref = parse_review_ref("https://github.com/fmhy/edit")
        assert ref["repo"] == "fmhy/edit"
        assert ref["pr_number"] is None

    def test_bare_repo_no_pr(self):
        from services.codereview_service import parse_review_ref
        ref = parse_review_ref("fmhy/edit")
        assert ref["repo"] == "fmhy/edit"
        assert ref["pr_number"] is None


class TestSemgrep:
    def test_semgrep_graceful_skip(self):
        from services.codereview_service import _run_semgrep
        findings = _run_semgrep({"files": []})
        assert findings == []


class TestReminderPersistence:
    def test_scheduler_has_sqlalchemy_jobstore(self):
        from services.reminder_service import scheduler
        assert "default" in scheduler._jobstores

    def test_list_reminders_empty(self):
        from services.reminder_service import list_reminders
        result = list_reminders("U_nonexistent")
        assert isinstance(result, list)

    def test_cancel_nonexistent_returns_false(self):
        from services.reminder_service import cancel_reminder
        result = cancel_reminder("reminder_nonexistent")
        assert result is False


class TestGitHubRateLimit:
    def test_check_rate_limit(self):
        from services.github_service import _check_rate_limit, _rate_limit_remaining
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.headers = {"X-RateLimit-Remaining": "4999", "X-RateLimit-Reset": "1234567890"}
        _check_rate_limit(resp)
        from services.github_service import _rate_limit_remaining as remaining
        assert remaining == 4999


class TestTavilySearch:
    @patch("services.learn_service.TAVILY_API_KEY", "test-key")
    @patch("services.learn_service.requests.post")
    def test_tavily_returns_results(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {"title": "Python Tutorial", "url": "https://example.com", "content": "Learn Python"}
            ]
        }
        mock_post.return_value = mock_resp
        from services.learn_service import _tavily_search
        results = _tavily_search("python tutorial")
        assert len(results) == 1
        assert results[0]["title"] == "Python Tutorial"
        assert results[0]["type"] == "web"

    @patch("services.learn_service.TAVILY_API_KEY", "test-key")
    @patch("services.learn_service.requests.post")
    def test_tavily_graceful_failure(self, mock_post):
        mock_post.side_effect = Exception("timeout")
        from services.learn_service import _tavily_search
        results = _tavily_search("python tutorial")
        assert results == []

    @patch("services.learn_service.TAVILY_API_KEY", None)
    def test_tavily_no_key_returns_empty(self):
        from services.learn_service import _tavily_search
        results = _tavily_search("python tutorial")
        assert results == []


class TestGithubGetPr:
    @patch("services.codereview_service.requests.get")
    def test_direct_api_success(self, mock_get):
        from services.codereview_service import _github_get_pr
        # First call: GET /pulls/N
        pr_resp = MagicMock(
            status_code=200,
            json=lambda: {
                "title": "Add feature",
                "body": "Description",
                "state": "open",
                "diff_url": "https://github.com/fmhy/edit/pull/1.diff",
            },
        )
        # Second call: GET /pulls/N/files
        files_resp = MagicMock(
            status_code=200,
            json=lambda: [{"filename": "test.py", "patch": "@@ -1 +1 @@"}],
        )
        mock_get.side_effect = [pr_resp, files_resp]

        result = _github_get_pr("fmhy/edit", 1)
        assert result["title"] == "Add feature"
        assert result["state"] == "open"
        assert len(result["files"]) == 1
        assert result["files"][0]["filename"] == "test.py"

    @patch("services.codereview_service.requests.get")
    def test_direct_api_404(self, mock_get):
        from services.codereview_service import _github_get_pr
        mock_get.return_value = MagicMock(status_code=404)
        result = _github_get_pr("fmhy/edit", 99999)
        assert result["title"] == "Unknown PR"

    @patch("services.codereview_service.requests.get")
    def test_direct_api_null_json(self, mock_get):
        from services.codereview_service import _github_get_pr
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: None,
        )
        result = _github_get_pr("fmhy/edit", 1)
        assert result["title"] == "Unknown PR"

    def test_mcp_list_response(self):
        """MCP returning a list instead of a dict should not crash."""
        from services.codereview_service import _github_get_pr
        mock_result_text = json.dumps([{"title": "PR", "body": "", "state": "open"}])

        with patch("services.mcp_client.mcp_client") as mock_mcp:
            mock_mcp._sessions = {"github": True}
            mock_mcp.call_tool.return_value = mock_result_text
            result = _github_get_pr("fmhy/edit", 1)
            assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════
# services/llm_service.py
# ══════════════════════════════════════════════════════════════════

class TestChatCompletion:
    @patch("services.llm_service.requests.post")
    def test_success_content(self, mock_post):
        from services.llm_service import _chat_completion
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "Hello!"}}]},
        )
        result = _chat_completion("hi", max_tokens=50)
        assert result == "Hello!"

    @patch("services.llm_service.requests.post")
    def test_success_reasoning_fallback(self, mock_post):
        from services.llm_service import _chat_completion
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "", "reasoning_content": "Thinking..."}}]},
        )
        result = _chat_completion("hi", max_tokens=50)
        assert result == "Thinking..."

    @patch("services.llm_service.requests.post")
    def test_empty_response(self, mock_post):
        from services.llm_service import _chat_completion
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "", "reasoning_content": ""}}]},
        )
        result = _chat_completion("hi", max_tokens=50)
        assert result == ""

    @patch("services.llm_service.requests.post")
    def test_http_error(self, mock_post):
        from services.llm_service import _chat_completion
        mock_post.return_value = MagicMock(status_code=500)
        result = _chat_completion("hi", max_tokens=50)
        assert result == ""

    @patch("services.llm_service.requests.post")
    def test_timeout(self, mock_post):
        from services.llm_service import _chat_completion
        import requests as req
        mock_post.side_effect = req.Timeout("timed out")
        result = _chat_completion("hi", max_tokens=50)
        assert result == ""

    @patch("services.llm_service.requests.post")
    def test_no_think_prefix_added(self, mock_post):
        from services.llm_service import _chat_completion
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "ok"}}]},
        )
        _chat_completion("test", max_tokens=10)
        call_data = mock_post.call_args[1]["json"]
        # The user message should have /no_think prefix
        assert call_data["messages"][-1]["content"].startswith("/no_think")

    @patch("services.llm_service.requests.post")
    def test_system_msg_included(self, mock_post):
        from services.llm_service import _chat_completion
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "ok"}}]},
        )
        _chat_completion("test", max_tokens=10, system_msg="Be helpful")
        call_data = mock_post.call_args[1]["json"]
        assert call_data["messages"][0]["role"] == "system"
        assert call_data["messages"][0]["content"] == "Be helpful"


class TestSummarizeThreadMessages:
    def test_empty_messages(self):
        from services.llm_service import summarize_thread_messages
        result = summarize_thread_messages([])
        assert "No messages" in result

    @patch("services.llm_service.requests.post")
    def test_uses_tail_not_head(self, mock_post):
        from services.llm_service import summarize_thread_messages
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"choices": [{"message": {"content": "Summary"}}]},
        )
        msgs = [{"user": f"U{i}", "text": f"msg{i}"} for i in range(20)]
        summarize_thread_messages(msgs, max_messages=5)
        call_data = mock_post.call_args[1]["json"]
        prompt = call_data["messages"][-1]["content"]
        # Should contain the last 5 messages (15-19), not first 5
        assert "User U15" in prompt
        assert "User U19" in prompt
        assert "User U0" not in prompt

    @patch("services.llm_service.requests.post")
    def test_fallback_on_empty_llm(self, mock_post):
        from services.llm_service import summarize_thread_messages
        mock_post.return_value = MagicMock(status_code=500)
        msgs = [{"user": "U1", "text": "hello"}, {"user": "U2", "text": "world"}]
        result = summarize_thread_messages(msgs, max_messages=10)
        assert "hello" in result
        assert "world" in result


# ══════════════════════════════════════════════════════════════════
# services/learn_service.py
# ══════════════════════════════════════════════════════════════════

class TestResearchTopic:
    @patch("services.learn_service._chat_completion")
    def test_llm_json_resources(self, mock_llm):
        from services.learn_service import research_topic
        mock_llm.return_value = json.dumps([
            {"title": "Python Docs", "url": "https://docs.python.org", "type": "docs"}
        ])
        result = research_topic("python")
        assert len(result["resources"]) >= 1
        # Should have the LLM-generated resource
        urls = [r.get("url", "") for r in result["resources"]]
        assert "https://docs.python.org" in urls

    @patch("services.learn_service._chat_completion")
    def test_llm_non_json_fallback(self, mock_llm):
        from services.learn_service import research_topic
        mock_llm.return_value = "Check out python.org for tutorials"
        result = research_topic("python")
        # Should have a text fallback resource
        assert any(r.get("type") == "text" for r in result["resources"])

    @patch("services.learn_service._chat_completion")
    def test_llm_empty(self, mock_llm):
        from services.learn_service import research_topic
        mock_llm.return_value = ""
        result = research_topic("python")
        assert isinstance(result["resources"], list)


class TestStructureLearningPath:
    @patch("services.learn_service._chat_completion")
    def test_valid_json(self, mock_llm):
        from services.learn_service import structure_learning_path
        mock_llm.return_value = json.dumps({
            "levels": [{"name": "Beginner", "topics": ["basics"], "estimated_hours": 10}],
            "total_hours": 10,
        })
        path = structure_learning_path("python", [])
        assert len(path["levels"]) == 1
        assert path["total_hours"] == 10

    @patch("services.learn_service._chat_completion")
    def test_invalid_json_fallback(self, mock_llm):
        from services.learn_service import structure_learning_path
        mock_llm.return_value = "not json at all"
        path = structure_learning_path("python", [])
        assert len(path["levels"]) == 3
        assert path["total_hours"] == 60

    @patch("services.learn_service._chat_completion")
    def test_empty_llm(self, mock_llm):
        from services.learn_service import structure_learning_path
        mock_llm.return_value = ""
        path = structure_learning_path("python", [])
        # Empty LLM → no valid data → empty path (caller shows error)
        assert path["levels"] == []
        assert path["total_hours"] == 0


class TestCurateResources:
    @patch("services.learn_service._chat_completion")
    def test_llm_success(self, mock_llm):
        from services.learn_service import curate_resources
        mock_llm.return_value = "**Python Learning Path**\nStart with basics."
        result = curate_resources("python", [], {"levels": [], "total_hours": 0})
        assert "Python Learning Path" in result

    @patch("services.learn_service._chat_completion")
    def test_llm_empty_fallback(self, mock_llm):
        from services.learn_service import curate_resources
        mock_llm.return_value = ""
        result = curate_resources("python", [
            {"title": "Docs", "url": "https://docs.python.org"}
        ], {"levels": [{"name": "Beginner", "topics": ["basics"], "estimated_hours": 10}], "total_hours": 10})
        assert "Learning Path: python" in result
        assert "Docs" in result


# ══════════════════════════════════════════════════════════════════
# graph/nodes.py — classify_intent
# ══════════════════════════════════════════════════════════════════

class TestClassifyIntent:
    def _make_state(self, raw_input, thread_messages=None):
        return {
            "raw_input": raw_input,
            "thread_messages": thread_messages or [],
            "command_type": "",
        }

    def test_empty_input_no_thread(self):
        from graph.nodes import classify_intent
        state = self._make_state("")
        result = classify_intent(state)
        assert result["command_type"] == "help"

    def test_empty_input_with_thread(self):
        from graph.nodes import classify_intent
        state = self._make_state("", thread_messages=[{"user": "U1", "text": "hi"}])
        result = classify_intent(state)
        assert result["command_type"] == "context"
        assert result["needs_llm"] is True

    def test_test_llm(self):
        from graph.nodes import classify_intent
        state = self._make_state("test")
        result = classify_intent(state)
        assert result["command_type"] == "test_llm"

    def test_test_llm_variant(self):
        from graph.nodes import classify_intent
        state = self._make_state("test llm")
        result = classify_intent(state)
        assert result["command_type"] == "test_llm"

    def test_learn_command(self):
        from graph.nodes import classify_intent
        state = self._make_state("learn python async")
        result = classify_intent(state)
        assert result["command_type"] == "learn"
        assert result["learn_topic"] == "python async"

    def test_codereview_command(self):
        from graph.nodes import classify_intent
        state = self._make_state("codereview fmhy/edit#5758")
        result = classify_intent(state)
        assert result["command_type"] == "codereview"

    def test_summarize_keyword(self):
        from graph.nodes import classify_intent
        state = self._make_state("summarize")
        result = classify_intent(state)
        assert result["command_type"] == "context"
        assert result["needs_llm"] is True

    def test_reminder_r_flag(self):
        from graph.nodes import classify_intent
        state = self._make_state('-r "task" @30m')
        result = classify_intent(state)
        assert result["command_type"] == "reminder"

    def test_remind_keyword(self):
        from graph.nodes import classify_intent
        state = self._make_state("remind me to call mom @1h")
        result = classify_intent(state)
        assert result["command_type"] == "reminder"

    def test_latest_issues(self):
        from graph.nodes import classify_intent
        state = self._make_state("latest issues")
        result = classify_intent(state)
        assert result["command_type"] == "latest_github"

    def test_latest_prs(self):
        from graph.nodes import classify_intent
        state = self._make_state("recent prs")
        result = classify_intent(state)
        assert result["command_type"] == "latest_github"

    def test_greeting(self):
        from graph.nodes import classify_intent
        state = self._make_state("hey")
        result = classify_intent(state)
        assert result["command_type"] == "greeting"

    def test_github_ref(self):
        from graph.nodes import classify_intent
        state = self._make_state("fmhy/edit#5758")
        result = classify_intent(state)
        assert result["command_type"] == "github"

    def test_bare_number_goes_to_chat(self):
        """Bare #123 should NOT match github (no default repo)."""
        from graph.nodes import classify_intent
        state = self._make_state("#123")
        result = classify_intent(state)
        assert result["command_type"] == "chat"

    def test_thread_messages_fallback(self):
        from graph.nodes import classify_intent
        state = self._make_state(
            "some random text",
            thread_messages=[{"user": "U1", "text": "hi"}],
        )
        result = classify_intent(state)
        assert result["command_type"] == "context"

    def test_default_is_chat(self):
        from graph.nodes import classify_intent
        state = self._make_state("what is the meaning of life")
        result = classify_intent(state)
        assert result["command_type"] == "chat"

    def test_learn_case_insensitive(self):
        from graph.nodes import classify_intent
        state = self._make_state("LEARN Python")
        result = classify_intent(state)
        assert result["command_type"] == "learn"
        assert result["learn_topic"] == "Python"

    def test_codereview_case_insensitive(self):
        from graph.nodes import classify_intent
        state = self._make_state("CodeReview owner/repo#1")
        result = classify_intent(state)
        assert result["command_type"] == "codereview"

    def test_codereview_typo_coderview(self):
        from graph.nodes import classify_intent
        state = self._make_state("coderview owner/repo#123")
        result = classify_intent(state)
        assert result["command_type"] == "codereview"

    def test_codereview_alias_review(self):
        from graph.nodes import classify_intent
        state = self._make_state("review owner/repo#123")
        result = classify_intent(state)
        assert result["command_type"] == "codereview"

    def test_codereview_alias_pr(self):
        from graph.nodes import classify_intent
        state = self._make_state("pr owner/repo#456")
        result = classify_intent(state)
        assert result["command_type"] == "codereview"

    def test_learn_alias(self):
        from graph.nodes import classify_intent
        state = self._make_state("learn python")
        result = classify_intent(state)
        assert result["command_type"] == "learn"

    def test_github_pr_url_goes_to_codereview(self):
        from graph.nodes import classify_intent
        state = self._make_state("https://github.com/fmhy/edit/pull/5758")
        result = classify_intent(state)
        assert result["command_type"] == "codereview"

    def test_github_issue_url_goes_to_github(self):
        from graph.nodes import classify_intent
        state = self._make_state("https://github.com/fmhy/edit/issues/42")
        result = classify_intent(state)
        assert result["command_type"] == "github"

    def test_github_pr_url_with_text(self):
        from graph.nodes import classify_intent
        state = self._make_state("review this PR https://github.com/fmhy/edit/pull/100")
        result = classify_intent(state)
        assert result["command_type"] == "codereview"

    def test_hollow_promise_not_triggered(self):
        """With new persona, bot should never say 'I'll check' in chat."""
        from graph.nodes import classify_intent
        state = self._make_state("can you review my code")
        result = classify_intent(state)
        # Goes to chat — persona prevents hollow promises
        assert result["command_type"] == "chat"


class TestClassifyIntentSummarizeRegex:
    """Test the loose summar* regex catches all variations."""

    def _make_state(self, raw_input):
        return {"raw_input": raw_input, "thread_messages": [], "command_type": ""}

    def test_exact_summarize(self):
        from graph.nodes import classify_intent
        result = classify_intent(self._make_state("summarize"))
        assert result["command_type"] == "context"

    def test_summarise_british(self):
        from graph.nodes import classify_intent
        result = classify_intent(self._make_state("summarise this thread"))
        assert result["command_type"] == "context"

    def test_summarize_with_trailing_words(self):
        from graph.nodes import classify_intent
        result = classify_intent(self._make_state("summarize last 6 messages"))
        assert result["command_type"] == "context"

    def test_summarize_of_channel(self):
        from graph.nodes import classify_intent
        result = classify_intent(self._make_state("summarize the channel"))
        assert result["command_type"] == "context"

    def test_summarize_between_users(self):
        from graph.nodes import classify_intent
        result = classify_intent(self._make_state("summarize between @user1 and @user2"))
        assert result["command_type"] == "context"

    def test_typo_summraise(self):
        from graph.nodes import classify_intent
        result = classify_intent(self._make_state("summraise this"))
        assert result["command_type"] == "context"

    def test_summary_noun(self):
        from graph.nodes import classify_intent
        result = classify_intent(self._make_state("give me a summary"))
        assert result["command_type"] == "context"

    def test_summed_not_matched(self):
        """'summed' is not summarize-related."""
        from graph.nodes import classify_intent
        result = classify_intent(self._make_state("the bill was summed up"))
        assert result["command_type"] == "chat"


# ══════════════════════════════════════════════════════════════════
# graph/workflow.py
# ══════════════════════════════════════════════════════════════════

class TestRouteAfterClassification:
    def test_all_routes(self):
        from graph.workflow import route_after_classification
        cases = {
            "reminder": "parse_reminder",
            "github": "extract_github",
            "latest_github": "fetch_latest",
            "context": "summarize",
            "help": "help_response",
            "greeting": "greeting_response",
            "chat": "chat_response",
            "test_llm": "test_llm",
            "learn": "learn_research",
            "codereview": "codereview_fetch",
        }
        for cmd, expected in cases.items():
            assert route_after_classification({"command_type": cmd}) == expected

    def test_unknown_defaults_to_help(self):
        from graph.workflow import route_after_classification
        assert route_after_classification({"command_type": "unknown"}) == "help_response"


class TestRouteCodereview:
    def test_error_skips_subagents(self):
        from graph.workflow import route_codereview
        state = {"response_message": "Could not fetch PR data."}
        result = route_codereview(state)
        assert result == ["codereview_response"]

    def test_no_error_runs_subagents(self):
        from graph.workflow import route_codereview
        state = {"response_message": ""}
        result = route_codereview(state)
        assert "codereview_security" in result
        assert "codereview_performance" in result
        assert "codereview_best_practices" in result


# ══════════════════════════════════════════════════════════════════
# services/slack_summarize_service.py
# ══════════════════════════════════════════════════════════════════

class TestSummarizeSlack:
    def test_no_token(self):
        from services.slack_summarize_service import summarize_slack
        with patch("services.slack_summarize_service.SLACK_BOT_TOKEN", None):
            result = summarize_slack("C123")
            assert result["error"] != ""

    @patch("services.slack_summarize_service._fetch_via_mcp")
    @patch("services.slack_summarize_service._fetch_direct")
    def test_mcp_success(self, mock_direct, mock_mcp):
        from services.slack_summarize_service import summarize_slack
        mock_mcp.return_value = json.dumps({
            "messages": [{"user": "U1", "text": "hello", "ts": "1"}],
            "count": 1,
            "has_more": False,
        })
        result = summarize_slack("C123")
        assert result["summary"] != ""
        assert result["error"] == ""
        mock_direct.assert_not_called()

    @patch("services.slack_summarize_service._fetch_via_mcp")
    @patch("services.slack_summarize_service._fetch_direct")
    def test_falls_back_to_direct(self, mock_direct, mock_mcp):
        from services.slack_summarize_service import summarize_slack
        mock_mcp.return_value = None
        mock_direct.return_value = json.dumps({
            "messages": [{"user": "U1", "text": "hi", "ts": "1"}],
            "count": 1,
            "has_more": False,
        })
        result = summarize_slack("C123")
        assert result["summary"] != ""
        mock_direct.assert_called_once()

    @patch("services.slack_summarize_service._fetch_via_mcp")
    @patch("services.slack_summarize_service._fetch_direct")
    def test_overflow_warning(self, mock_direct, mock_mcp):
        from services.slack_summarize_service import summarize_slack
        msgs = [{"user": "U1", "text": f"msg{i}", "ts": str(i)} for i in range(30)]
        mock_mcp.return_value = json.dumps({
            "messages": msgs,
            "count": 30,
            "has_more": True,
        })
        result = summarize_slack("C123")
        assert "More than" in result["warning"]

    def test_parse_error(self):
        from services.slack_summarize_service import summarize_slack
        with patch("services.slack_summarize_service._fetch_via_mcp", return_value="not json"):
            with patch("services.slack_summarize_service._fetch_direct", return_value=None):
                result = summarize_slack("C123")
                assert "parse" in result["error"].lower() or result["error"] != ""

    @patch("services.slack_summarize_service._fetch_via_mcp")
    def test_slack_error_response(self, mock_mcp):
        from services.slack_summarize_service import summarize_slack
        mock_mcp.return_value = json.dumps({"error": "missing_scope"})
        result = summarize_slack("C123")
        assert "missing_scope" in result["error"]


class TestFetchDirectOverfetch:
    def test_fetches_more_than_max(self):
        """Verify _fetch_direct requests limit+10 to buffer filtered bot messages."""
        mock_client = MagicMock()
        mock_resp = MagicMock()
        msgs = [{"user": "U1", "text": f"msg{i}", "ts": str(i)} for i in range(35)]
        mock_resp.get = lambda key, default=None: msgs if key == "messages" else default
        mock_client.conversations_history.return_value = mock_resp

        # Patch WebClient where it's imported from
        with patch("slack_sdk.WebClient", return_value=mock_client):
            with patch("services.slack_summarize_service.is_real_message", return_value=True):
                from services.slack_summarize_service import _fetch_direct
                result = json.loads(_fetch_direct("C123"))
                call_kwargs = mock_client.conversations_history.call_args[1]
                assert call_kwargs["limit"] == 35  # 25 + 10


# ══════════════════════════════════════════════════════════════════
# services/reminder_service.py
# ══════════════════════════════════════════════════════════════════

class TestReminderService:
    @patch("services.reminder_service.scheduler")
    def test_schedule_reminder(self, mock_scheduler):
        from services.reminder_service import schedule_reminder, _ensure_scheduler
        _ensure_scheduler._scheduler_started = False
        schedule_reminder("U1", "Call mom", 1800, "C123")
        mock_scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler.add_job.call_args
        assert call_kwargs[1]["args"] == ["U1", "Call mom", "C123"]

    @patch("services.reminder_service.scheduler")
    def test_shutdown(self, mock_scheduler):
        from services.reminder_service import shutdown_scheduler
        import services.reminder_service as rs
        rs._scheduler_started = True
        shutdown_scheduler()
        mock_scheduler.shutdown.assert_called_once_with(wait=False)
        assert rs._scheduler_started is False


# ══════════════════════════════════════════════════════════════════
# services/mcp_slack_server.py — _is_real_message + _collect
# ══════════════════════════════════════════════════════════════════

class TestMcpSlackServer:
    def test_is_real_message_matches_shared(self):
        from services.mcp_slack_server import _is_real_message
        from handlers.shared import is_real_message as shared_filter
        # Should agree on core cases
        test_msgs = [
            {"text": "hello", "user": "U1"},
            {"bot_id": "B1", "text": "hi", "user": "U1"},
            {"subtype": "bot_message", "text": "hi", "user": "U1"},
            {"subtype": "bot_add", "text": "hi", "user": "U1"},
            {"text": "", "user": "U1"},
            {"text": "   ", "user": "U1"},
        ]
        for msg in test_msgs:
            assert _is_real_message(msg) == shared_filter(msg), f"Mismatch on {msg}"

    def test_collect_reverses_order(self):
        from services.mcp_slack_server import _collect
        resp = {
            "messages": [
                {"user": "U1", "text": "newest", "ts": "2"},
                {"user": "U2", "text": "oldest", "ts": "1"},
            ],
            "has_more": False,
        }
        result = _collect(resp, limit=10)
        # Slack returns newest-first; _collect reverses to oldest-first
        assert result["messages"][0]["text"] == "oldest"
        assert result["messages"][1]["text"] == "newest"

    def test_collect_filters_bots(self):
        from services.mcp_slack_server import _collect
        resp = {
            "messages": [
                {"user": "U1", "text": "human", "ts": "1"},
                {"bot_id": "B1", "text": "bot msg", "ts": "2"},
                {"user": "U2", "text": "human 2", "ts": "3"},
            ],
            "has_more": True,
        }
        result = _collect(resp, limit=10)
        assert result["count"] == 2
        assert result["has_more"] is True


# ══════════════════════════════════════════════════════════════════
# graph/nodes.py — specific node functions
# ══════════════════════════════════════════════════════════════════

class TestCodereviewFetch:
    def test_no_ref_shows_error(self):
        from graph.nodes import codereview_fetch
        state = {"raw_input": "codereview", "response_message": ""}
        result = codereview_fetch(state)
        assert "Could not parse" in result["response_message"]

    def test_no_repo_shows_error(self):
        from graph.nodes import codereview_fetch
        state = {"raw_input": "codereview #123", "response_message": ""}
        result = codereview_fetch(state)
        assert "Could not parse" in result["response_message"]

    @patch("graph.nodes.fetch_pr_diff")
    def test_unknown_pr_shows_error(self, mock_fetch):
        from graph.nodes import codereview_fetch
        mock_fetch.return_value = {"title": "Unknown PR", "body": "", "state": "unknown", "files": []}
        state = {"raw_input": "codereview fmhy/edit#99999", "response_message": ""}
        result = codereview_fetch(state)
        assert "Could not fetch PR" in result["response_message"]

    def test_bare_repo_shows_actionable_error(self):
        from graph.nodes import codereview_fetch
        state = {"raw_input": "codereview fmhy/edit", "response_message": ""}
        result = codereview_fetch(state)
        assert "fmhy/edit" in result["response_message"]
        assert "not a specific PR" in result["response_message"]
        assert "latest prs" in result["response_message"]

    def test_bare_url_shows_actionable_error(self):
        from graph.nodes import codereview_fetch
        state = {"raw_input": "codereview https://github.com/fmhy/edit", "response_message": ""}
        result = codereview_fetch(state)
        assert "fmhy/edit" in result["response_message"]
        assert "not a specific PR" in result["response_message"]


class TestLearnResearch:
    def test_empty_topic_shows_error(self):
        from graph.nodes import learn_research
        state = {"raw_input": "learn", "learn_topic": "", "response_message": ""}
        result = learn_research(state)
        assert "specify a topic" in result["response_message"]


class TestCodereviewMerge:
    @patch("graph.nodes.merge_reviews")
    def test_merge_sets_response(self, mock_merge):
        from graph.nodes import codereview_merge
        mock_merge.return_value = "Merged review"
        state = {
            "review_security": "sec",
            "review_performance": "perf",
            "review_best_practices": "bp",
            "review_pr_data": {"title": "PR"},
            "response_message": "",
        }
        result = codereview_merge(state)
        assert result["response_message"] == "Merged review"


class TestCodereviewResponse:
    def test_sets_default_if_empty(self):
        from graph.nodes import codereview_response
        state = {"response_message": ""}
        result = codereview_response(state)
        assert "Code review completed" in result["response_message"]

    def test_keeps_existing(self):
        from graph.nodes import codereview_response
        state = {"response_message": "Custom review output"}
        result = codereview_response(state)
        assert result["response_message"] == "Custom review output"


# ══════════════════════════════════════════════════════════════════
# Integration: full graph invoke (mocked LLM + GitHub)
# ══════════════════════════════════════════════════════════════════

class TestGraphIntegration:
    def _make_state(self, **overrides):
        from handlers.shared import build_initial_state
        state = build_initial_state(
            user_id="U1", channel_id="C1", message_ts="1.1",
            raw_input=overrides.get("raw_input", ""),
            thread_messages=overrides.get("thread_messages", []),
        )
        state.update(overrides)
        return state

    @patch("services.llm_service._chat_completion", return_value="LLM says hi")
    def test_greeting_goes_through_graph(self, mock_llm):
        from graph.workflow import sab_graph
        state = self._make_state(raw_input="hey")
        result = sab_graph.invoke(state)
        assert result["command_type"] == "greeting"
        assert result["response_message"] != ""

    @patch("graph.nodes.fetch_pr_diff")
    @patch("graph.nodes.review_best_practices", return_value="BP review")
    @patch("graph.nodes.review_performance", return_value="Perf review")
    @patch("graph.nodes.review_security", return_value="Sec review")
    def test_codereview_error_skips_subagents(
        self, mock_sec, mock_perf, mock_bp, mock_fetch
    ):
        from graph.workflow import sab_graph
        mock_fetch.return_value = {"title": "Unknown PR", "body": "", "state": "unknown", "files": []}
        state = self._make_state(raw_input="codereview fmhy/edit#99999")
        result = sab_graph.invoke(state)
        # Should have error, subagents should NOT have been called
        assert "Could not fetch" in result["response_message"]
        mock_sec.assert_not_called()
        mock_perf.assert_not_called()
        mock_bp.assert_not_called()

    @patch("services.slack_summarize_service.summarize_slack")
    def test_summarize_empty_channel(self, mock_summarize):
        from graph.workflow import sab_graph
        mock_summarize.return_value = {
            "summary": "No messages to summarize.",
            "warning": "",
            "error": "Could not fetch messages.",
        }
        state = self._make_state(raw_input="", thread_messages=[])
        result = sab_graph.invoke(state)
        assert result["response_message"] != ""


# ══════════════════════════════════════════════════════════════════
# v2.1: Risk score, footer, learn_via_mcp, LLM provider, features
# ══════════════════════════════════════════════════════════════════

class TestMdToSlackMrkdwn:
    def test_bold_conversion(self):
        from handlers.shared import md_to_slack_mrkdwn
        assert md_to_slack_mrkdwn("**bold**") == "*bold*"

    def test_underscore_bold_conversion(self):
        from handlers.shared import md_to_slack_mrkdwn
        assert md_to_slack_mrkdwn("__bold__") == "*bold*"

    def test_link_conversion(self):
        from handlers.shared import md_to_slack_mrkdwn
        assert md_to_slack_mrkdwn("[text](https://example.com)") == "<https://example.com|text>"

    def test_bare_url_wrapped(self):
        from handlers.shared import md_to_slack_mrkdwn
        result = md_to_slack_mrkdwn("Visit https://example.com for info")
        assert "<https://example.com>" in result
        assert "https://example.com" not in result.replace("<https://example.com>", "")

    def test_already_wrapped_url_not_double_wrapped(self):
        from handlers.shared import md_to_slack_mrkdwn
        assert md_to_slack_mrkdwn("<https://example.com>") == "<https://example.com>"

    def test_empty_text(self):
        from handlers.shared import md_to_slack_mrkdwn
        assert md_to_slack_mrkdwn("") == ""
        assert md_to_slack_mrkdwn(None) is None


class TestBuildInitialStateSearchFields:
    def test_action_token_default(self):
        from handlers.shared import build_initial_state
        state = build_initial_state(user_id="U1", channel_id="C1", message_ts="1", raw_input="hi")
        assert state["action_token"] == ""
        assert state["search_query"] == ""

    def test_action_token_passed(self):
        from handlers.shared import build_initial_state
        state = build_initial_state(user_id="U1", channel_id="C1", message_ts="1", raw_input="hi", action_token="tok123")
        assert state["action_token"] == "tok123"


class TestSearchRouting:
    def test_search_route(self):
        from graph.workflow import route_after_classification
        assert route_after_classification({"command_type": "search"}) == "search"

    def test_search_in_routes(self):
        from graph.workflow import route_after_classification
        assert route_after_classification({"command_type": "digest"}) == "digest"
        assert route_after_classification({"command_type": "duplicate"}) == "duplicate_check"
        assert route_after_classification({"command_type": "release_notes"}) == "release_notes"


class TestSearchNode:
    def test_empty_query_shows_usage(self):
        from graph.nodes import search_node
        state = {"search_query": "", "action_token": "", "response_message": ""}
        result = search_node(state)
        assert "Usage" in result["response_message"]

    @patch("services.slack_search_service.search_slack_context")
    def test_error_returns_error(self, mock_search):
        from graph.nodes import search_node
        mock_search.return_value = {"error": "missing_scope: search:read"}
        state = {"search_query": "deployment", "action_token": "tok", "response_message": ""}
        result = search_node(state)
        assert "missing_scope" in result["response_message"]

    @patch("services.slack_search_service.summarize_search_results", return_value="Found 3 results")
    @patch("services.slack_search_service.search_slack_context")
    def test_success_returns_summary(self, mock_search, mock_summarize):
        from graph.nodes import search_node
        mock_search.return_value = {"messages": [{"text": "msg1"}, {"text": "msg2"}]}
        state = {"search_query": "deployment", "action_token": "tok", "response_message": ""}
        result = search_node(state)
        assert result["response_message"] == "Found 3 results"


class TestDigestNode:
    def test_subscribe(self):
        from graph.nodes import digest_node
        state = {"raw_input": "digest subscribe", "channel_id": "C1", "response_message": ""}
        with patch("services.reminder_service.schedule_daily_digest"):
            result = digest_node(state)
            assert "subscribed" in result["response_message"].lower()

    def test_unsubscribe(self):
        from graph.nodes import digest_node
        state = {"raw_input": "digest unsubscribe", "channel_id": "C1", "response_message": ""}
        with patch("services.reminder_service.cancel_daily_digest", return_value=True):
            result = digest_node(state)
            assert "cancelled" in result["response_message"].lower()

    def test_usage(self):
        from graph.nodes import digest_node
        state = {"raw_input": "digest", "channel_id": "C1", "response_message": ""}
        result = digest_node(state)
        assert "Usage" in result["response_message"]


class TestDuplicateCheckNode:
    def test_no_ref_shows_usage(self):
        from graph.nodes import duplicate_check_node
        state = {"raw_input": "duplicate", "response_message": ""}
        result = duplicate_check_node(state)
        assert "Usage" in result["response_message"]

    def test_no_title_shows_usage(self):
        from graph.nodes import duplicate_check_node
        state = {"raw_input": "duplicate owner/repo", "response_message": ""}
        result = duplicate_check_node(state)
        assert "Usage" in result["response_message"]

    @patch("graph.nodes.find_similar_issues")
    def test_no_matches(self, mock_find):
        from graph.nodes import duplicate_check_node
        mock_find.return_value = []
        state = {'raw_input': 'duplicate owner/repo "fix login"', "response_message": ""}
        result = duplicate_check_node(state)
        assert "No likely duplicates" in result["response_message"]

    @patch("graph.nodes.find_similar_issues")
    def test_matches_found(self, mock_find):
        from graph.nodes import duplicate_check_node
        mock_find.return_value = [{"score": 0.87, "title": "Fix login", "url": "http://1", "number": 42}]
        state = {'raw_input': 'duplicate owner/repo "fix login"', "response_message": ""}
        result = duplicate_check_node(state)
        assert "87%" in result["response_message"]


class TestReleaseNotesNode:
    def test_no_repo_shows_usage(self):
        from graph.nodes import release_notes_node
        state = {"raw_input": "release notes", "response_message": ""}
        result = release_notes_node(state)
        assert "Usage" in result["response_message"]

    @patch("services.release_service.generate_release_notes", return_value="## Features\n- New thing")
    def test_generates_notes(self, mock_gen):
        from graph.nodes import release_notes_node
        state = {"raw_input": "release notes owner/repo", "response_message": ""}
        result = release_notes_node(state)
        assert "Features" in result["response_message"]


class TestRiskScore:
    def test_high_risk_past_200_chars(self):
        from services.codereview_service import _risk_score
        text = "x" * 300 + "Risk Level: High"
        assert _risk_score(text) == "🔴 High"

    def test_semgrep_error_is_high(self):
        from services.codereview_service import _risk_score
        findings = [{"severity": "ERROR"}]
        assert _risk_score("no issues", findings) == "🔴 High"

    def test_low_default(self):
        from services.codereview_service import _risk_score
        assert _risk_score("Risk Level: Low") == "🟢 Low"

    def test_medium_with_semgrep_warning(self):
        from services.codereview_service import _risk_score
        findings = [{"severity": "WARNING"}]
        assert _risk_score("no issues", findings) == "🟡 Medium"

    def test_medium_in_text(self):
        from services.codereview_service import _risk_score
        text = "x" * 300 + "Risk Level: Medium"
        assert _risk_score(text) == "🟡 Medium"


class TestMergeReviewsFormatting:
    def test_footer_no_double_underscore(self):
        from services.codereview_service import merge_reviews
        out = merge_reviews("sec", "perf", "best", {"title": "T"}, via_mcp=True)
        assert "via GitHub MCP" in out
        assert "__" not in out


class TestCodereviewLLMFailure:
    def test_warning_on_all_fallbacks(self):
        from services.codereview_service import (
            merge_reviews, _FALLBACK_SECURITY, _FALLBACK_PERFORMANCE, _FALLBACK_BEST,
        )
        out = merge_reviews(
            _FALLBACK_SECURITY, _FALLBACK_PERFORMANCE, _FALLBACK_BEST,
            {"title": "T", "files": []},
        )
        assert "LLM unavailable" in out


class TestLearnViaMcp:
    @patch("graph.nodes.research_topic")
    def test_flag_stored_in_state(self, mock_research):
        from graph.nodes import learn_research
        mock_research.return_value = {"resources": [], "search_via_mcp": True}
        state = {"learn_topic": "python", "response_message": ""}
        result = learn_research(state)
        assert result["learn_via_mcp"] is True


class TestLLMProvider:
    @patch("services.llm_service._local_completion", return_value="")
    @patch("services.llm_service._gemini_completion", return_value="gemini ok")
    @patch("services.llm_service.LLM_PROVIDER", "local")
    @patch("services.llm_service.LLM_FALLBACK_ENABLED", True)
    @patch("services.llm_service.GOOGLE_API_KEY", "key")
    def test_cross_fallback_local_to_gemini(self, mock_gemini, mock_local):
        from services.llm_service import _chat_completion
        assert _chat_completion("hi") == "gemini ok"

    @patch("services.llm_service._local_completion", return_value="local ok")
    @patch("services.llm_service.LLM_PROVIDER", "local")
    def test_local_primary(self, mock_local):
        from services.llm_service import _chat_completion
        assert _chat_completion("hi") == "local ok"


class TestFindSimilarIssues:
    @patch("services.github_service.fetch_repo_issues")
    def test_finds_similar(self, mock_issues):
        from services.github_service import find_similar_issues
        mock_issues.return_value = [
            {"title": "Fix login bug on mobile", "url": "http://1", "number": 42},
            {"title": "Unrelated feature", "url": "http://2", "number": 43},
        ]
        results = find_similar_issues("owner/repo", "fix login bug mobile")
        assert len(results) >= 1
        assert results[0]["score"] >= 0.55


class TestFetchMergedPrs:
    @patch("services.github_service.requests.get")
    def test_filters_merged_only(self, mock_get):
        from services.github_service import fetch_merged_prs
        mock_get.return_value = MagicMock(
            status_code=200,
            headers={},
            json=lambda: [
                {"title": "Merged PR", "number": 1, "html_url": "http://1", "merged_at": "2026-01-01"},
                {"title": "Closed not merged", "number": 2, "html_url": "http://2", "merged_at": None},
            ],
        )
        results = fetch_merged_prs("owner/repo")
        assert len(results) == 1
        assert results[0]["title"] == "Merged PR"


class TestClassifyNewCommands:
    def _make_state(self, raw):
        from graph.nodes import classify_intent
        return classify_intent({
            "raw_input": raw, "thread_messages": [], "command_type": "help",
            "needs_llm": False, "learn_topic": "",
        })

    def test_digest(self):
        assert self._make_state("digest subscribe")["command_type"] == "digest"

    def test_duplicate(self):
        assert self._make_state('duplicate owner/repo "title"')["command_type"] == "duplicate"

    def test_release_notes(self):
        assert self._make_state("release notes owner/repo")["command_type"] == "release_notes"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
