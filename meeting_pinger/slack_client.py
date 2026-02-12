import logging
from typing import Callable, Dict, List, Optional

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from meeting_pinger.config import Settings

logger = logging.getLogger(__name__)


class SlackClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._app = App(token=settings.slack_bot_token)
        self._client = self._app.client
        self._socket_handler: Optional[SocketModeHandler] = None
        self._dm_channels: Dict[str, str] = {}  # slack_user_id -> channel_id
        self._user_confirmation_handlers: Dict[
            str, Callable[[str], None]
        ] = {}  # slack_user_id -> handler
        self._user_phrases: Dict[str, str] = {}  # slack_user_id -> confirmation_phrase
        self._on_today: Optional[Callable[[str], None]] = None
        self._on_tomorrow: Optional[Callable[[str], None]] = None

    def register_user(
        self,
        slack_user_id: str,
        confirmation_phrase: str,
        on_confirmation: Callable[[str, str], Optional[str]],
    ) -> None:
        """Register a user for confirmation handling.

        on_confirmation receives (phrase, meeting_name) and returns the confirmed
        meeting summary or None if no match.
        """
        self._user_phrases[slack_user_id] = confirmation_phrase.lower()
        self._user_confirmation_handlers[slack_user_id] = on_confirmation

    def set_digest_handlers(
        self,
        on_today: Callable[[str], None],
        on_tomorrow: Callable[[str], None],
    ) -> None:
        """Register handlers for on-demand digest commands."""
        self._on_today = on_today
        self._on_tomorrow = on_tomorrow

    def start(self) -> None:
        """Start the Slack bot in Socket Mode (runs in a background thread)."""

        @self._app.event("message")
        def handle_message(event: dict, say: Callable) -> None:
            text = event.get("text", "").strip().lower()
            user = event.get("user", "")

            if user not in self._user_confirmation_handlers:
                return

            if text == "today":
                if self._on_today:
                    self._on_today(user)
                return

            if text == "tomorrow":
                if self._on_tomorrow:
                    self._on_tomorrow(user)
                return

            phrase = self._user_phrases.get(user, "ok")
            prefix = f"{phrase} for "

            if not text.startswith(prefix):
                return

            meeting_name = text[len(prefix):].strip()
            if not meeting_name:
                say(f"Please specify the meeting: `{phrase} for <meeting name>`")
                return

            logger.info(f"Received confirmation from {user}: '{text}'")
            handler = self._user_confirmation_handlers[user]
            result = handler(phrase, meeting_name)
            if result:
                say(f"Got it. Stopping pings for *{result}*.")
            else:
                say(
                    f"No active meeting matching \"{meeting_name}\". "
                    f"Try `{phrase} for <part of the meeting name>`."
                )

        self._socket_handler = SocketModeHandler(
            self._app, self._settings.slack_app_token
        )
        self._socket_handler.connect()
        logger.info("Slack Socket Mode handler started")

    def stop(self) -> None:
        """Stop the Slack bot."""
        if self._socket_handler:
            self._socket_handler.close()
            logger.info("Slack Socket Mode handler stopped")

    def _get_dm_channel_id(self, slack_user_id: str) -> str:
        """Open or retrieve the DM channel with a specific user."""
        if slack_user_id in self._dm_channels:
            return self._dm_channels[slack_user_id]

        response = self._client.conversations_open(users=[slack_user_id])
        channel_id = response["channel"]["id"]
        self._dm_channels[slack_user_id] = channel_id
        return channel_id

    def send_ping(
        self,
        slack_user_id: str,
        meeting_summary: str,
        minutes_until: int,
        ping_count: int,
        confirmation_phrase: str = "ok",
    ) -> None:
        """Send a ping DM about an upcoming meeting to a specific user."""
        channel_id = self._get_dm_channel_id(slack_user_id)

        if minutes_until > 0:
            time_text = f"starts in {minutes_until} minute{'s' if minutes_until != 1 else ''}"
        elif minutes_until == 0:
            time_text = "is starting NOW"
        else:
            time_text = f"started {abs(minutes_until)} minute{'s' if abs(minutes_until) != 1 else ''} ago"

        message = (
            f"*Meeting Reminder* (ping #{ping_count})\n"
            f"> *{meeting_summary}* {time_text}\n"
            f"Reply `{confirmation_phrase} for {meeting_summary}` to stop pinging."
        )

        self._client.chat_postMessage(channel=channel_id, text=message)
        logger.info(
            f"Sent ping #{ping_count} for '{meeting_summary}' to {slack_user_id} "
            f"({time_text})"
        )

    def send_digest(
        self,
        slack_user_id: str,
        header: str,
        meetings: List[dict],
        current_time_str: str = "",
        target_day: str = "",
    ) -> None:
        """Send a daily digest of meetings to a user.

        Args:
            slack_user_id: The user to DM.
            header: e.g. "Today's meetings" or "Tomorrow's meetings".
            meetings: List of dicts with 'summary', 'start_time', 'end_time'.
            current_time_str: e.g. "7:20 PM EST" -- the current local time.
            target_day: e.g. "today (Wednesday)" or "tomorrow (Thursday)".
        """
        channel_id = self._get_dm_channel_id(slack_user_id)

        preamble = ""
        if current_time_str and target_day:
            preamble = f"_It is {current_time_str}. Showing schedule for {target_day}._\n\n"

        if not meetings:
            self._client.chat_postMessage(
                channel=channel_id,
                text=f"{preamble}*{header}*\nNo meetings scheduled.",
            )
            logger.info(f"Sent empty digest ({header}) to {slack_user_id}")
            return

        first_time = meetings[0]["start_time"]
        first_line = f"*Your first meeting is at {first_time}*\n"

        lines = [f"{preamble}{first_line}\n*{header}*\n"]
        for m in meetings:
            lines.append(f"  {m['start_time']} - {m['end_time']}  *{m['summary']}*")

        self._client.chat_postMessage(channel=channel_id, text="\n".join(lines))
        logger.info(
            f"Sent digest ({header}, {len(meetings)} meetings) to {slack_user_id}"
        )
