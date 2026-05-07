import logging
import os
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from openai import OpenAI
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("slack-llm-bot")

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]

BOT_NAME = os.getenv("BOT_NAME", "local-llm")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://your-llm-api-host:4000/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "sk-local")
LLM_MODEL = os.getenv("LLM_MODEL", "local-chat")
LLM_TEMPERATURE = env_float("LLM_TEMPERATURE", 0.2)
MAX_THREAD_MESSAGES = env_int("MAX_THREAD_MESSAGES", 50)
MAX_RESPONSE_TOKENS = env_int("MAX_RESPONSE_TOKENS", 1600)
RESPOND_TO_THREAD_FOLLOWUPS = env_bool("RESPOND_TO_THREAD_FOLLOWUPS", False)
ENABLE_DM_THREAD_LINK_SUMMARY = env_bool("ENABLE_DM_THREAD_LINK_SUMMARY", True)

app = App(token=SLACK_BOT_TOKEN)
llm = OpenAI(base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
SLACK_LINK_RE = re.compile(r"<([^>|]+)\|([^>]+)>")
SLACK_ARCHIVE_URL_RE = re.compile(r"https://[^\s<>|]+/archives/[^\s<>|]+")
USER_NAME_CACHE: dict[str, str] = {}


def clean_slack_text(text: str) -> str:
    text = MENTION_RE.sub("", text or "")
    text = SLACK_LINK_RE.sub(r"\2 (\1)", text)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return text.strip()


def slackify_markdown(text: str) -> str:
    text = text or ""
    text = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"*\1*", text)
    return text.strip()


def extract_slack_archive_url(text: str) -> str | None:
    if not text:
        return None

    wrapped_matches = re.findall(r"<(https://[^>|]+/archives/[^>|]+)(?:\|[^>]+)?>", text)
    if wrapped_matches:
        return wrapped_matches[0]

    raw_match = SLACK_ARCHIVE_URL_RE.search(text)
    if raw_match:
        return raw_match.group(0).rstrip(".,)")

    return None


def slack_permalink_ts_from_p_segment(p_segment: str) -> str | None:
    digits = re.sub(r"\D", "", p_segment.removeprefix("p"))
    if len(digits) <= 6:
        return None
    return f"{digits[:-6]}.{digits[-6:]}"


def parse_slack_permalink(url: str) -> tuple[str, str, str] | None:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]

    try:
        archives_index = path_parts.index("archives")
        channel = path_parts[archives_index + 1]
        p_segment = path_parts[archives_index + 2]
    except (ValueError, IndexError):
        return None

    root_ts = slack_permalink_ts_from_p_segment(p_segment)
    if not root_ts:
        return None

    query = parse_qs(parsed.query)
    thread_ts = query.get("thread_ts", [root_ts])[0]
    return channel, thread_ts, root_ts


def user_display_name(client: Any, user_id: str) -> str:
    if user_id in USER_NAME_CACHE:
        return USER_NAME_CACHE[user_id]

    try:
        response = client.users_info(user=user_id)
        user = response.get("user", {})
        profile = user.get("profile", {})
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or user.get("real_name")
            or user.get("name")
            or user_id
        )
    except Exception:
        logger.exception("failed resolving Slack user %s", user_id)
        name = user_id

    USER_NAME_CACHE[user_id] = name
    return name


def message_author(client: Any, message: dict[str, Any]) -> str:
    if message.get("bot_id"):
        return BOT_NAME

    user_id = message.get("user")
    if user_id:
        return user_display_name(client, user_id)

    return message.get("username") or "unknown-user"


def get_thread_messages(client: Any, channel: str, thread_ts: str) -> list[dict[str, Any]]:
    response = client.conversations_replies(
        channel=channel,
        ts=thread_ts,
        limit=MAX_THREAD_MESSAGES,
    )
    return response.get("messages", [])


def build_thread_messages(client: Any, thread_messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are a helpful LLM assistant inside Slack. "
                "Use the Slack thread as context. Answer the latest user request directly. "
                "Be concise but complete. Use Slack-friendly formatting. "
                "If context is missing, say exactly what is missing."
            ),
        }
    ]

    transcript_lines: list[str] = []
    for message in thread_messages:
        subtype = message.get("subtype")
        if subtype in {"bot_message", "message_deleted", "message_changed"}:
            continue

        text = clean_slack_text(message.get("text", ""))
        if not text:
            continue

        transcript_lines.append(f"{message_author(client, message)}: {text}")

    messages.append(
        {
            "role": "user",
            "content": "Slack thread transcript:\n\n" + "\n\n".join(transcript_lines),
        }
    )
    return messages


def build_summary_messages(
    client: Any,
    thread_messages: list[dict[str, Any]],
    source_url: str,
) -> list[dict[str, str]]:
    messages = build_thread_messages(client, thread_messages)
    messages[0] = {
        "role": "system",
        "content": (
            "You are summarizing a Slack thread for a user who sent you a thread link in a private DM. "
            "Reply privately with a concise but useful summary. Include decisions, open questions, "
            "action items, owners if stated, and notable risks. If the thread is mostly noise or lacks "
            "enough context, say so."
        ),
    }
    messages.append(
        {
            "role": "user",
            "content": f"Summarize this linked Slack thread: {source_url}",
        }
    )
    return messages


