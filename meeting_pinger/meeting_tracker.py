import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from meeting_pinger.config import Settings
from meeting_pinger.models import Meeting, PingState, PingStatus

logger = logging.getLogger(__name__)


class MeetingTracker:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tracked: Dict[str, PingState] = {}

    def update_meetings(self, meetings: List[Meeting]) -> None:
        """Merge newly fetched meetings into tracking state.

        New meetings are added as PENDING. Existing meetings are left alone.
        Meetings that disappeared and already started are marked EXPIRED.
        """
        seen_ids = {m.event_id for m in meetings}

        for meeting in meetings:
            if meeting.event_id not in self._tracked:
                self._tracked[meeting.event_id] = PingState(meeting=meeting)
                logger.info(
                    f"Now tracking: '{meeting.summary}' at {meeting.start_time}"
                )

        now = datetime.now(timezone.utc)
        for event_id, state in list(self._tracked.items()):
            if event_id not in seen_ids and state.meeting.start_time < now:
                if state.status not in (PingStatus.CONFIRMED, PingStatus.EXPIRED):
                    state.status = PingStatus.EXPIRED
                    logger.info(
                        f"Expired tracking for: '{state.meeting.summary}'"
                    )

    def get_meetings_to_ping(self) -> List[PingState]:
        """Return meetings that should be pinged right now."""
        now = datetime.now(timezone.utc)
        lead_time = timedelta(minutes=self._settings.ping_lead_time_minutes)
        ping_interval = timedelta(seconds=self._settings.ping_interval_seconds)
        result = []

        for state in self._tracked.values():
            if state.status in (PingStatus.CONFIRMED, PingStatus.EXPIRED):
                continue

            time_until_start = state.meeting.start_time - now

            is_in_ping_window = time_until_start <= lead_time
            is_past_start_within_grace = (
                time_until_start < timedelta(0)
                and abs(time_until_start) < timedelta(minutes=10)
            )

            if not (is_in_ping_window or is_past_start_within_grace):
                continue

            state.status = PingStatus.PINGING

            if state.last_ping_at is not None:
                time_since_last_ping = now - state.last_ping_at
                if time_since_last_ping < ping_interval:
                    continue

            result.append(state)

        return result

    def mark_pinged(self, event_id: str) -> None:
        """Record that a ping was sent for this meeting."""
        if event_id in self._tracked:
            state = self._tracked[event_id]
            state.last_ping_at = datetime.now(timezone.utc)
            state.ping_count += 1

    def confirm_by_name(self, meeting_name: str) -> Optional[str]:
        """Confirm a meeting by matching its name (case-insensitive substring).

        Returns the meeting summary if confirmed, None otherwise.
        """
        meeting_name_lower = meeting_name.lower().strip()
        is_pinging = [
            s for s in self._tracked.values() if s.status == PingStatus.PINGING
        ]
        if not is_pinging:
            return None

        for state in is_pinging:
            if meeting_name_lower in state.meeting.summary.lower():
                state.status = PingStatus.CONFIRMED
                state.is_confirmed = True
                logger.info(f"Confirmed: '{state.meeting.summary}'")
                return state.meeting.summary

        return None

    def get_pinging_summaries(self) -> List[str]:
        """Return summaries of all currently pinging meetings."""
        return [
            s.meeting.summary
            for s in self._tracked.values()
            if s.status == PingStatus.PINGING
        ]

    def cleanup_expired(self) -> None:
        """Remove meetings that ended more than 30 minutes ago."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=30)
        to_remove = [
            eid
            for eid, state in self._tracked.items()
            if state.meeting.end_time < cutoff
        ]
        for eid in to_remove:
            del self._tracked[eid]

    @property
    def active_count(self) -> int:
        """Number of meetings currently being tracked."""
        return sum(
            1
            for s in self._tracked.values()
            if s.status in (PingStatus.PENDING, PingStatus.PINGING)
        )
