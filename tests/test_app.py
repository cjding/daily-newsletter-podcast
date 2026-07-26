import base64
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from newsletter_podcast.app import DAILY_SECTIONS, MAX_SCRIPT_WORDS, Config, build_source, make_script, message_text, write_feed


def encoded(value):
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_message_text_prefers_plain_text():
    payload = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/plain", "body": {"data": encoded("Plain newsletter")}},
        {"mimeType": "text/html", "body": {"data": encoded("<b>HTML newsletter</b>")}},
    ]}
    assert message_text(payload) == "Plain newsletter"


def test_message_text_converts_html_and_removes_script():
    payload = {"mimeType": "text/html", "body": {"data": encoded("<h1>Headline</h1><script>bad()</script><p>Story</p>")}}
    assert "Headline" in message_text(payload)
    assert "Story" in message_text(payload)
    assert "bad" not in message_text(payload)


def test_build_source_includes_metadata_and_truncates():
    messages = [{"payload": {"headers": [
        {"name": "Subject", "value": "Morning News"}, {"name": "From", "value": "Editor"}
    ], "mimeType": "text/plain", "body": {"data": encoded("abcdefgh")}}}]
    source = build_source(messages, 4)
    assert "Subject: Morning News" in source
    assert "From: Editor" in source
    assert source.endswith("abcd")


def test_write_feed_prepends_new_episodes(tmp_path):
    episodes = tmp_path / "episodes"
    episodes.mkdir()
    for day in (1, 2):
        name = f"episodes/2026-01-0{day}.mp3"
        (tmp_path / name).write_bytes(b"audio")
        write_feed(tmp_path, "https://example.com", f"Episode {day}", "Summary", name,
                   datetime(2026, 1, day, tzinfo=timezone.utc))
    channel = ET.parse(tmp_path / "feed.xml").getroot().find("channel")
    assert channel.findall("item")[0].findtext("title") == "Episode 2"


class FakeResponses:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": next(self.outputs)})()


def config():
    return Config("id", "secret", "refresh", "key", "https://example.com", "me@example.com")


def test_script_prompt_has_stable_sections_and_duration_budget():
    responses = FakeResponses(["short script"])
    client = type("Client", (), {"responses": responses})()
    assert make_script(client, "newsletter", config()) == "short script"
    instructions = responses.calls[0]["instructions"]
    assert "1,400 and 1,750 words" in instructions
    assert all(section in instructions for section in DAILY_SECTIONS)
    assert "so what for you" in instructions
    assert "key risk" in instructions
    assert "political idea" in instructions
    assert config().interest_profile in instructions


def test_overlong_script_is_condensed():
    long_script = "word " * (MAX_SCRIPT_WORDS + 1)
    responses = FakeResponses([long_script, "condensed script"])
    client = type("Client", (), {"responses": responses})()
    assert make_script(client, "newsletter", config()) == "condensed script"
    assert len(responses.calls) == 2
