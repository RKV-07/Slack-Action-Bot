# Slack Advanced Actions Bot - 7-Day Sprint Plan

## What You're Actually Building

NOT: "Full GitHub integration with persistent reminders"
YES: "Smart action bot that contextualizes mentions and sets reminders"

---

## Day 1: Setup & Context Feature (3 hrs)

### Tasks
- [ ] Create Slack workspace
- [ ] Create Slack app, get tokens
- [ ] Set up Python environment + slack-bolt

### Feature: Action Context Capture
- [ ] Build `/sab` command that works in message threads
- [ ] Extract: Who mentioned you? What was the original message?
- [ ] Ask user: "Summarize this action?" or "Just remind me?"
- [ ] Post back with context

**Code structure:**
```python
@app.command("/sab")
def handle_sab(ack, command, client, logger):
    ack()
    
    # Get original message context
    message_ts = command.get("thread_ts", command.get("trigger_id"))
    
    # Fetch message from channel
    msg_response = client.conversations_history(
        channel=command["channel_id"],
        latest=message_ts,
        limit=1
    )
    
    # Ask user what they want
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": "What do you want to do?"}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Summarize & Remind"},
                "value": "summarize", "action_id": "sab_summarize"},
            {"type": "button", "text": {"type": "plain_text", "text": "Just Set Reminder"},
                "value": "remind", "action_id": "sab_remind"}
        ]}
    ]
    
    client.chat_postMessage(
        channel=command["channel_id"],
        blocks=blocks
    )
```

**Demo:** User replies /sab in a thread mentioning them, bot asks what to do.

---

## Day 2: Reminders Feature (4 hrs)

