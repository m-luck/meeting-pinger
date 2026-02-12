import json
import logging
from typing import List

from pydantic_settings import BaseSettings

from meeting_pinger.models import UserConfig

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Google Calendar (used for local auth only)
    google_credentials_path: str = "credentials/credentials.json"
    google_token_path: str = "credentials/token.json"

    # Slack bot (shared across all users)
    slack_bot_token: str = ""
    slack_app_token: str = ""

    # Per-user config: JSON string of user array, or path to a JSON file
    users_json: str = ""
    users_file: str = "users.json"

    # Behavior (defaults, can be overridden per-user in users config)
    ping_lead_time_minutes: int = 5
    ping_interval_seconds: int = 60
    poll_interval_seconds: int = 30
    lookahead_minutes: int = 15
    confirmation_phrase: str = "ok"

    # Filters
    is_skip_all_day_events: bool = True
    is_skip_declined_events: bool = True

    # Timezone (IANA name) for digest scheduling
    timezone: str = "America/New_York"

    # Server
    port: int = 8080

    model_config = {
        "env_prefix": "INTERNAL_TEAM_UTIL_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    def load_users(self) -> List[UserConfig]:
        """Load user configs from users_json env var or users_file."""
        raw = None

        if self.users_json:
            raw = json.loads(self.users_json)
            logger.info(f"Loaded {len(raw)} user(s) from INTERNAL_TEAM_UTIL_USERS_JSON")
        else:
            import os

            if os.path.exists(self.users_file):
                with open(self.users_file) as f:
                    raw = json.load(f)
                logger.info(f"Loaded {len(raw)} user(s) from {self.users_file}")

        if not raw:
            raise RuntimeError(
                "No users configured. Set INTERNAL_TEAM_UTIL_USERS_JSON or "
                "create a users.json file."
            )

        users = []
        for entry in raw:
            users.append(
                UserConfig(
                    slack_user_id=entry["slack_user_id"],
                    google_token_json=entry["google_token_json"],
                    google_calendar_id=entry.get("google_calendar_id", "primary"),
                    confirmation_phrase=entry.get(
                        "confirmation_phrase", self.confirmation_phrase
                    ),
                    name=entry.get("name", ""),
                )
            )

        return users
