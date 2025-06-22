from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import requests
from collections import defaultdict

# --- Хранилище балансов пользователей: chat_id → {symbol: amount} ---
user_balances: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))

# --- Словарь «символ → CoinGecko ID» ---
SYMBOL_MAP = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "usdt": "tether",
    "bnb": "binancecoin",
    "ada": "cardano",
    "xrp": "ripple",
    "usdc": "usd-coin",
    "doge": "dogecoin",
    "matic": "matic-network",
}

def resolve_coin(symbol: str) -> str:
    return SYMBOL_MAP.get(symbol, symbol)

# --- Настройка администратора для уведомлений ---
ADMIN_CHAT_ID = 7736404289  # замените на ваш chat_id

# --- Токен от BotFather ---
BOT_TOKEN = "7612093789:AAFmp7EeR9iIEguG3zG6_6ImrzPd5L30c9w"

def get_price(symbol: str) -> float | None:
    coin_id = resolve_coin(symbol.lower())
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": coin_id, "vs_currencies": "usd"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        return data.get(coin_id, {}).get("usd")
    except Exception:
        return None

# --- Обработчики ---
async def initial_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔰 Начать", callback_data="main_menu")]]
    markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text("Нажмите кнопку, чтобы начать:", reply_markup=markup)
    else:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("Нажмите кнопку, чтобы начать:", reply_markup=markup)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("🏦 Кошелёк", callback_data="wallet_menu"),
         InlineKeyboardButton("📈 Биржа", callback_data="exchange_menu")],
        [InlineKeyboardButton("🤝 P2P", callback_data="p2p_menu"),
         InlineKeyboardButton("⚙️ Аккаунт", callback_data="account_menu")],
    ]
    await query.edit_message_text("Выберите раздел:", reply_markup=InlineKeyboardMarkup(keyboard))

async def wallet_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Баланс", callback_data="wallet_balance")],
        [InlineKeyboardButton("Пополнить", callback_data="wallet_deposit")],
        [InlineKeyboardButton("Вывести", callback_data="wallet_withdraw")],
        [InlineKeyboardButton("◀️ Назад", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        "🏦 *Кошелёк*\nВыберите действие:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def wallet_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    balances = user_balances[chat_id]
    if not balances:
        text = "У вас пока нет средств."
    else:
        text = "Ваш баланс:\n" + "\n".join(f"{sym.upper()}: {amt}" for sym, amt in balances.items())
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="wallet_menu")]])
    )

async def wallet_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Офис Москва", callback_data="deposit_office_moscow")],
        [InlineKeyboardButton("Офис Санкт-Петербург", callback_data="deposit_office_spb")],
        [InlineKeyboardButton("◀️ Назад", callback_data="wallet_menu")],
    ]
    await query.edit_message_text(
        "🚀 Выберите офис для пополнения:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def deposit_office_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    office = query.data.split('_')[-1]
    context.user_data['deposit_office'] = office
    await query.edit_message_text(
        f"Вы выбрали офис: {office}\nВведите сумму пополнения:",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="wallet_menu")]])
    )

async def deposit_amount_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    office = context.user_data.get('deposit_office')
    if not office:
        return
    amount = update.message.text.strip()
    chat_id = update.effective_chat.id
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(f"Новая заявка на пополнение:\n"
                  f"Пользователь: {chat_id}\n"
                  f"Офис: {office}\n"
                  f"Сумма: {amount}"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✉️ Связаться с клиентом", url=f"tg://user?id={chat_id}")]
            ])
        )
    except Exception:
        await update.message.reply_text(
            "⚠️ Не удалось уведомить администратора. "
            "Попросите его сначала нажать /start в личном чате с ботом."
        )
    await update.message.reply_text("✅ Ваша заявка на пополнение отправлена! Спасибо.")
    context.user_data.pop('deposit_office', None)

async def wallet_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "💸 Функция вывода в разработке.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="wallet_menu")]])
    )

async def exchange_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "📈 *Биржа*\nИспользуйте /rate и /exchange.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
    )

async def p2p_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "🤝 *P2P*\nСписок P2P-офферов в разработке.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
    )

async def account_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚙️ *Аккаунт*\nУправление профилем в разработке.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Назад", callback_data="main_menu")]])
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/rate <coin> — узнать курс\n"
        "/exchange <from> <to> <amount> — расчёт обмена"
    )

async def rate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Нужно указать монету, например /rate btc")
    sym = context.args[0].lower()
    price = get_price(sym)
    if price is None:
        return await update.message.reply_text(f"Не нашёл цену для «{sym}» 😕")
    await update.message.reply_text(f"💰 {sym.upper()} = {price} USD")

async def exchange(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 3:
        return await update.message.reply_text(
            "Использование: /exchange <from> <to> <amount>\n"
            "Пример: /exchange btc usdt 0.5"
        )
    frm, to, amt_str = map(str.lower, context.args)
    try:
        amt = float(amt_str)
    except ValueError:
        return await update.message.reply_text("Сумма должна быть числом, например 0.5")
    price_from = get_price(frm)
    price_to = get_price(to)
    if price_from is None or price_to is None:
        return await update.message.reply_text("Ошибка: проверьте символы монет.")
    result = amt * price_from / price_to
    await update.message.reply_text(f"{amt} {frm.upper()} ≈ {result:.6f} {to.upper()}")


def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    # старт и начало
    app.add_handler(CommandHandler("start", initial_handler))
    app.add_handler(CallbackQueryHandler(initial_handler, pattern="^start$"))
    app.add_handler(MessageHandler(filters.Regex("^🔰 Начать$"), initial_handler))
    # меню
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    # кошелёк
    app.add_handler(CallbackQueryHandler(wallet_menu, pattern="^wallet_menu$"))
    app.add_handler(CallbackQueryHandler(wallet_balance, pattern="^wallet_balance$"))
    app.add_handler(CallbackQueryHandler(wallet_deposit, pattern="^wallet_deposit$"))
    app.add_handler(CallbackQueryHandler(deposit_office_handler, pattern="^deposit_office_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, deposit_amount_handler))
    app.add_handler(CallbackQueryHandler(wallet_withdraw, pattern="^wallet_withdraw$"))
    # другие разделы
    app.add_handler(CallbackQueryHandler(exchange_menu, pattern="^exchange_menu$"))
    app.add_handler(CallbackQueryHandler(p2p_menu, pattern="^p2p_menu$"))
    app.add_handler(CallbackQueryHandler(account_menu, pattern="^account_menu$"))
    # команды
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("rate", rate))
    app.add_handler(CommandHandler("exchange", exchange))

    print("Бот запущен…")
    app.run_polling()

if __name__ == "__main__":
    main()
