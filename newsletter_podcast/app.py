from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
   
]

DAILY_SECTIONS = (
    "Opening headlines",
    "Key stories, takeaways, and common themes",
    "Why this matters to you",
    "Top world events",
    "Daily political concept",
    "Daily finance and investment idea",
    "Closing recap",
)
MIN_SCRIPT_WORDS = 1_000
MAX_SCRIPT_WORDS = 1_200


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1
        elif tag in {"p", "br", "div", "h1", "h2", "h3", "li"}:
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.text.append(data)


def html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return "".join(parser.text)


@dataclass(frozen=True)
class Config:
    gmail_client_id: str
    gmail_client_secret: str
    gmail_refresh_token: str
    openai_api_key: str
    podcast_base_url: str
    delivery_email: str
    gmail_label: str = "daily newsletter"
    processed_label: str = "podcast/processed"
    summary_model: str = "gpt-4.1-mini"
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "coral"
    podcast_language: str = "en"
    interest_profile: str = "technology, global affairs, business, finance, and lifelong learning"
    max_source_chars: int = 12_000
    dry_run: bool = False

    @classmethod
    def from_env(cls) -> "Config":
        required = [
            "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
            "OPENAI_API_KEY", "PODCAST_BASE_URL", "DELIVERY_EMAIL",
        ]
        missing = [key for key in required if not os.getenv(key)]
        if missing:
            raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
        return cls(
            gmail_client_id=os.environ["GMAIL_CLIENT_ID"],
            gmail_client_secret=os.environ["GMAIL_CLIENT_SECRET"],
            gmail_refresh_token=os.environ["GMAIL_REFRESH_TOKEN"],
            openai_api_key=os.environ["OPENAI_API_KEY"],
            podcast_base_url=os.environ["PODCAST_BASE_URL"].rstrip("/"),
            delivery_email=os.environ["DELIVERY_EMAIL"],
            gmail_label=os.getenv("GMAIL_LABEL", "daily newsletter"),
            processed_label=os.getenv("PROCESSED_LABEL", "podcast/processed"),
            summary_model=os.getenv("SUMMARY_MODEL", "gpt-4.1-mini"),
            tts_model=os.getenv("TTS_MODEL", "gpt-4o-mini-tts"),
            tts_voice=os.getenv("TTS_VOICE", "coral"),
            podcast_language=os.getenv("PODCAST_LANGUAGE", "en"),
            interest_profile=os.getenv(
                "INTEREST_PROFILE",
                "technology, global affairs, business, finance, and lifelong learning",
            ),
            max_source_chars=int(os.getenv("MAX_SOURCE_CHARS", "12000")),
            dry_run=os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"},
        )


