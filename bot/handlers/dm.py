"""
DM handler — private messages.
- Regular users: info message
- Admins: full control panel with navigation
"""
import logging

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from bot.config import config
from bot.database.operations import (
    get_user_count,
    get_round_stats,
    get_match_count,
    get_current_round,
    get_opted_in_users,
    get_group_chat_id,
    update_round_status,
    delete_round,
)

logger = logging.getLogger(__name__)
router = Router()

# Only handle private (DM) messages
router.message.filter(F.chat.type == "private")
router.callback_query.filter(F.message.chat.type == "private")


def _is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids


_USER_TEXT = (
    "☕ <b>Привет! Я — Научный Кофе.</b>\n\n"
    "Бот для нетворкинга выпускников программы "
    "«Кадровый резерв Наука».\n\n"
    "📌 <b>Как это работает:</b>\n"
    "1. В чате появляется опрос — голосуй «Да!»\n"
    "2. Я составляю случайные пары\n"
    "3. Публикую результаты в чат\n"
    "4. Пишешь партнёру и договариваетесь о встрече\n\n"
    "Всё происходит в групповом чате — "
    "сюда писать не нужно 🙂\n\n"
    "🔒 <b>Приватность:</b> не собираю персональные данные. "
    "Использую только публичный @username из Telegram "
    "для составления пар."
)


# ─── Helpers ─────────────────────────────────────────────

async def _cleanup_poll(bot, round_data: dict) -> None:
    """Stop the poll and delete the poll message from the chat."""
    chat_id = round_data.get("chat_id") or (await get_group_chat_id())
    poll_msg_id = round_data.get("poll_message_id")
    if not chat_id or not poll_msg_id:
        return

    # Stop the poll first (close voting)
    try:
        await bot.stop_poll(chat_id=chat_id, message_id=poll_msg_id)
    except Exception as e:
        logger.debug(f"Could not stop poll: {e}")

    # Delete the poll message
    try:
        await bot.delete_message(chat_id=chat_id, message_id=poll_msg_id)
    except Exception as e:
        logger.debug(f"Could not delete poll message: {e}")


async def _stop_poll_only(bot, round_data: dict) -> None:
    """Stop the poll (close voting) but keep the message visible."""
    chat_id = round_data.get("chat_id") or (await get_group_chat_id())
    poll_msg_id = round_data.get("poll_message_id")
    if not chat_id or not poll_msg_id:
        return

    try:
        await bot.stop_poll(chat_id=chat_id, message_id=poll_msg_id)
    except Exception as e:
        logger.debug(f"Could not stop poll: {e}")


# ─── Main screen ─────────────────────────────────────────

async def _main_text_and_kb() -> tuple[str, InlineKeyboardMarkup]:
    """Build main admin screen: text + keyboard."""
    chat_id = await get_group_chat_id()
    current_round = await get_current_round()

    lines = ["☕ <b>Научный Кофе — Панель управления</b>\n"]

    if chat_id:
        lines.append(f"📍 Чат подключён: <code>{chat_id}</code>")
    else:
        lines.append(
            "⚠️ <b>Бот не добавлен в чат.</b>\n"
            "Добавь меня в группу."
        )

    buttons = []

    if current_round:
        opted = await get_opted_in_users(current_round["id"])
        status_emoji = {"planned": "📝", "active": "🟢"}.get(
            current_round["status"], "📋"
        )
        lines.append(
            f"\n{status_emoji} <b>Раунд #{current_round['id']}</b> "
            f"({current_round['status']})\n"
            f"   {current_round['month_start']} — {current_round['month_end']}\n"
            f"   Записались: {len(opted)}"
        )
        buttons.append(
            [InlineKeyboardButton(
                text="📋 Управление раундом",
                callback_data="adm_round",
            )]
        )
    else:
        lines.append("\nНет активного раунда.")
        if chat_id:
            buttons.append(
                [InlineKeyboardButton(
                    text="🚀 Запустить раунд",
                    callback_data="adm_coffee",
                )]
            )

    buttons.append(
        [InlineKeyboardButton(text="📊 Статистика", callback_data="adm_stats")]
    )

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


# ─── /start ──────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start_dm(message: Message):
    if _is_admin(message.from_user.id):
        text, kb = await _main_text_and_kb()
        await message.answer(text, reply_markup=kb)
    else:
        await message.answer(_USER_TEXT)


# ─── Back to main ────────────────────────────────────────

@router.callback_query(F.data == "adm_back")
async def cb_back(callback: CallbackQuery):
    text, kb = await _main_text_and_kb()
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


# ─── Launch round ────────────────────────────────────────