### Feature: /sab -r "text" @30m
- [ ] Parse command: `/sab -r "Check this bug" @30m`
- [ ] Extract time (30m, 1h, etc.)
- [ ] Store in simple dict (won't persist, but works for demo)
- [ ] Use APScheduler to send DM reminder

**Code structure:**
```python
from apscheduler.schedulers.background import BackgroundScheduler
import re

scheduler = BackgroundScheduler()
scheduler.start()

@app.command("/sab")
def handle_sab(ack, command, client, logger):
    ack()
    
    text = command["text"]
    user_id = command["user_id"]
    
    # Parse: /sab -r "text" @time
    if "-r" in text:
        match = re.search(r'-r\s"([^"]+)"\s@(\d+)([mh])', text)
        if match:
            reminder_text = match.group(1)
            time_value = int(match.group(2))
            time_unit = match.group(3)  # 'm' or 'h'
            
            # Convert to seconds
            delay_seconds = time_value * 60 if time_unit == 'm' else time_value * 3600
            
            # Schedule reminder
            scheduler.add_job(
                send_reminder,
                'date',
                run_date=datetime.now() + timedelta(seconds=delay_seconds),
                args=[client, user_id, reminder_text]
            )
            
            client.chat_postMessage(
                channel=command["channel_id"],
                text=f"✓ Reminder set: '{reminder_text}' in {time_value}{time_unit}"
            )

def send_reminder(client, user_id, text):
    client.chat_postMessage(
        channel=user_id,  # DM to user
        text=f"🔔 Reminder: {text}"
    )
```

**Demo:** User types `/sab -r "Check the bug in prod" @30m`, bot confirms, sends DM after 30 mins.

---

## Day 3: GitHub Lookup (Lightweight) (4 hrs)

### Feature: Simple Issue/PR link detection
- [ ] User mentions: "Check issue #123" or "PR owner/repo#456"
- [ ] Bot auto-detects & fetches from GitHub API
- [ ] Posts: Issue title, state (open/closed), link

**Code structure:**
```python
import requests

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # Personal access token

@app.message(r"(#\d+|[\w-]+/[\w-]+#\d+)")
def handle_github_mention(message, say, logger):
    """Auto-detect GitHub issue/PR references"""
    
    text = message["text"]
    
    # Match: #123 or owner/repo#456
    matches = re.findall(r'([\w-]+/[\w-]+)?#(\d+)', text)
    
    for match in matches:
        repo = match[0] or "your-default-repo"  # Default if not specified
        issue_num = match[1]
        
        # Fetch from GitHub
        url = f"https://api.github.com/repos/{repo}/issues/{issue_num}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"}
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                issue = response.json()
                
                blocks = [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{issue['title']}*\nStatus: {issue['state']}\n<{issue['html_url']}|View on GitHub>"
                        }
                    }
                ]
                
                say(blocks=blocks)
        except Exception as e:
            logger.error(f"GitHub lookup failed: {e}")
```

**Demo:** User mentions `#42` or `my-org/repo#99`, bot automatically fetches and posts details.

---

## Day 4: Mention Detection + Polish (3 hrs)

### Feature: Auto-suggest /sab when mentioned
- [ ] Listen for @admin or @user mentions in channels
- [ ] Post: "Hey @user, you were mentioned. Use /sab to review this action."
- [ ] Link original message

**Code structure:**
```python
@app.event("app_mention")
def handle_app_mention(event, say, client, logger):
    """Respond to mentions with action suggestion"""
    
    user_id = event["user"]
    channel_id = event["channel"]
    
    # Fetch context
    msg_response = client.conversations_history(
        channel=channel_id,
        latest=event["ts"],
        limit=1
    )
    
    original_msg = msg_response["messages"][0]["text"]
    
    say(f"Hi <@{user_id}>! Someone mentioned you about: \n> {original_msg}\n\nReply with `/sab` to handle this action.")
```

**Polish tasks:**
- [ ] Error handling (missing tokens, API failures)
- [ ] Test all features in real Slack
- [ ] Add emoji feedback (✓ done, 🔔 reminder set, etc.)

---

## Day 5: Demo Recording (2–3 hrs)

### Record a 3-minute demo showing:

1. **Segment 1: Action Context (30 secs)**
   - Someone mentions you in a thread
   - You type `/sab`
   - Bot shows context + asks what to do

2. **Segment 2: Reminders (1 min)**
   - Type `/sab -r "Check the production bug" @5m`
   - Bot confirms
   - Wait 5 mins or fast-forward
   - Show DM reminder arrives

3. **Segment 3: GitHub Lookup (1 min)**
   - User mentions "#42" in channel
   - Bot auto-detects and posts issue title + link
   - User mentions "my-org/repo#99"
   - Bot posts PR details

4. **Segment 4: Mention Detection (30 secs)**
   - Someone types "@admin check this out"
   - Bot replies suggesting `/sab`

**Keep it raw:** No editing, no fancy transitions. Just show it working.

---

## Day 6: Docs + Diagram (2 hrs)

### Feature Description
```
Slack Advanced Actions Bot (SAB):
Transform how your team handles distributed work across Slack and GitHub.

What it does:
• /sab - Instantly capture context when you're mentioned (who pinged you? what's the action?)
• /sab -r "task" @30m - Set smart reminders linked to original messages
• Auto-detects GitHub issues/PRs (#123, org/repo#456) and fetches live status
• Suggests /sab when you're mentioned, so you never miss an action

Why it matters:
Teams lose 30% of their productivity context-switching between Slack, email, and GitHub. 
SAB keeps everything in Slack with smart reminders and auto-linked issues.

Built with: Slack Bolt API, GitHub API, APScheduler, Gemini for context awareness
```

### Architecture Diagram
```
User mentions you in Slack
        ↓
    Bot detects mention
        ↓
   /sab command triggers
        ↓
   ┌─────────────────┐
   │ 3 possible flows │
   └─────────────────┘
        ↓
   ┌────────┬──────────┬───────────┐
   ↓        ↓          ↓           ↓
Summarize Remind GH Lookup Mention Detection
   ↓        ↓          ↓           ↓
Gemini  APScheduler  GH API   Auto-suggest
```

---

## Day 7: Final Test + Submit (1–2 hrs)

- [ ] Test all features one more time
- [ ] Check for crashes, weird messages
- [ ] Verify demo video is watchable
- [ ] Submit to Devpost with:
  - Demo video link
  - Feature description
  - Architecture diagram
  - Slack workspace (judges can test)
  - Code link (GitHub)

---

## What to CUT if you're behind:

1. **GitHub auto-detection** — Keep only manual lookup (user types /sab gh:owner/repo#123)
2. **Mention detection** — Not critical, demo without it
3. **Persistent reminders** — In-memory is fine for hackathon (no database)
4. **Gemini summarization** — Keep basic text, add Gemini only if time

---

## Your winning angle for judges:

**Problem:** Teams waste 2+ hours/day context-switching between Slack and GitHub.

**Solution:** One bot, three features:
1. Action context (who pinged me? what's the ask?)
2. Smart reminders (never miss a task)
3. GitHub link (see live issue status without leaving Slack)

**Impact:** 30+ min/day saved per person = $5K+ annual value for a 20-person team.

**Why it's unique:** Not just a summarizer. It's a workflow orchestrator. Combines mention detection + reminders + GitHub awareness.

---

## Risk mitigation:

If you hit Wednesday and realize reminders are too complex:
- Switch to simpler version: /sab save "text" (just saves message, no scheduling)
- Still shows you understand state management
- Still ships

If GitHub API fails:
- Keep manual lookup only: /sab gh owner/repo#123
- Still shows you can integrate external APIs

The core idea is solid. The execution is paced. You've got this.
