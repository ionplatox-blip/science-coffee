"""
☕ Научный Кофе — Main entry point.
Initializes bot, registers handlers, starts scheduler.
Works inside a group chat (not DMs).
"""
import asyncio
import logging
import logging.handlers
import pathlib
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import config

# Logging — console + file
log_dir = pathlib.Path(__file__).resolve().parent.parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            log_dir / "bot.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point."""
    if not config.bot_token:
        logger.error("BOT_TOKEN is not set! Check your .env file.")
        sys.exit(1)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Database init
    from bot.database.models import init_db
    await init_db()
    logger.info("Database initialized.")

    # Setup bot profile (avatar, description)
    await _setup_bot_profile(bot)

    # Register routers (order matters — DM last as catch-all)
    from bot.handlers import commands, polls, chat_events, dm
    dp.include_router(chat_events.router)  # my_chat_member events
    dp.include_router(commands.router)
    dp.include_router(polls.router)
    dp.include_router(dm.router)           # catch-all for DMs

    # ── Scheduler: monthly cycle (only if GROUP_CHAT_ID is set) ──
    if config.group_chat_id and config.group_chat_id != 0:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

        scheduler.add_job(
            _daily_dispatcher,
            "cron",
            hour=config.announce_hour,
            minute=0,
            args=[bot],
            id="daily_dispatcher",
            replace_existing=True,
        )

        scheduler.add_job(
            _matching_dispatcher,
            "cron",
            hour=config.match_hour,
            minute=0,
            args=[bot],
            id="matching_dispatcher",
            replace_existing=True,
        )

        scheduler.start()
        logger.info(
            f"Scheduler started — monthly cycle for chat {config.group_chat_id} "
            f"(announce {config.announce_hour}:00, match {config.match_hour}:00)"
        )
    else:
        scheduler = None
        logger.warning(
            "GROUP_CHAT_ID not set — scheduler disabled. "
            "Use /coffee and /match commands manually."
        )

    # Start polling
    me = await bot.get_me()
    logger.info(f"☕ Научный Кофе is live as @{me.username}")

    try:
        await dp.start_polling(bot)
    finally:
        if scheduler:
            scheduler.shutdown()
        await bot.session.close()

# ─── Bot profile setup ───────────────────────────────────

async def _setup_bot_profile(bot: Bot):
    """Set bot avatar, description, and short description."""
    import pathlib
    from aiogram.types import FSInputFile

    # Description (shown when user first opens bot)
    try:
        await bot.set_my_description(
            description=(
                "☕ Научный Кофе — бот для нетворкинга "
                "выпускников программы «Кадровый резерв Наука».\n\n"
                "Раз в месяц составляю случайные пары для "
                "неформальных встреч внутри сообщества.\n\n"
                "Работаю в групповом чате. "
                "Не собираю персональные данные — "
                "использую только публичный @username "
                "для формирования пар."
            )
        )
        logger.info("Bot description set.")
    except Exception as e:
        logger.warning(f"Could not set description: {e}")

    # Short description (shown in bot profile)
    try:
        await bot.set_my_short_description(
            short_description=(
                "☕ Нетворкинг для выпускников КР Наука — "
                "случайные кофейные встречи каждый месяц"
            )
        )
        logger.info("Bot short description set.")
    except Exception as e:
        logger.warning(f"Could not set short description: {e}")

    # Avatar photo
    avatar_path = pathlib.Path(__file__).resolve().parent.parent / "avatar.jpg"
    if avatar_path.exists():
        try:
            photo = FSInputFile(str(avatar_path))
            await bot.set_chat_photo(chat_id=bot.id, photo=photo)
            logger.info("Bot avatar set.")
        except Exception as e:
            # set_chat_photo doesn't work for bots — use BotFather
            logger.debug(f"Avatar via API not supported: {e}")
    else:
        logger.debug("No avatar.jpg found, skipping.")


# ─── Date helpers ────────────────────────────────────────


def _get_today():
    """Get today's date in Moscow timezone."""
    from zoneinfo import ZoneInfo
    from datetime import datetime
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def _is_nearest_weekday(today, target_day: int) -> bool:
    """Check if today is the nearest weekday to target_day in this month."""
    import calendar
    from datetime import date, timedelta

    last = calendar.monthrange(today.year, today.month)[1]
    target = min(target_day, last)
    d = date(today.year, today.month, target)
    if d.weekday() == 5:
        d -= timedelta(days=1)
    elif d.weekday() == 6:
        d -= timedelta(days=2)
    return today == d


