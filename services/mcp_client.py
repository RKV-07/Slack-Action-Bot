"""
MCP Client - Wrapper for Model Context Protocol servers.

Provides sync interface for LangGraph nodes to call MCP tools.
Uses AsyncExitStack for proper resource management.
"""

import asyncio
import concurrent.futures
import threading
from typing import Any, Optional
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


_CONNECT_TIMEOUT = 90
_CALL_TIMEOUT = 20


class MCPClient:
    """Sync wrapper for MCP client sessions."""

    def __init__(self):
        self._sessions: dict[str, ClientSession] = {}
        self._exit_stacks: dict[str, AsyncExitStack] = {}
        self._tools_cache: dict[str, list] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _ensure_loop(self):
        """Ensure background event loop is running (thread-safe)."""
        with self._lock:
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
                self._thread.start()

    def _run_async(self, coro, timeout=_CALL_TIMEOUT):
        """Run async coroutine in background loop with timeout."""
        self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            print(f"[MCP] Operation timed out after {timeout}s")
            return f"Error: MCP operation timed out after {timeout}s"
        except Exception as e:
            print(f"[MCP] Error: {e}")
            return f"Error: {e}"

    async def _connect_server(self, name: str, command: str, args: list[str], env: dict = None):
        """Connect to an MCP server using AsyncExitStack."""
        exit_stack = AsyncExitStack()
        await exit_stack.__aenter__()
        self._exit_stacks[name] = exit_stack

        params = StdioServerParameters(command=command, args=args, env=env)
        read_stream, write_stream = await exit_stack.enter_async_context(stdio_client(params))
        session = await exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()
        self._sessions[name] = session
        print(f"[MCP] Connected to {name}")

    async def _disconnect_server(self, name: str):
        """Disconnect from an MCP server."""
        if name in self._exit_stacks:
            await self._exit_stacks[name].__aexit__(None, None, None)
            del self._exit_stacks[name]
            if name in self._sessions:
                del self._sessions[name]
            print(f"[MCP] Disconnected from {name}")

    async def _list_tools(self, name: str) -> list:
        """List available tools from a server."""
        if name not in self._tools_cache:
            session = self._sessions.get(name)
            if session:
                result = await session.list_tools()
                self._tools_cache[name] = [
                    {"name": t.name, "description": t.description, "schema": t.inputSchema}
                    for t in result.tools
                ]
        return self._tools_cache.get(name, [])

    async def _call_tool(self, name: str, tool_name: str, arguments: dict) -> str:
        """Call a tool on a server."""
        session = self._sessions.get(name)
        if not session:
            return f"Error: Server {name} not connected"
        result = await session.call_tool(tool_name, arguments)
        # Extract text from result content
        if hasattr(result, "content") and result.content:
            texts = []
            for item in result.content:
                if hasattr(item, "text"):
                    texts.append(item.text)
            return "\n".join(texts) if texts else str(result)
        return str(result)

    def connect(self, name: str, command: str, args: list[str], env: dict = None) -> bool:
        """Sync: Connect to an MCP server. Returns True if connected."""
        self._run_async(self._connect_server(name, command, args, env), timeout=_CONNECT_TIMEOUT)
        return name in self._sessions

    def disconnect(self, name: str):
        """Sync: Disconnect from an MCP server."""
        self._run_async(self._disconnect_server(name))

    def list_tools(self, name: str) -> list:
        """Sync: List tools from a server."""
        return self._run_async(self._list_tools(name))

    def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        """Sync: Call a tool on a server. Auto-evicts dead sessions."""
        result = self._run_async(self._call_tool(server_name, tool_name, arguments))
        if isinstance(result, str) and result.startswith("Error"):
            print(f"[MCP] Tool call failed for {server_name}, running health check...")
            if not self.health_check(server_name):
                print(f"[MCP] Session {server_name} is unhealthy, evicting...")
                self._evict_session(server_name)
        return result

    def _evict_session(self, name: str):
        """Forcefully evict a dead session."""
        try:
            self._run_async(self._disconnect_server(name))
        except Exception:
            pass
        self._sessions.pop(name, None)
        self._exit_stacks.pop(name, None)
        self._tools_cache.pop(name, None)
        print(f"[MCP] Evicted session: {name}")

    def health_check(self, name: str) -> bool:
        """Check if a session is alive by calling list_tools with a short timeout."""
        if name not in self._sessions:
            return False
        try:
            self._ensure_loop()
            future = asyncio.run_coroutine_threadsafe(self._list_tools(name), self._loop)
            future.result(timeout=5)
            return True
        except Exception:
            return False


# Global MCP client instance
mcp_client = MCPClient()


def setup_mcp_servers(github_token: str = None):
    """Initialize connections to available MCP servers."""
    try:
        # GitHub MCP Server
        env = {}
        if github_token:
            env["GITHUB_PERSONAL_ACCESS_TOKEN"] = github_token

        if mcp_client.connect(
            name="github",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-github"],
            env=env if env else None,
        ):
            print("[MCP] GitHub server ready")
        else:
            print("[MCP] GitHub server FAILED to connect within 90s")
    except Exception as e:
        print(f"[MCP] Failed to connect GitHub server: {e}")

    try:
        # Fetch MCP Server (Python-based, run with uvx)
        if mcp_client.connect(
            name="fetch",
            command="uvx",
            args=["mcp-server-fetch"],
        ):
            print("[MCP] Fetch server ready")
        else:
            print("[MCP] Fetch server FAILED to connect within 90s")
    except Exception as e:
        print(f"[MCP] Failed to connect fetch server: {e}")

    try:
        # Slack MCP Server (custom, in-repo; uses the bot token via slack-sdk)
        import os
        import sys

        from config import SLACK_BOT_TOKEN

        slack_server_path = os.path.join(os.path.dirname(__file__), "mcp_slack_server.py")
        env = {"SLACK_BOT_TOKEN": SLACK_BOT_TOKEN} if SLACK_BOT_TOKEN else None
        if mcp_client.connect(
            name="slack",
            command=sys.executable,
            args=[slack_server_path],
            env=env,
        ):
            print("[MCP] Slack server ready")
        else:
            print("[MCP] Slack server FAILED to connect within 90s")
    except Exception as e:
        print(f"[MCP] Failed to connect slack server: {e}")


def call_github_tool(tool_name: str, arguments: dict) -> str:
    """Convenience: Call a GitHub MCP tool."""
    try:
        return mcp_client.call_tool("github", tool_name, arguments)
    except Exception as e:
        print(f"[MCP] GitHub tool error: {e}")
        return f"Error calling GitHub tool: {e}"


def call_fetch_tool(tool_name: str, arguments: dict) -> str:
    """Convenience: Call a fetch MCP tool."""
    try:
        return mcp_client.call_tool("fetch", tool_name, arguments)
    except Exception as e:
        print(f"[MCP] Fetch tool error: {e}")
        return f"Error calling fetch tool: {e}"


def call_slack_tool(tool_name: str, arguments: dict) -> str:
    """Convenience: Call a Slack MCP tool."""
    try:
        return mcp_client.call_tool("slack", tool_name, arguments)
    except Exception as e:
        print(f"[MCP] Slack tool error: {e}")
        return f"Error calling Slack tool: {e}"
