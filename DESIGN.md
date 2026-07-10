# Slack Action Bot - MCP Integration & New Commands Design

## Overview

Add two new commands (`/learn` and `/codereview`) with MCP (Model Context Protocol) server integration for extensible tool access.

## Current Architecture

```
Slack → main.py → handlers/commands.py → graph/workflow.py → nodes.py → services/
                                    ↓
                              sab_graph.invoke()
```

## MCP Integration Approach

### Why MCP?

- **Standardized**: Any MCP server works with any MCP client
- **Extensible**: Add new tools without code changes
- **FOSS**: Many open-source MCP servers available (GitHub, filesystem, web search, etc.)

### Integration Strategy

Use the **MCP Python SDK** (`mcp`) to connect to local MCP servers as tool providers in LangGraph nodes.

```
LangGraph Node → MCP Client → MCP Server → External API
```

### Available FOSS MCP Servers

| Server | Purpose | Use Case |
|--------|---------|----------|
| `@modelcontextprotocol/server-github` | GitHub API | /codereview, PR analysis |
| `@modelcontextprotocol/server-fetch` | Web fetching | /learn research |
| `@modelcontextprotocol/server-filesystem` | File access | Local code review |
| `@modelcontextprotocol/server-memory` | Knowledge graph | Learning context |

## New Commands

### 1. `/learn <topic>`

**Purpose**: Help users learn anything by creating a personalized learning path.

**Flow**:
```
/learn python async programming
    ↓
┌─────────────────────────────────────┐
│ 1. Research Agent                   │
│    - Fetch web resources via MCP    │
│    - Search documentation           │
│    - Find tutorials & examples      │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 2. Structure Agent                  │
│    - Organize by skill level        │
│    - Create learning path           │
│    - Estimate time commitment       │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ 3. Resource Agent                   │
│    - Curate best resources          │
│    - Include hands-on projects      │
│    - Add practice exercises         │
└─────────────────────────────────────┘
    ↓
Response: Structured learning path
```

**LangGraph Implementation**:
```python
# New nodes
"learn_research" → "learn_structure" → "learn_resources" → "learn_response"

# State additions
class BotState(TypedDict):
    learn_topic: str
    learn_resources: list[dict]
    learn_path: list[dict]
    learn_level: str  # beginner, intermediate, advanced
```

**MCP Tools Used**:
- `fetch` - Get web content from documentation
- `github` - Find example repos and code

### 2. `/codereview <owner/repo> or <pr-url>`

**Purpose**: Fan out 3 subagents to review code from different perspectives.

**Flow**:
```
/codereview owner/repo#123
    ↓
┌─────────────────────────────────────┐
│ Fetch PR diff via GitHub MCP        │
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ │ Security    │ │ Performance │ │ Best        │
│ │ Reviewer    │ │ Reviewer    │ │ Practices   │
│ │             │ │             │ │ Reviewer    │
│ └─────────────┘ └─────────────┘ └─────────────┘
└─────────────────────────────────────┘
    ↓
┌─────────────────────────────────────┐
│ Merge & Format Response             │
└─────────────────────────────────────┘
    ↓
Response: Consolidated review with suggestions
```

**LangGraph Implementation**:
```python
# New nodes
"codereview_fetch" → fan_out → [
    "codereview_security",
    "codereview_performance", 
    "codereview_best_practices"
] → "codereview_merge" → "codereview_response"

# State additions
class BotState(TypedDict):
    review_pr_url: str
    review_diff: str
    review_security: str
    review_performance: str
    review_best_practices: str
    review_merged: str
```

**MCP Tools Used**:
- `github` - Fetch PR details and diff
- `filesystem` - Read local code if needed

**Subagent Prompts**:

1. **Security Reviewer**:
   - Check for SQL injection, XSS, CSRF
   - Review authentication/authorization
   - Identify hardcoded secrets
   - Flag insecure dependencies

2. **Performance Reviewer**:
   - Identify N+1 queries
   - Check for memory leaks
   - Review algorithm complexity
   - Flag unnecessary API calls

3. **Best Practices Reviewer**:
   - Code style consistency
   - Error handling patterns
   - Documentation coverage
   - Test coverage suggestions

## Implementation Plan

### Phase 1: MCP Client Setup