# ─── Monthly Dispatchers ─────────────────────────────────

async def _daily_dispatcher(bot: Bot):
    """
    Runs every day at announce_hour. Checks date and dispatches:
    - 1st Monday: announce new round (send poll)
    - ~18th (weekday): meeting nudge
    - ~30th (weekday): feedback poll
    """
    today = _get_today()
    day, weekday = today.day, today.weekday()

    if day <= 7 and weekday == 0:
        logger.info("📅 1st Monday — creating round + sending poll")
        await _announce_round(bot)
    elif _is_nearest_weekday(today, config.reminder_day):
        logger.info(f"📅 ~{config.reminder_day}th — meeting nudge")
        await _meeting_nudge(bot)
    elif _is_nearest_weekday(today, config.feedback_day):
        logger.info(f"📅 ~{config.feedback_day}th — feedback poll")
        await _request_feedback(bot)


async def _matching_dispatcher(bot: Bot):
    """
    Runs every day at match_hour. Only fires on 2nd Monday.
    """
    today = _get_today()
    day, weekday = today.day, today.weekday()

    if 8 <= day <= 14 and weekday == 0:
        logger.info("☕ 2nd Monday 18:00 — running matching")
        await _run_matching(bot)


# ─── Job implementations ─────────────────────────────────

async def _announce_round(bot: Bot):
    """1st Monday: create round + send poll to chat."""
    from bot.services.matcher import create_monthly_round
    from bot.services.notifier import send_optin_poll
    from bot.database.operations import get_group_chat_id

    chat_id = await get_group_chat_id()
    if not chat_id:
        logger.warning("No group chat ID — skipping announce")
        return

    round_data = await create_monthly_round(chat_id=chat_id)
    if not round_data:
        logger.error("Failed to create monthly round")
        return

    await send_optin_poll(bot, chat_id, round_data["id"])

    for admin_id in config.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"📋 <b>Раунд #{round_data['id']} создан</b>\n"
                f"Период: {round_data['month_start']} — {round_data['month_end']}\n"
                f"Poll отправлен в чат.",
            )
        except Exception:
            pass


async def _run_matching(bot: Bot):
    """2nd Monday 18:00: match all opted-in users."""
    from bot.services.matcher import run_matching
    from bot.services.notifier import send_pairs_message
    from bot.database.operations import get_current_round, update_round_status, get_group_chat_id

    current_round = await get_current_round()
    if not current_round:
        logger.warning("No active round to match")
        return

    matches = await run_matching(current_round["id"])
    chat_id = current_round.get("chat_id") or (await get_group_chat_id())

    if not matches:
        for admin_id in config.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    "⚠️ <b>Раунд пропущен</b>\n"
                    f"Недостаточно участников (минимум {config.min_participants}).",
                )
            except Exception:
                pass
        await update_round_status(current_round["id"], "completed")
        return

    await send_pairs_message(bot, chat_id, matches)

    for admin_id in config.admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"☕ <b>Мэтчинг завершён — Раунд #{current_round['id']}</b>\n"
                f"Пар: {len(matches)}",
            )
        except Exception:
            pass


async def _meeting_nudge(bot: Bot):
    """~18th: nudge in chat."""
    from bot.services.notifier import send_meeting_nudge
    from bot.database.operations import get_current_round

    current_round = await get_current_round()
    if not current_round:
        return

    chat_id = current_round.get("chat_id") or (await get_group_chat_id())
    await send_meeting_nudge(bot, chat_id)


async def _request_feedback(bot: Bot):
    """~30th: feedback poll + complete round."""
    from bot.services.notifier import send_feedback_poll
    from bot.database.operations import update_round_status
    from bot.database.models import get_db

    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM rounds WHERE status = 'active' "
            "ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        prev_round = dict(row) if row else None
    finally:
        await db.close()

    if not prev_round:
        return

    chat_id = prev_round.get("chat_id") or (await get_group_chat_id())
    await send_feedback_poll(bot, chat_id)
    await update_round_status(prev_round["id"], "completed")


if __name__ == "__main__":
    asyncio.run(main())
