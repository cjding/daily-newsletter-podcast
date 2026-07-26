# Daily Newsletter Podcast

Turn every Gmail message carrying the **daily newsletter** label into a private,
spoken morning briefing. A GitHub Actions schedule runs at **07:00 Korea Standard
Time (22:00 UTC)**, asks OpenAI for a concise script, creates an MP3, updates a
podcast RSS feed, and emails the episode link to you.

## What it does

1. Finds unread/unprocessed messages under a configurable Gmail label.
2. Extracts readable text from HTML and plain-text email bodies.
3. Produces one editorially ordered, roughly 11–14 minute briefing with source
   attribution and a 15-minute target ceiling.
4. Generates speech with OpenAI text-to-speech.
5. Publishes `public/feed.xml` and dated MP3 files through GitHub Pages.
6. Sends the episode link to the configured delivery address and marks the
   source messages with a processed label.

The workflow does nothing (and does not mark messages processed) when the inbox
query has no matching messages.

## Daily episode sections

Every episode follows the same listening-friendly structure:

1. **Opening headlines** — a welcome and quick preview.
2. **Key stories, takeaways, and common themes** — the most consequential
   reporting, with overlapping ideas across newsletters explicitly connected.
3. **Why this matters to you** — a distinct “so what” for every key story or
   theme, tied to your configured interests and a concrete knowledge or skill
   development opportunity.
4. **Top world events** — the most important global developments covered by the
   source newsletters, with an explicit coverage warning when the emails are
   insufficient for a complete world update.
5. **Daily political concept** — one reusable political idea, explained in plain
   language and applied to a story from that day's newsletters.
6. **Daily finance and investment idea** — one educational idea with rationale,
   risk, counterargument, and evidence to monitor. It is not personalized
   financial advice.
7. **Closing recap** — the key takeaways in a concise sign-off.

The generated script targets 1,400–1,750 words, normally about 11–14 minutes at
a measured news-reading pace. If the first draft exceeds the word ceiling, the
app automatically condenses it. A day with little source material may be shorter
rather than padded with invented or repetitive content.

## Where to listen

After the workflow publishes an episode, you can listen in either of these ways:

* Open the direct MP3 link sent to `DELIVERY_EMAIL` in a browser or audio app.
* Subscribe to `<PODCAST_BASE_URL>/feed.xml` in a podcast player that accepts a
  custom RSS URL. The newest episode will appear at the top of the feed.

For example, if `PODCAST_BASE_URL` is
`https://you.github.io/daily-newsletter-podcast`, the feed is
`https://you.github.io/daily-newsletter-podcast/feed.xml`, and individual audio
files are stored below `https://you.github.io/daily-newsletter-podcast/episodes/`.

## Setup

### 1. Create Gmail OAuth credentials

In Google Cloud, enable the Gmail API and create an OAuth **Desktop app**. Obtain
a refresh token authorized for these scopes:

```text
https://www.googleapis.com/auth/gmail.modify
https://www.googleapis.com/auth/gmail.send
```

The workflow uses a refresh token rather than storing an expiring access token.

### 2. Configure repository secrets and variables

Add these GitHub Actions secrets:

| Name | Purpose |
|---|---|
| `GMAIL_CLIENT_ID` | OAuth client ID |
| `GMAIL_CLIENT_SECRET` | OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | OAuth refresh token with the scopes above |
| `OPENAI_API_KEY` | OpenAI API key |

Add these repository **variables**:

| Name | Example | Purpose |
|---|---|---|
| `PODCAST_BASE_URL` | `https://you.github.io/daily-newsletter-podcast` | Public Pages URL, without trailing slash |
| `DELIVERY_EMAIL` | `you@example.com` | Address that receives each episode |
| `GMAIL_LABEL` | `daily newsletter` | Source label (optional) |
| `PROCESSED_LABEL` | `podcast/processed` | Completion label (optional) |
| `INTEREST_PROFILE` | `AI, geopolitics, leadership, investing` | Your interests, goals, and skills used to personalize each “so what” (optional) |

Set `INTEREST_PROFILE` as specifically as useful—for example, `AI product
management, Korean and US politics, long-term index investing, public speaking`.
The app uses this profile for relevance and learning suggestions; it does not
infer private interests from other Gmail messages.

Enable GitHub Pages with **GitHub Actions** as its source. Run the workflow once
manually from the Actions tab to validate credentials and publish the initial
feed. Subscribe to `https://…/feed.xml` in any podcast player if desired.

> GitHub Pages URLs are public. Do not use this publication method for sensitive
> newsletters. For private audio, replace the Pages deployment with private
> object storage and signed URLs.

## Local use

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
set -a; source .env; set +a
python -m newsletter_podcast
```

Set `DRY_RUN=true` to fetch and summarize without generating audio, sending mail,
changing Gmail labels, or writing the feed. Tests do not access external APIs:

```bash
pip install -r requirements-dev.txt
pytest
```

## Scheduling note

GitHub Actions cron schedules use UTC and may start a few minutes late during
busy periods. Korea does not observe daylight saving time, so `0 22 * * *`
remains 07:00 KST throughout the year.
