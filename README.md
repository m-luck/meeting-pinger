# Meeting Pinger

Slack bot that monitors Google Calendar and sends DM reminders every minute before and during meetings until you reply with a confirmation phrase. Supports multiple users and daily meeting digests.

## Features

- Pings you on Slack starting 5 minutes before a meeting, repeating every 60 seconds
- Stops pinging when you reply `ok for <meeting name>` (substring match)
- Daily digest at 8am (today's meetings) and 10pm (tomorrow's meetings)
- On-demand digests: type `today` or `tomorrow` in the bot DM
- Skips all-day, declined, and cancelled events
- Multi-user support via `users.json`

## Prerequisites

- Python 3.12+
- [Poetry](https://python-poetry.org/docs/#installation)
- A Google Cloud project with Calendar API enabled
- A Slack workspace where you can create apps

## Setup

### 1. Clone and install

```bash
git clone git@github.com:m-luck/meeting-pinger.git
cd meeting-pinger
make dev-install
```

### 2. Google Calendar OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use an existing one)
3. Enable the **Google Calendar API**
4. Go to **Credentials** > **Create Credentials** > **OAuth client ID**
5. Choose **Desktop app** as the application type
6. Download the JSON file and save it as `credentials/credentials.json`
7. Run the OAuth flow:

```bash
make auth
```

This opens a browser window to authorize calendar access. The token is saved to `credentials/token.json`.

### 3. Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app
2. Under **Socket Mode**, enable it and generate an app-level token (`xapp-...`)
3. Under **OAuth & Permissions**, add these bot scopes:
   - `chat:write`
   - `im:history`
   - `im:write`
4. Under **Event Subscriptions**, enable events and subscribe to the `message.im` bot event
5. Under **App Home**, check "Allow users to send Slash commands and messages from the messages tab"
6. Install the app to your workspace and copy the bot token (`xoxb-...`)
7. Find your Slack user ID (click your profile > three dots > "Copy member ID")

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```
INTERNAL_TEAM_UTIL_SLACK_BOT_TOKEN=xoxb-your-bot-token
INTERNAL_TEAM_UTIL_SLACK_APP_TOKEN=xapp-your-app-level-token
```

### 5. Configure users

```bash
cp users.json.example users.json
```

Edit `users.json` with each user's config. To get the `google_token_json` value for a user:

```bash
# Each user runs this locally after completing step 2
make print-token
```

Paste the output into the `google_token_json` field for that user.

Example `users.json`:

```json
[
  {
    "name": "Michael",
    "slack_user_id": "U09AYD7Q96F",
    "google_token_json": "{\"token\": \"...\", \"refresh_token\": \"...\", ...}",
    "google_calendar_id": "primary",
    "confirmation_phrase": "ok"
  }
]
```

### 6. Run

```bash
make run
```

## Usage

Once running, the bot will DM you on Slack:

| You receive | You reply | What happens |
|---|---|---|
| Ping about "Team Standup" | `ok for standup` | Pings stop (substring match) |
| Nothing (want today's schedule) | `today` | Bot sends today's meeting digest |
| Nothing (want tomorrow's schedule) | `tomorrow` | Bot sends tomorrow's meeting digest |

## Adding a teammate

1. They clone the repo and run `make dev-install`
2. Share `credentials/credentials.json` with them (this is the OAuth client, not a personal token)
3. They run `make auth` to authorize their own Google account
4. They run `make print-token` and send you the output
5. Add their entry to `users.json` with their Slack user ID and token JSON

## Azure deployment

The bot can run on Azure Container Apps for always-on operation.

```bash
# Login to Azure CLI
az login

# Set required env vars
export INTERNAL_TEAM_UTIL_SLACK_BOT_TOKEN=xoxb-...
export INTERNAL_TEAM_UTIL_SLACK_APP_TOKEN=xapp-...
export INTERNAL_TEAM_UTIL_USERS_JSON=$(cat users.json)

# Deploy
make deploy
```

This creates a Container Registry, builds the Docker image, and deploys to Container Apps with `--min-replicas 1`.

## Configuration

All env vars are prefixed with `INTERNAL_TEAM_UTIL_`. Defaults shown:

| Variable | Default | Description |
|---|---|---|
| `PING_LEAD_TIME_MINUTES` | `5` | Start pinging N minutes before meeting |
| `PING_INTERVAL_SECONDS` | `60` | Seconds between pings |
| `POLL_INTERVAL_SECONDS` | `30` | How often to check the calendar |
| `LOOKAHEAD_MINUTES` | `15` | How far ahead to look for meetings |
