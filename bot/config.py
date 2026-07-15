"""
Научный Кофе — Configuration.
Loads settings from .env file.
"""
import pathlib
from dataclasses import dataclass, field

from dotenv import load_dotenv
import os

# Load .env from project root
_env_path = pathlib.Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)


@dataclass(frozen=True)
class Config:
    bot_token: str = field(default_factory=lambda: os.getenv("BOT_TOKEN", ""))
    admin_ids: frozenset[int] = field(default_factory=lambda: frozenset(
        int(x.strip()) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip()
    ))

    # Group chat where the bot operates
    group_chat_id: int = field(
        default_factory=lambda: int(os.getenv("GROUP_CHAT_ID", "0"))
    )

    # Database
    db_path: str = field(
        default_factory=lambda: str(
            pathlib.Path(__file__).resolve().parent.parent / "data" / "coffee.db"
        )
    )

    # Scheduler settings — monthly cycle (MSK)
    announce_hour: int = 10     # Hour for poll + reminders
    match_hour: int = 18        # Hour for matching (2nd Monday)
    reminder_day: int = 18      # Day of month for meeting nudge
    feedback_day: int = 30      # Day of month for feedback request

    # Matching
    history_lookback: int = 4    # Avoid repeat pairs for N rounds
    min_participants: int = 2    # Minimum to run a round


config = Config()