def decode_part(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")


def message_text(payload: dict) -> str:
    """Extract user-visible text, preferring text/plain over HTML."""
    plain, rich = [], []

    def visit(part: dict) -> None:
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime in {"text/plain", "text/html"}:
            value = decode_part(data)
            (plain if mime == "text/plain" else rich).append(value)
        for child in part.get("parts", []):
            visit(child)

    visit(payload)
    text = "\n".join(plain)
    if not text and rich:
        text = html_to_text("\n".join(rich))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def header(payload: dict, name: str) -> str:
    return next((h["value"] for h in payload.get("headers", []) if h["name"].lower() == name.lower()), "")


def ensure_label(service, name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    match = next((item for item in labels if item["name"].lower() == name.lower()), None)
    if match:
        return match["id"]
    return service.users().labels().create(
        userId="me", body={"name": name, "labelListVisibility": "labelShow"}
    ).execute()["id"]


def fetch_messages(service, source_label: str, processed_label: str, limit: int = 50) -> list[dict]:
    query = f'label:"{source_label}" -label:"{processed_label}" newer_than:2d'
    refs = service.users().messages().list(userId="me", q=query, maxResults=limit).execute().get("messages", [])
    return [service.users().messages().get(userId="me", id=item["id"], format="full").execute() for item in refs]


def build_source(messages: list[dict], max_chars: int) -> str:
    sections = []
    for index, message in enumerate(messages, 1):
        payload = message["payload"]
        body = message_text(payload)[:max_chars]
        sections.append(
            f"NEWSLETTER {index}\nSubject: {header(payload, 'Subject')}\n"
            f"From: {header(payload, 'From')}\nDate: {header(payload, 'Date')}\n\n{body}"
        )
    return "\n\n---\n\n".join(sections)


def make_script(client, source: str, config: Config) -> str:
    section_list = "; ".join(DAILY_SECTIONS)
    response = client.responses.create(
        model=config.summary_model,
        instructions=(
            "You are the host of a private daily news podcast. Write between 1,000 and 1,200 words, "
"which targets a consistent 8–10 minute episode, stays below the speech API's 2,000-token "
"input limit, and keeps the episode under 15 minutes at a "
"measured speaking pace. "
            f"Create the briefing in {config.podcast_language}. Prioritize consequential news, merge duplicate "
            "stories, explicitly identify themes that recur across multiple newsletters, name the newsletter "
            "source, and distinguish facts from "
            "the newsletter author's opinion. Never invent details. Do not use markdown, URLs, stage "
            "directions, or a references section. Always use these spoken sections in this order: "
            f"{section_list}. The listener's stated interests and growth goals are: {config.interest_profile}. "
            "For every key story or cross-newsletter theme, include a distinct 'so what for you' that ties "
            "the item to those interests and gives a concrete way to advance the listener's knowledge or "
            "skills. In Top world events, summarize the most important global developments present in the "
            "source material; clearly say when the newsletters do not provide enough coverage for a complete "
            "world update. In Daily political concept, teach one relevant, reusable political idea, define it "
            "in plain language, and connect it to a sourced story. In Daily finance and investment idea, give "
            "one educational, actionable idea supported by the newsletters, including its rationale, key risk, "
            "counterargument, and what evidence to monitor; label it as educational information rather than "
            "personalized financial advice. Use a brief spoken transition to introduce every section. When "
            "source material is limited, keep a section concise rather than padding or inventing information."
        ),
        input=source,
    )
    script = response.output_text.strip()
    if len(script.split()) <= MAX_SCRIPT_WORDS:
        return script

    # A second pass corrects the initial model response when it
    # ignores the requested word budget. It is intentionally only used for an
    # overlong script: sparse newsletters should not be padded with speculation.
    condensed = client.responses.create(
        model=config.summary_model,
        instructions=(
            f"Condense this podcast script to {MIN_SCRIPT_WORDS}–{MAX_SCRIPT_WORDS} words without "
            "adding facts or removing source attribution. Preserve all seven spoken sections and "
            "their order. Return only the revised narration, with no markdown."
        ),
        input=script,
    )
    return condensed.output_text.strip()


def write_feed(public: Path, base_url: str, title: str, description: str, audio_name: str, now: datetime) -> None:
    feed_path = public / "feed.xml"
    if feed_path.exists():
        root = ET.parse(feed_path).getroot()
        channel = root.find("channel")
        assert channel is not None
    else:
        root = ET.Element("rss", {"version": "2.0", "xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"})
        channel = ET.SubElement(root, "channel")
        for tag, value in (("title", "My Daily Newsletter Podcast"), ("link", base_url),
                           ("description", "A private daily briefing from my newsletters."),
                           ("language", "en")):
            ET.SubElement(channel, tag).text = value
    item = ET.Element("item")
    url = f"{base_url}/{audio_name}"
    for tag, value in (("title", title), ("description", description), ("guid", url),
                       ("pubDate", now.strftime("%a, %d %b %Y %H:%M:%S +0000"))):
        ET.SubElement(item, tag).text = value
    size = str((public / audio_name).stat().st_size)
    ET.SubElement(item, "enclosure", {"url": url, "length": size, "type": "audio/mpeg"})
    first_item = channel.find("item")
    channel.insert(list(channel).index(first_item) if first_item is not None else len(channel), item)
    ET.indent(root)
    ET.ElementTree(root).write(feed_path, encoding="utf-8", xml_declaration=True)


def send_delivery(service, recipient: str, title: str, url: str, count: int) -> None:
    message = EmailMessage()
    message["To"] = recipient
    message["From"] = "me"
    message["Subject"] = title
    message.set_content(f"Your briefing from {count} newsletter(s) is ready:\n\n{url}\n")
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()


def main() -> None:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from openai import OpenAI

    config = Config.from_env()
    credentials = Credentials(
        token=None, refresh_token=config.gmail_refresh_token,
        token_uri="https://oauth2.googleapis.com/token", client_id=config.gmail_client_id,
        client_secret=config.gmail_client_secret, scopes=GMAIL_SCOPES,
    )
    gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    messages = fetch_messages(gmail, config.gmail_label, config.processed_label)
    if not messages:
        print("No new newsletters; nothing to publish.")
        return

    client = OpenAI(api_key=config.openai_api_key)
    script = make_script(client, build_source(messages, config.max_source_chars), config)
    if config.dry_run:
        print(script)
        return

    now = datetime.now(timezone.utc)
    audio_name = f"episodes/{now:%Y-%m-%d}.mp3"
    public = Path("public")
    (public / "episodes").mkdir(parents=True, exist_ok=True)
    with client.audio.speech.with_streaming_response.create(
        model=config.tts_model, voice=config.tts_voice, input=script,
        instructions="Warm, clear morning news host; measured pace and neutral tone.",
    ) as response:
        response.stream_to_file(public / audio_name)

    title = f"Daily Briefing — {now:%B %-d, %Y}"
    write_feed(public, config.podcast_base_url, title, script[:500], audio_name, now)
    url = f"{config.podcast_base_url}/{audio_name}"
    send_delivery(gmail, config.delivery_email, title, url, len(messages))
    processed_id = ensure_label(gmail, config.processed_label)
    gmail.users().messages().batchModify(
        userId="me", body={"ids": [item["id"] for item in messages], "addLabelIds": [processed_id]}
    ).execute()
    print(f"Published {url} from {len(messages)} newsletter(s).")