@router.callback_query(F.data == "adm_coffee")
async def cb_launch_round(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return

    chat_id = await get_group_chat_id()
    if not chat_id:
        await callback.answer("Бот не добавлен в чат!", show_alert=True)
        return

    from bot.services.matcher import create_monthly_round
    from bot.services.notifier import send_optin_poll

    round_data = await create_monthly_round(chat_id=chat_id)
    if not round_data:
        await callback.answer("Не удалось создать раунд", show_alert=True)
        return

    await send_optin_poll(callback.bot, chat_id, round_data["id"])

    await callback.message.edit_text(
        f"✅ <b>Раунд #{round_data['id']} запущен!</b>\n\n"
        f"Период: {round_data['month_start']} — {round_data['month_end']}\n"
        f"Опрос отправлен в чат.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Главная", callback_data="adm_back")],
        ]),
    )
    await callback.answer()
    logger.info(f"Admin started round via DM")


# ─── Round management submenu ────────────────────────────

@router.callback_query(F.data == "adm_round")
async def cb_round_menu(callback: CallbackQuery):
    """Show round management submenu."""
    if not _is_admin(callback.from_user.id):
        return

    current_round = await get_current_round()
    if not current_round:
        await callback.answer("Нет активного раунда", show_alert=True)
        return

    opted = await get_opted_in_users(current_round["id"])
    status_emoji = {"planned": "📝", "active": "🟢"}.get(
        current_round["status"], "📋"
    )

    text = (
        f"{status_emoji} <b>Раунд #{current_round['id']}</b> "
        f"({current_round['status']})\n\n"
        f"Период: {current_round['month_start']} — {current_round['month_end']}\n"
        f"Записались: <b>{len(opted)}</b>"
    )

    buttons = [
        [InlineKeyboardButton(text="👥 Кто записался", callback_data="adm_participants")],
        [InlineKeyboardButton(text="⚡ Запустить мэтчинг", callback_data="adm_match")],
        [InlineKeyboardButton(text="🔄 Перезапустить раунд", callback_data="adm_restart")],
        [InlineKeyboardButton(text="🛑 Завершить раунд", callback_data="adm_complete")],
        [InlineKeyboardButton(text="❌ Удалить раунд", callback_data="adm_delete")],
        [InlineKeyboardButton(text="← Главная", callback_data="adm_back")],
    ]

    await callback.message.edit_text(
        text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()


# ─── Participants list ───────────────────────────────────

@router.callback_query(F.data == "adm_participants")
async def cb_participants(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return

    current_round = await get_current_round()
    if not current_round:
        await callback.answer("Нет активного раунда", show_alert=True)
        return

    opted = await get_opted_in_users(current_round["id"])

    if not opted:
        text = "👥 <b>Пока никто не записался.</b>"
    else:
        lines = [f"👥 <b>Участники раунда #{current_round['id']}</b> ({len(opted)} чел.)\n"]
        for i, u in enumerate(opted, 1):
            username = f"@{u['username']}" if u.get("username") else "—"
            lines.append(f"{i}. {u['full_name']} ({username})")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Раунд", callback_data="adm_round")],
        ]),
    )
    await callback.answer()


# ─── Matching ────────────────────────────────────────────

@router.callback_query(F.data == "adm_match")
async def cb_match(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return

    chat_id = await get_group_chat_id()
    if not chat_id:
        await callback.answer("Бот не добавлен в чат!", show_alert=True)
        return

    current_round = await get_current_round()
    if not current_round:
        await callback.answer("Нет активного раунда!", show_alert=True)
        return

    from bot.services.matcher import run_matching
    from bot.services.notifier import send_pairs_message

    await callback.message.edit_text("⏳ Запускаю мэтчинг...")

    matches = await run_matching(current_round["id"])

    if not matches:
        opted = await get_opted_in_users(current_round["id"])
        await callback.message.edit_text(
            f"⚠️ <b>Недостаточно участников</b>\n\n"
            f"Записались: {len(opted)} (минимум: {config.min_participants})",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="← Раунд", callback_data="adm_round")],
            ]),
        )
        return

    # Close the poll — no more votes after matching
    await _stop_poll_only(callback.bot, current_round)

    await send_pairs_message(callback.bot, chat_id, matches)

    # Build summary of pairs for admin
    pair_lines = []
    for m in matches:
        names = " x ".join(
            f"@{u.get('username', '?')}" for u in m["users"]
        )
        pair_lines.append(f"  ☕ {names}")

    await callback.message.edit_text(
        f"✅ <b>Мэтчинг завершён!</b>\n\n"
        f"Пар: {len(matches)}\n"
        + "\n".join(pair_lines) + "\n\n"
        f"Результаты опубликованы в чат.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Главная", callback_data="adm_back")],
        ]),
    )
    await callback.answer()
    logger.info(f"Matching via DM: {len(matches)} pairs")


# ─── Restart round ───────────────────────────────────────

