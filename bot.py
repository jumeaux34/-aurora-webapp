from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    WebAppInfo
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)
import requests
import json
from collections import defaultdict

# --- Хранилище балансов пользователей: chat_id → данные ---
user_balances: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))

# --- Конфигурация ---
ADMIN_CHAT_ID = 7736404289
BOT_TOKEN = "7612093789:AAFmp7EeR9iIEguG3zG6_6ImrzPd5L30c9w"
WEBAPP_URL = "https://jumeaux34.github.io/aurora-webapp/index.html"  # ваш главный WebApp

# --- Вспомогательная функция для получения курса ---
def get_price(symbol: str) -> float | None:
    try:
        r = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": symbol.lower(), "vs_currencies": "usd"}, timeout=5
        )
        data = r.json()
        return data.get(symbol.lower(), {}).get("usd")
    except:
        return None

# --- /start: открывает весь интерфейс через WebApp ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [[InlineKeyboardButton(
        "🚀 Открыть Aurora App",
        web_app=WebAppInfo(url=WEBAPP_URL)
    )]]
    await update.message.reply_text(
        "Добро пожаловать в AuroraCryptoBot!\nИспользуйте кнопку ниже, чтобы загрузить полностью веб-интерфейс:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

# --- Приём данных из WebApp (JSON) ---
async def webapp_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    payload = json.loads(update.message.web_app_data.data)
    action = payload.get("action")
    user_id = update.effective_chat.id

    # Пример обработки: action=deposit, office, amount
    if action == "deposit":
        office = payload.get("office")
        amount = payload.get("amount")
        # Уведомляем администратора
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(f"🔔 Новая заявка на пополнение WebApp:\n"
                  f"Пользователь: {user_id}\n"
                  f"Офис: {office}\n"
                  f"Сумма: {amount}"),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✉️ Связаться", url=f"tg://user?id={user_id}")]
            ])
        )
        # Ответ пользователю
        await update.message.reply_text("✅ Ваша заявка на пополнение отправлена через WebApp.")
    # Здесь можно добавить другие action: exchange, withdraw и т.д.
    else:
        await update.message.reply_text("⚠️ Неизвестное действие из WebApp.")

# --- Обработчики команд (резервно) ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start — загрузить веб-интерфейс\n"
        "/help — помощь"
    )

# --- Точка входа ---
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Команды
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("help", help_command))
    # WebApp-data
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, webapp_handler))

    print("AuroraCryptoBot запущен…")
    app.run_polling()

if __name__ == "__main__":
    main()
