import asyncio
import logging
import os

from meeting_pinger.config import Settings
from meeting_pinger.health import start_health_server
from meeting_pinger.scheduler import Scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Entry point for the meeting pinger."""
    settings = Settings()

    port = int(os.environ.get("INTERNAL_TEAM_UTIL_PORT", os.environ.get("PORT", settings.port)))
    start_health_server(port)

    scheduler = Scheduler(settings)

    logger.info("Starting Meeting Pinger...")
    try:
        asyncio.run(scheduler.run())
    except KeyboardInterrupt:
        logger.info("Stopped by user")


if __name__ == "__main__":
    main()
