import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from meeting_pinger.config import Settings
from meeting_pinger.models import Meeting

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

logger = logging.getLogger(__name__)


class CalendarClient:
    def __init__(
        self,
        settings: Settings,
        token_json: str = "",
        calendar_id: str = "primary",
        user_label: str = "",
    ) -> None:
        self._settings = settings
        self._token_json = token_json
        self._calendar_id = calendar_id
        self._user_label = user_label or "default"
        self._service = None

    def authenticate(self) -> None:
        """Load or create OAuth2 credentials, refreshing if needed.

        For deployed (headless) environments, pass token_json at construction.
        For local dev, uses file-based token flow.
        """
        creds = None
        token_path = self._settings.google_token_path
        creds_path = self._settings.google_credentials_path

        if self._token_json:
            creds = Credentials.from_authorized_user_info(
                json.loads(self._token_json), SCOPES
            )
            logger.info(f"[{self._user_label}] Loaded credentials from token JSON")
        elif os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                if self._token_json:
                    logger.info(
                        f"[{self._user_label}] Token refreshed (in-memory only)"
                    )
                else:
                    with open(token_path, "w") as token_file:
                        token_file.write(creds.to_json())
            else:
                if self._token_json:
                    raise RuntimeError(
                        f"[{self._user_label}] Token is invalid and cannot be "
                        "refreshed. Re-run `make auth` locally and update the config."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    creds_path, SCOPES
                )
                creds = flow.run_local_server(port=0)
                with open(token_path, "w") as token_file:
                    token_file.write(creds.to_json())

        self._service = build("calendar", "v3", credentials=creds)
        logger.info(f"[{self._user_label}] Google Calendar authenticated successfully")

    def get_upcoming_meetings(self, lookahead_minutes: int) -> List[Meeting]:
        """Fetch meetings starting within the next N minutes."""
        now = datetime.now(timezone.utc)
        time_max = now + timedelta(minutes=lookahead_minutes)

        events_result = (
            self._service.events()
            .list(
                calendarId=self._calendar_id,
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])
        meetings = []

        for event in events:
            start = event.get("start", {})
            is_all_day = "date" in start and "dateTime" not in start

            if is_all_day and self._settings.is_skip_all_day_events:
                continue

            if event.get("status") == "cancelled":
                continue

            is_declined = False
            for attendee in event.get("attendees", []):
                if (
                    attendee.get("self")
                    and attendee.get("responseStatus") == "declined"
                ):
                    is_declined = True
                    break

            if is_declined and self._settings.is_skip_declined_events:
                continue

            if is_all_day:
                start_time = datetime.fromisoformat(start["date"]).replace(
                    tzinfo=timezone.utc
                )
                end_time = datetime.fromisoformat(event["end"]["date"]).replace(
                    tzinfo=timezone.utc
                )
            else:
                start_time = datetime.fromisoformat(start["dateTime"])
                end_time = datetime.fromisoformat(event["end"]["dateTime"])

            meetings.append(
                Meeting(
                    event_id=event["id"],
                    summary=event.get("summary", "(No title)"),
                    start_time=start_time,
                    end_time=end_time,
                    is_all_day=is_all_day,
                    is_declined=is_declined,
                    html_link=event.get("htmlLink", ""),
                )
            )

        logger.info(
            f"[{self._user_label}] Found {len(meetings)} upcoming meetings "
            f"in the next {lookahead_minutes} minutes"
        )
        return meetings

    def get_meetings_for_date(self, date: datetime) -> List[dict]:
        """Fetch all meetings for a specific date. Returns simplified dicts for digest."""
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        events_result = (
            self._service.events()
            .list(
                calendarId=self._calendar_id,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events = events_result.get("items", [])
        result = []

        for event in events:
            start = event.get("start", {})
            is_all_day = "date" in start and "dateTime" not in start

            if is_all_day and self._settings.is_skip_all_day_events:
                continue

            if event.get("status") == "cancelled":
                continue

            is_declined = False
            for attendee in event.get("attendees", []):
                if (
                    attendee.get("self")
                    and attendee.get("responseStatus") == "declined"
                ):
                    is_declined = True
                    break

            if is_declined and self._settings.is_skip_declined_events:
                continue

            if is_all_day:
                result.append(
                    {
                        "summary": event.get("summary", "(No title)"),
                        "start_time": "All day",
                        "end_time": "",
                    }
                )
            else:
                start_dt = datetime.fromisoformat(start["dateTime"])
                end_dt = datetime.fromisoformat(event["end"]["dateTime"])
                result.append(
                    {
                        "summary": event.get("summary", "(No title)"),
                        "start_time": start_dt.strftime("%-I:%M %p"),
                        "end_time": end_dt.strftime("%-I:%M %p"),
                    }
                )

        return result
