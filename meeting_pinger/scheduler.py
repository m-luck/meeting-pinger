import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

from meeting_pinger.calendar_client import CalendarClient
from meeting_pinger.config import Settings
from meeting_pinger.meeting_tracker import MeetingTracker
from meeting_pinger.models import UserConfig
from meeting_pinger.slack_client import SlackClient

logger = logging.getLogger(__name__)

MORNING_DIGEST_HOUR = 8
EVENING_DIGEST_HOUR = 22


@dataclass
class UserState:
    user_config: UserConfig
    calendar: CalendarClient
    tracker: MeetingTracker
    sent_digests: Set[str] = field(default_factory=set)


class Scheduler:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._slack = SlackClient(settings)
        self._user_states: List[UserState] = []
        self._is_running: bool = False

    async def run(self) -> None:
        """Main loop: authenticate all users, start Slack, poll calendars, send pings."""
        users = self._settings.load_users()

        for user in users:
            label = user.name or user.slack_user_id
            calendar = CalendarClient(
                settings=self._settings,
                token_json=user.google_token_json,
                calendar_id=user.google_calendar_id,
                user_label=label,
            )
            calendar.authenticate()

            tracker = MeetingTracker(self._settings)
            state = UserState(
                user_config=user, calendar=calendar, tracker=tracker
            )
            self._user_states.append(state)

            self._slack.register_user(
                slack_user_id=user.slack_user_id,
                confirmation_phrase=user.confirmation_phrase,
                on_confirmation=lambda phrase, name, s=state: self._handle_confirmation(
                    s, phrase, name
                ),
            )
            logger.info(f"Registered user: {label} ({user.slack_user_id})")

        self._slack.set_digest_handlers(
            on_today=self.send_today_digest,
            on_tomorrow=self.send_tomorrow_digest,
        )
        self._slack.start()

        self._is_running = True
        logger.info(
            f"Meeting Pinger started for {len(self._user_states)} user(s). "
            f"Polling every {self._settings.poll_interval_seconds}s, "
            f"pinging {self._settings.ping_lead_time_minutes}min before meetings, "
            f"ping interval {self._settings.ping_interval_seconds}s."
        )

        try:
            while self._is_running:
                await self._tick()
                await asyncio.sleep(self._settings.poll_interval_seconds)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            self._slack.stop()
            logger.info("Meeting Pinger stopped")

    def _handle_confirmation(
        self, user_state: UserState, phrase: str, meeting_name: str
    ) -> Optional[str]:
        """Called by Slack client when a user sends 'ok for <meeting name>'."""
        label = user_state.user_config.name or user_state.user_config.slack_user_id
        confirmed_summary = user_state.tracker.confirm_by_name(meeting_name)
        if confirmed_summary:
            logger.info(f"[{label}] Confirmed meeting: '{confirmed_summary}'")
        return confirmed_summary

    async def _tick(self) -> None:
        """Single iteration of the main loop -- polls all users' calendars and sends digests."""
        now = datetime.now(timezone.utc)

        for user_state in self._user_states:
            label = (
                user_state.user_config.name or user_state.user_config.slack_user_id
            )
            try:
                self._check_digests(user_state, now)

                meetings = user_state.calendar.get_upcoming_meetings(
                    self._settings.lookahead_minutes
                )
                user_state.tracker.update_meetings(meetings)

                to_ping = user_state.tracker.get_meetings_to_ping()

                for state in to_ping:
                    minutes_until = int(
                        (state.meeting.start_time - now).total_seconds() / 60
                    )
                    self._slack.send_ping(
                        slack_user_id=user_state.user_config.slack_user_id,
                        meeting_summary=state.meeting.summary,
                        minutes_until=minutes_until,
                        ping_count=state.ping_count + 1,
                        confirmation_phrase=user_state.user_config.confirmation_phrase,
                    )
                    user_state.tracker.mark_pinged(state.meeting.event_id)

                user_state.tracker.cleanup_expired()

            except Exception as e:
                logger.error(f"[{label}] Error in tick: {e}", exc_info=True)

    def _check_digests(self, user_state: UserState, now: datetime) -> None:
        """Send morning and evening digests only during the exact target minute."""
        local_now = now.astimezone()
        today_key = f"morning-{local_now.strftime('%Y-%m-%d')}"
        tonight_key = f"evening-{local_now.strftime('%Y-%m-%d')}"
        label = user_state.user_config.name or user_state.user_config.slack_user_id

        is_morning_window = (
            local_now.hour == MORNING_DIGEST_HOUR and local_now.minute < 2
        )
        if is_morning_window and today_key not in user_state.sent_digests:
            user_state.sent_digests.add(today_key)
            try:
                meetings = user_state.calendar.get_meetings_for_date(local_now)
                self._slack.send_digest(
                    slack_user_id=user_state.user_config.slack_user_id,
                    header=f"Today's meetings ({local_now.strftime('%A, %b %-d')})",
                    meetings=meetings,
                )
            except Exception as e:
                logger.error(f"[{label}] Error sending morning digest: {e}")

        is_evening_window = (
            local_now.hour == EVENING_DIGEST_HOUR and local_now.minute < 2
        )
        if is_evening_window and tonight_key not in user_state.sent_digests:
            user_state.sent_digests.add(tonight_key)
            try:
                tomorrow = local_now + timedelta(days=1)
                meetings = user_state.calendar.get_meetings_for_date(tomorrow)
                self._slack.send_digest(
                    slack_user_id=user_state.user_config.slack_user_id,
                    header=f"Tomorrow's meetings ({tomorrow.strftime('%A, %b %-d')})",
                    meetings=meetings,
                )
            except Exception as e:
                logger.error(f"[{label}] Error sending evening digest: {e}")

    def send_today_digest(self, slack_user_id: str) -> None:
        """On-demand: send today's digest for a specific user."""
        for user_state in self._user_states:
            if user_state.user_config.slack_user_id == slack_user_id:
                local_now = datetime.now(timezone.utc).astimezone()
                meetings = user_state.calendar.get_meetings_for_date(local_now)
                self._slack.send_digest(
                    slack_user_id=slack_user_id,
                    header=f"Today's meetings ({local_now.strftime('%A, %b %-d')})",
                    meetings=meetings,
                )
                return

    def send_tomorrow_digest(self, slack_user_id: str) -> None:
        """On-demand: send tomorrow's digest for a specific user."""
        for user_state in self._user_states:
            if user_state.user_config.slack_user_id == slack_user_id:
                tomorrow = datetime.now(timezone.utc).astimezone() + timedelta(days=1)
                meetings = user_state.calendar.get_meetings_for_date(tomorrow)
                self._slack.send_digest(
                    slack_user_id=slack_user_id,
                    header=f"Tomorrow's meetings ({tomorrow.strftime('%A, %b %-d')})",
                    meetings=meetings,
                )
                return
