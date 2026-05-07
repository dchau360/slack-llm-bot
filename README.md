# Slack LLM Bot

Docker Compose deployment for a Slack bot that talks to any OpenAI-compatible LLM API endpoint.

The bot uses Slack Socket Mode, so the host running Docker does not need to expose an inbound HTTP webhook. It only needs outbound access to Slack and to your LLM endpoint.

## LLM API endpoint

Yes, `LLM_BASE_URL` is an OpenAI-compatible API base URL. The bot uses the OpenAI Python SDK, but the server does not have to be OpenAI. It can be LiteLLM, vLLM, llama.cpp server, Text Generation Inference behind an OpenAI-compatible proxy, Ollama behind LiteLLM, or any service that supports the OpenAI chat completions API.

Set `LLM_BASE_URL` to the API base path that ends in `/v1`, not the full completions route. The bot calls `/chat/completions` under that base URL.

Examples:

```env
LLM_BASE_URL=http://litellm:4000/v1
LLM_BASE_URL=http://vllm-host:8000/v1
LLM_BASE_URL=http://host.docker.internal:4000/v1
LLM_BASE_URL=http://your-llm-api-host:4000/v1
```

## Features

- Responds in channels and threads when explicitly mentioned.
- Responds to normal direct messages.
- Summarizes a Slack thread privately when you DM the bot a Slack thread link.
- Uses `users:read` to resolve Slack user IDs into display names before sending thread context to the LLM.
- Avoids duplicate replies when both `app_mention` and generic `message.*` events are enabled.
- Does not auto-reply to regular channel/thread conversation unless explicitly configured.

## Repository layout

```text
.
├── .env.example
├── .gitignore
├── README.md
├── docker-compose.yml
├── bot
│   ├── .dockerignore
│   ├── Dockerfile
│   ├── app.py
│   └── requirements.txt
└── slack
    └── app-manifest.yml
```

## Slack app setup

You can create the Slack app either manually or from the included manifest.

### Option A: use the manifest

1. Go to <https://api.slack.com/apps>.
2. Click **Create New App**.
3. Choose **From an app manifest**.
4. Select your workspace.
5. Paste the contents of:

```text
slack/app-manifest.yml
```

6. Create the app.
7. Go to **OAuth & Permissions** and install/reinstall the app to the workspace.

The manifest includes these bot scopes:

```text
app_mentions:read
channels:history
chat:write
groups:history
im:history
mpim:history
users:read
```

The manifest includes these bot events:

```text
app_mention
message.im
```

### Option B: configure manually

Create an app at <https://api.slack.com/apps>, then configure the following.

Under **OAuth & Permissions**, add bot token scopes:

```text
app_mentions:read
chat:write
channels:history
im:history
users:read
```

For private channel thread links, also add:

```text
groups:history
```

For group DMs, also add:

```text
mpim:history
```

Under **App Home**, enable:

```text
Messages Tab
Allow users to send Slash commands and messages from the messages tab
```

The exact label can vary in Slack’s UI. The important part is that users can DM the app.

Under **Socket Mode**, enable Socket Mode.

Under **Event Subscriptions**, enable events and add bot events:

```text
app_mention
message.im
```

Do not add these unless you want passive thread follow-up behavior:

```text
message.channels
message.groups
message.mpim
```

After any scope or event change, go back to **OAuth & Permissions** and click **Reinstall to Workspace**.

## Slack tokens

This bot needs two Slack tokens.

### Bot token

Find this under:

```text
OAuth & Permissions -> Bot User OAuth Token
```

It starts with:

```text
xoxb-
```

Use it as:

```env
SLACK_BOT_TOKEN=xoxb-...
```

### App-level Socket Mode token

Find or create this under:

```text
Basic Information -> App-Level Tokens -> Generate Token and Scopes
```

Add this scope:

```text
connections:write
```

It starts with:

```text
xapp-
```

Use it as:

```env
SLACK_APP_TOKEN=xapp-...
```

The `xapp-` token and `xoxb-` token must come from the same Slack app.

## Configure environment

Copy the example file:

```bash
cp .env.example .env
```

Edit `.env`:

```env
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

BOT_NAME=llm-bot
LOG_LEVEL=INFO

LLM_BASE_URL=http://your-llm-api-host:4000/v1
LLM_API_KEY=sk-local
LLM_MODEL=your-model-name
LLM_TEMPERATURE=0.2

MAX_THREAD_MESSAGES=50
MAX_RESPONSE_TOKENS=1600
RESPOND_TO_THREAD_FOLLOWUPS=false
ENABLE_DM_THREAD_LINK_SUMMARY=true
```