```python
# services/mcp_client.py
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

class MCPClient:
    def __init__(self):
        self.sessions = {}
    
    async def connect(self, server_name: str, command: str, args: list):
        """Connect to an MCP server"""
        params = StdioServerParameters(command=command, args=args)
        # ... connection logic
    
    async def call_tool(self, server_name: str, tool_name: str, args: dict):
        """Call a tool on an MCP server"""
        # ... tool call logic
```

### Phase 2: New Service Files

```
services/
├── mcp_client.py          # MCP client wrapper
├── learn_service.py       # /learn logic
└── codereview_service.py  # /codereview logic
```

### Phase 3: New Nodes

```python
# graph/nodes.py additions

def classify_intent(state: BotState) -> BotState:
    # Add new intents
    if re.match(r'^learn\b', raw_lower):
        state["command_type"] = "learn"
        return state
    
    if re.match(r'^codereview\b', raw_lower):
        state["command_type"] = "codereview"
        return state

def learn_research(state: BotState) -> BotState:
    """Research the topic using MCP tools"""
    # ... implementation

def codereview_fetch(state: BotState) -> BotState:
    """Fetch PR diff via GitHub MCP"""
    # ... implementation

def codereview_security(state: BotState) -> BotState:
    """Security review subagent"""
    # ... implementation
```

### Phase 4: Workflow Updates

```python
# graph/workflow.py additions

def build_graph() -> CompiledStateGraph:
    g = StateGraph(BotState)
    
    # Existing nodes...
    
    # New learn nodes
    g.add_node("learn_research", learn_research)
    g.add_node("learn_structure", learn_structure)
    g.add_node("learn_resources", learn_resources)
    g.add_node("learn_response", learn_response)
    
    # New codereview nodes
    g.add_node("codereview_fetch", codereview_fetch)
    g.add_node("codereview_security", codereview_security)
    g.add_node("codereview_performance", codereview_performance)
    g.add_node("codereview_best_practices", codereview_best_practices)
    g.add_node("codereview_merge", codereview_merge)
    g.add_node("codereview_response", codereview_response)
    
    # Routing
    g.add_conditional_edges("classify", route_after_classification, {
        # ... existing routes
        "learn": "learn_research",
        "codereview": "codereview_fetch",
    })
    
    # Learn flow
    g.add_edge("learn_research", "learn_structure")
    g.add_edge("learn_structure", "learn_resources")
    g.add_edge("learn_resources", "learn_response")
    g.add_edge("learn_response", END)
    
    # Codereview flow (fan-out)
    g.add_edge("codereview_fetch", "codereview_security")
    g.add_edge("codereview_fetch", "codereview_performance")
    g.add_edge("codereview_fetch", "codereview_best_practices")
    g.add_edge("codereview_security", "codereview_merge")
    g.add_edge("codereview_performance", "codereview_merge")
    g.add_edge("codereview_best_practices", "codereview_merge")
    g.add_edge("codereview_merge", "codereview_response")
    g.add_edge("codereview_response", END)
    
    return g.compile()
```

## Dependencies to Add

```toml
# pyproject.toml
dependencies = [
    # ... existing
    "mcp>=1.0.0",
    "anyio>=4.0.0",
]
```

## Environment Variables

```env
# .env
GITHUB_TOKEN=ghp_...
MCP_GITHUB_SERVER=true
MCP_FETCH_SERVER=true
```

## Testing

### /learn Test Cases

```bash
/sab learn python async programming
/sab learn machine learning basics
/sab learn kubernetes deployment
```

Expected: Structured learning path with resources, time estimates, and skill levels.

### /codereview Test Cases

```bash
/sab codereview owner/repo#123
/sab codereview https://github.com/owner/repo/pull/123
/sab codereview #456
```

Expected: Three-section review (security, performance, best practices) with actionable suggestions.

## Success Criteria

1. `/learn` returns structured learning path with 3+ resources
2. `/codereview` returns three distinct review perspectives
3. Both commands complete within 30 seconds
4. MCP servers can be swapped without code changes
5. Graceful fallback if MCP server unavailable

## Future Extensions

- Add more MCP servers (Slack, Jira, Linear)
- Add `/compare` command for diff analysis
- Add `/document` command for auto-documentation
- Persistent learning progress via MCP memory server
