from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class PingStatus(Enum):
    PENDING = "pending"
    PINGING = "pinging"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"


@dataclass
class Meeting:
    event_id: str
    summary: str
    start_time: datetime
    end_time: datetime
    is_all_day: bool = False
    is_declined: bool = False
    is_cancelled: bool = False
    html_link: str = ""


@dataclass
class PingState:
    meeting: Meeting
    status: PingStatus = PingStatus.PENDING
    last_ping_at: Optional[datetime] = None
    ping_count: int = 0
    is_confirmed: bool = False


@dataclass
class UserConfig:
    slack_user_id: str
    google_token_json: str
    google_calendar_id: str = "primary"
    confirmation_phrase: str = "ok"
    name: str = ""