@router.callback_query(F.data == "adm_restart")
async def cb_restart(callback: CallbackQuery):
    """Confirm restart — delete current + create new + send poll."""
    if not _is_admin(callback.from_user.id):
        return

    current_round = await get_current_round()
    if not current_round:
        await callback.answer("Нет активного раунда", show_alert=True)
        return

    await callback.message.edit_text(
        f"🔄 <b>Перезапустить раунд #{current_round['id']}?</b>\n\n"
        "Текущий раунд будет удалён.\n"
        "Создам новый и отправлю опрос в чат.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Да, перезапустить",
                callback_data="adm_restart_confirm",
            )],
            [InlineKeyboardButton(text="← Отмена", callback_data="adm_round")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "adm_restart_confirm")
async def cb_restart_confirm(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return

    chat_id = await get_group_chat_id()
    if not chat_id:
        await callback.answer("Бот не добавлен в чат!", show_alert=True)
        return

    current_round = await get_current_round()
    if current_round:
        await _cleanup_poll(callback.bot, current_round)
        await delete_round(current_round["id"])

    from bot.services.matcher import create_monthly_round
    from bot.services.notifier import send_optin_poll

    round_data = await create_monthly_round(chat_id=chat_id)
    if round_data:
        await send_optin_poll(callback.bot, chat_id, round_data["id"])

    await callback.message.edit_text(
        f"✅ <b>Раунд перезапущен!</b>\n"
        f"Новый раунд #{round_data['id']} создан.\n"
        f"Опрос отправлен в чат.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Главная", callback_data="adm_back")],
        ]),
    )
    await callback.answer()
    logger.info("Round restarted via DM")


# ─── Complete round ──────────────────────────────────────

@router.callback_query(F.data == "adm_complete")
async def cb_complete(callback: CallbackQuery):
    """Confirm force-complete."""
    if not _is_admin(callback.from_user.id):
        return

    current_round = await get_current_round()
    if not current_round:
        await callback.answer("Нет активного раунда", show_alert=True)
        return

    await callback.message.edit_text(
        f"🛑 <b>Завершить раунд #{current_round['id']}?</b>\n\n"
        "Раунд будет помечен как завершённый.\n"
        "Данные сохранятся.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="✅ Да, завершить",
                callback_data="adm_complete_confirm",
            )],
            [InlineKeyboardButton(text="← Отмена", callback_data="adm_round")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "adm_complete_confirm")
async def cb_complete_confirm(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return

    current_round = await get_current_round()
    if current_round:
        await _cleanup_poll(callback.bot, current_round)
        await update_round_status(current_round["id"], "completed")

    await callback.message.edit_text(
        "✅ Раунд завершён. Опрос закрыт.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Главная", callback_data="adm_back")],
        ]),
    )
    await callback.answer()
    logger.info("Round force-completed via DM")


# ─── Delete round ────────────────────────────────────────

@router.callback_query(F.data == "adm_delete")
async def cb_delete(callback: CallbackQuery):
    """Confirm delete."""
    if not _is_admin(callback.from_user.id):
        return

    current_round = await get_current_round()
    if not current_round:
        await callback.answer("Нет активного раунда", show_alert=True)
        return

    opted = await get_opted_in_users(current_round["id"])

    await callback.message.edit_text(
        f"❌ <b>Удалить раунд #{current_round['id']}?</b>\n\n"
        f"Записавшиеся: {len(opted)}\n"
        "Все данные раунда (участники, пары) будут удалены безвозвратно.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="❌ Да, удалить",
                callback_data="adm_delete_confirm",
            )],
            [InlineKeyboardButton(text="← Отмена", callback_data="adm_round")],
        ]),
    )
    await callback.answer()


@router.callback_query(F.data == "adm_delete_confirm")
async def cb_delete_confirm(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return

    current_round = await get_current_round()
    if current_round:
        await _cleanup_poll(callback.bot, current_round)
        await delete_round(current_round["id"])

    await callback.message.edit_text(
        "✅ Раунд удалён. Опрос убран из чата.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Главная", callback_data="adm_back")],
        ]),
    )
    await callback.answer()
    logger.info("Round deleted via DM")


# ─── Statistics ──────────────────────────────────────────

@router.callback_query(F.data == "adm_stats")
async def cb_stats(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return

    user_count = await get_user_count()
    round_stats = await get_round_stats()
    match_count = await get_match_count()

    await callback.message.edit_text(
        "📊 <b>Статистика Научного Кофе</b>\n\n"
        f"👥 Пользователей: <b>{user_count}</b>\n"
        f"🔄 Раундов: {round_stats['total']} "
        f"(завершённых: {round_stats['completed']})\n"
        f"☕ Всего пар: {match_count}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="← Главная", callback_data="adm_back")],
        ]),
    )
    await callback.answer()


# ─── Catch-all for regular users ─────────────────────────

@router.message()
async def any_dm(message: Message):
    if _is_admin(message.from_user.id):
        text, kb = await _main_text_and_kb()
        await message.answer(text, reply_markup=kb)
    else:
        await message.answer(_USER_TEXT)
