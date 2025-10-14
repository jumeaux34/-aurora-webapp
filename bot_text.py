"""Text-based Telegram bot for handling deposit requests."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from telegram import ReplyKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

BOT_TOKEN = "7612093789:AAFmp7EeR9iIEguG3zG6_6ImrzPd5L30c9w"
ADMIN_CHAT_ID = 123456789

OFFICE, AMOUNT = range(2)

OFFICE_KEYBOARD = ReplyKeyboardMarkup(
    [["Уфа"]], resize_keyboard=True, one_time_keyboard=True
)


def format_amount(amount: Decimal) -> str:
    """Return a human-friendly string representation of the amount."""
    normalized = amount.quantize(Decimal("1")) if amount == amount.to_integral() else amount.normalize()
    return f"{normalized}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send a welcome message and prompt the user to choose an office."""
    await update.message.reply_text(
        "Здравствуйте! Пожалуйста, выберите офис для пополнения:",
        reply_markup=OFFICE_KEYBOARD,
    )
    return OFFICE


async def office_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the selected office and ask for the deposit amount."""
    office = update.message.text.strip()
    if office != "Уфа":
        await update.message.reply_text(
            "Доступен только офис ‘Уфа’. Пожалуйста, выберите его из меню.",
            reply_markup=OFFICE_KEYBOARD,
        )
        return OFFICE

    context.user_data["office"] = office
    await update.message.reply_text("Введите сумму пополнения в рублях:")
    return AMOUNT


async def amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate the amount, notify the admin, and confirm to the user."""
    text = update.message.text.replace(",", ".").strip()
    try:
        amount = Decimal(text)
    except InvalidOperation:
        await update.message.reply_text(
            "Не удалось распознать сумму. Пожалуйста, введите число, например 1500."
        )
        return AMOUNT

    if amount <= 0:
        await update.message.reply_text(
            "Сумма должна быть положительным числом. Попробуйте снова."
        )
        return AMOUNT

    office = context.user_data.get("office", "Уфа")
    formatted_amount = format_amount(amount)

    admin_message = (
        "Новая заявка на пополнение:\n"
        f"ID пользователя: {update.effective_user.id}\n"
        f"Офис: {office}\n"
        f"Сумма: {formatted_amount}"
    )

    await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_message)
    await update.message.reply_text("✅ Ваша заявка отправлена")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Allow the user to cancel the current operation."""
    context.user_data.clear()
    await update.message.reply_text(
        "Операция отменена. Чтобы начать заново, отправьте команду /start."
    )
    return ConversationHandler.END


def main() -> None:
    """Start the bot and set up the command handlers."""
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conversation = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            OFFICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, office_handler)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_handler)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conversation)
    app.add_handler(CommandHandler("cancel", cancel))

    app.run_polling()


if __name__ == "__main__":
    main()