def build_dm_messages(text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a helpful LLM assistant inside a private Slack DM. "
                "Answer the user directly. Be concise but complete. "
                "Use Slack-friendly formatting. If you need more context, ask for it."
            ),
        },
        {
            "role": "user",
            "content": clean_slack_text(text),
        },
    ]


def call_llm(messages: list[dict[str, str]]) -> str:
    logger.info("calling LLM model=%s base_url=%s", LLM_MODEL, LLM_BASE_URL)
    response = llm.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=LLM_TEMPERATURE,
        max_tokens=MAX_RESPONSE_TOKENS,
    )
    return response.choices[0].message.content or ""


def respond_to_thread(client: Any, say: Any, channel: str, thread_ts: str) -> None:
    thread_messages = get_thread_messages(client, channel, thread_ts)
    llm_messages = build_thread_messages(client, thread_messages)
    answer = slackify_markdown(call_llm(llm_messages))
    say(text=answer or "I did not get a usable response from the model.", thread_ts=thread_ts)


def respond_with_private_thread_summary(client: Any, say: Any, dm_channel: str, source_url: str) -> None:
    parsed = parse_slack_permalink(source_url)
    if not parsed:
        say(
            text="I found a Slack link, but I could not parse it. Send the full thread permalink from Slack's *Copy link* action.",
            channel=dm_channel,
        )
        return

    source_channel, thread_ts, _root_ts = parsed
    logger.info(
        "private thread summary source_channel=%s thread_ts=%s dm_channel=%s",
        source_channel,
        thread_ts,
        dm_channel,
    )

    try:
        thread_messages = get_thread_messages(client, source_channel, thread_ts)
    except Exception as exc:
        logger.exception("failed fetching linked Slack thread")
        say(
            text=(
                "I could not read that thread. Make sure I am invited to the source channel "
                "and have the right history scope. "
                f"Slack/API error: `{type(exc).__name__}: {exc}`"
            ),
            channel=dm_channel,
        )
        return

    llm_messages = build_summary_messages(client, thread_messages, source_url)
    answer = slackify_markdown(call_llm(llm_messages))
    say(text=answer or "I could not generate a summary for that thread.", channel=dm_channel)


def respond_to_dm(client: Any, say: Any, event: dict[str, Any]) -> None:
    dm_channel = event["channel"]
    text = event.get("text", "")

    if ENABLE_DM_THREAD_LINK_SUMMARY:
        source_url = extract_slack_archive_url(text)
        if source_url:
            respond_with_private_thread_summary(client, say, dm_channel, source_url)
            return

    cleaned = clean_slack_text(text)
    if not cleaned:
        say(text="Send me a question or a Slack thread link to summarize.", channel=dm_channel)
        return

    logger.info("dm message channel=%s", dm_channel)
    llm_messages = build_dm_messages(cleaned)
    answer = slackify_markdown(call_llm(llm_messages))
    say(text=answer or "I did not get a usable response from the model.", channel=dm_channel)


@app.event("app_mention")
def handle_app_mention(event: dict[str, Any], client: Any, say: Any) -> None:
    channel = event["channel"]
    thread_ts = event.get("thread_ts") or event["ts"]
    logger.info("app mention channel=%s thread_ts=%s", channel, thread_ts)

    try:
        respond_to_thread(client, say, channel, thread_ts)
    except Exception as exc:
        logger.exception("failed handling app_mention")
        say(text=f"`{BOT_NAME}` error: `{type(exc).__name__}: {exc}`", thread_ts=thread_ts)


@app.event("message")
def handle_message(event: dict[str, Any], client: Any, say: Any) -> None:
    if event.get("bot_id") or event.get("subtype"):
        return

    if event.get("channel_type") == "im":
        try:
            respond_to_dm(client, say, event)
        except Exception as exc:
            logger.exception("failed handling DM message")
            say(
                text=f"`{BOT_NAME}` error: `{type(exc).__name__}: {exc}`",
                channel=event["channel"],
            )
        return

    # Slack can deliver a direct bot mention as both an app_mention event and
    # a generic message.* event when message events are subscribed. Let
    # app_mention be the single path for explicit mentions to avoid duplicate
    # replies in threads.
    bot_user_id = app.client.auth_test()["user_id"]
    if f"<@{bot_user_id}>" in event.get("text", ""):
        return

    if not RESPOND_TO_THREAD_FOLLOWUPS:
        return

    if "thread_ts" not in event:
        return

    channel = event["channel"]
    thread_ts = event["thread_ts"]
    logger.info("thread follow-up channel=%s thread_ts=%s", channel, thread_ts)

    try:
        thread_messages = get_thread_messages(client, channel, thread_ts)
        bot_was_mentioned = any(
            message.get("text") and f"<@{bot_user_id}>" in message["text"]
            for message in thread_messages
        )
        if not bot_was_mentioned:
            return
        respond_to_thread(client, say, channel, thread_ts)
    except Exception:
        logger.exception("failed handling thread follow-up")


if __name__ == "__main__":
    auth = app.client.auth_test()
    logger.info(
        "starting %s as bot_user_id=%s team=%s model=%s base_url=%s",
        BOT_NAME,
        auth.get("user_id"),
        auth.get("team"),
        LLM_MODEL,
        LLM_BASE_URL,
    )
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