Set `LLM_MODEL` to the model name or alias exposed by your OpenAI-compatible LLM API.

## Deploy with Docker Compose

Build and start:

```bash
docker compose up -d --build
```

Watch logs:

```bash
docker compose logs -f slack-llm-bot
```

Expected startup logs:

```text
starting llm-bot as bot_user_id=... team=... model=... base_url=...
A new session has been established
Bolt app is running
```

Restart after editing `.env`:

```bash
docker compose down
docker compose up -d
```

Rebuild after editing Python or Dockerfile files:

```bash
docker compose down
docker compose build --no-cache slack-llm-bot
docker compose up -d
```

## Test the LLM endpoint

Run this from inside the bot container:

```bash
docker compose exec -T slack-llm-bot python - <<'PY'
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.environ["LLM_BASE_URL"],
    api_key=os.environ.get("LLM_API_KEY", "sk-local"),
)

resp = client.chat.completions.create(
    model=os.environ["LLM_MODEL"],
    messages=[{"role": "user", "content": "reply with ok"}],
    max_tokens=16,
)
print(resp.choices[0].message.content)
PY
```

Expected result:

```text
ok
```

## Test Slack API access

Check the bot token:

```bash
docker compose exec -T slack-llm-bot python - <<'PY'
import os
from slack_sdk import WebClient

client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
print(client.auth_test())
PY
```

Manually post to a channel:

```bash
docker compose exec -T slack-llm-bot python - <<'PY'
import os
from slack_sdk import WebClient

channel = "C0B1VQSJCG3"
client = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
print(client.chat_postMessage(channel=channel, text="manual post test from llm-bot"))
PY
```

Replace `C0B1VQSJCG3` with your channel ID.

## Invite the bot

In the Slack channel:

```text
/invite @llm-bot
```

Then test:

```text
@llm-bot hi
```

Use Slack autocomplete and select the bot so the message is a real mention, not plain text.

## Behavior

### Channel or thread mention

The bot responds when explicitly mentioned:

```text
@llm-bot summarize this thread
```

If the mention is inside a thread, the bot replies in the same thread.

### Regular channel messages

With the default:

```env
RESPOND_TO_THREAD_FOLLOWUPS=false
```

The bot ignores regular channel and thread conversation.

### Direct messages

The bot responds to normal DMs:

```text
hi, what model are you using?
```

Slack requirements:

```text
App Home Messages Tab enabled
message.im event
chat:write
im:history
```

### Private thread summaries

DM the bot a Slack thread permalink:

```text
summarize this: https://your-workspace.slack.com/archives/C1234567890/p1714410000000000?thread_ts=1714410000.000000&cid=C1234567890
```

The bot fetches the linked thread and replies in the DM, not in the source channel.

The bot must have access to the source channel. For private channels, invite the bot and grant `groups:history`.

## Optional thread follow-ups

If you want the bot to respond to follow-up messages in a thread after it was mentioned once:

```env
RESPOND_TO_THREAD_FOLLOWUPS=true
```

Then add the relevant Slack bot event:

```text
message.channels
```

For private channels:

```text
message.groups
```

This can be noisy. The recommended default is:

```env
RESPOND_TO_THREAD_FOLLOWUPS=false
```

## Troubleshooting

### Bot is running but no Slack response

Check logs:

```bash
docker compose logs -f slack-llm-bot
```

If there is no log when you mention the bot, Slack is not delivering events. Check:

```text
Socket Mode enabled
SLACK_APP_TOKEN starts with xapp-
SLACK_APP_TOKEN has connections:write
SLACK_BOT_TOKEN starts with xoxb-
app_mention is under Subscribe to bot events
App was reinstalled after scope/event changes
Bot is invited to the channel
```

### Bot responds twice

Remove these events unless you need follow-ups:

```text
message.channels
message.groups
```

The code also ignores generic message events that directly mention the bot to avoid duplicate replies.

### Bot does not respond to DMs

Check:

```text
App Home Messages Tab enabled
message.im bot event added
im:history scope added
chat:write scope added
App reinstalled after changes
```

### User IDs show up instead of names

Make sure this scope is present:

```text
users:read
```

Then reinstall the Slack app. The bot resolves user IDs using Slack user profile data and caches names in memory.

### Container cannot reach the LLM

Check:

```bash
docker compose exec -T slack-llm-bot env | grep LLM
```

Then run the LLM test command above. If DNS fails from Docker, use an address resolvable from inside the container or run with host networking if appropriate for your environment.
