# 💱 UfaSwap — Telegram-бот для заявок (Python 3.13)
# Версия 3.1 — стабильная и финальная
# ✅ Исправлен подсчёт суммы в отчёте
# ✅ Добавлено сообщение клиенту после проведения
# ✅ Исправлена ошибка Message is not modified
# ✅ Добавлена команда /report (только для администратора)
# ✅ Защита от повторных нажатий "Проведена"/"Не проведена"
# ✅ Ежедневный автоотчёт + ручной отчёт
# ✅ Кнопка "Курс" — биржа +0.85% с кэш-фолбэком

import os
import asyncio
import logging
import time
import traceback
import uuid
import csv
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from dotenv import load_dotenv
import requests

from telegram import (
    Bot,
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.constants import ParseMode

# ───────────────────────────────
# ⚙️ Настройки окружения
# ───────────────────────────────
load_dotenv()
os.makedirs("logs", exist_ok=True)

# 🔇 Настройка логов
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("UfaSwap")

file_handler = logging.FileHandler("logs/errors.log", encoding="utf-8")
file_handler.setLevel(logging.ERROR)
file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(file_handler)

# ───────────────────────────────
# 🔑 Основные параметры
# ───────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))
ALLOWED_OFFICES = [x.strip() for x in os.getenv("ALLOWED_OFFICES", "Уфа, Верхнеторговая 4").split(";")]
MIN_DEPOSIT_AMOUNT = float(os.getenv("MIN_DEPOSIT_AMOUNT", "50000"))
MAX_DEPOSIT_AMOUNT = float(os.getenv("MAX_DEPOSIT_AMOUNT", "20000000"))
USER_COOLDOWN_SEC = 60
ABCEX_API_KEY = os.getenv("ABCEX_API_KEY")

# Курс
RATE_MARKUP_PCT = float(os.getenv("RATE_MARKUP_PCT", "0.85"))  # +0.85%
RATE_CACHE_FILE = "logs/last_rate.json"
RATE_CACHE_MAX_AGE_SEC = 60 * 60  # кэш валиден 60 минут
ABCEX_URL = "https://gateway.abcex.io/api/v2/exchange/public/instrument/rates"
MARKET_CODE = "BTCUSDT"

if not BOT_TOKEN or not ADMIN_CHAT_ID:
    raise RuntimeError("❌ Не указан BOT_TOKEN или ADMIN_CHAT_ID в .env")

if not ABCEX_API_KEY:
    logger.warning("⚠️ ABCEX_API_KEY не указан в .env - запросы к API могут не работать")

bot = Bot(token=BOT_TOKEN)
user_state = {}
last_submission = {}

# ───────────────────────────────
# 🧩 Утилиты
# ───────────────────────────────
def fmt_rub(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ") + " ₽"

def generate_order_id() -> str:
    return uuid.uuid4().hex[:8].upper()

def escape_md(text: str) -> str:
    if not text:
        return ""
    escape_chars = "_*[]()~`>#+-=|{}.!<>"
    for ch in escape_chars:
        text = text.replace(ch, f"\\{ch}")
    return text

def save_order_to_csv(order_id: str, user_id: int, office: str, amount: float):
    """Сохраняет заявку в logs/orders.csv"""
    file_path = "logs/orders.csv"
    file_exists = os.path.isfile(file_path)
    with open(file_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter=";")
        if not file_exists:
            writer.writerow(["Дата и время", "ID заявки", "ID пользователя", "Офис", "Сумма"])
        writer.writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            order_id,
            user_id,
            office,
            str(int(amount)),  # сохраняем как число
        ])

async def safe_send_message(chat_id, text, parse_mode=None, reply_markup=None):
    """Надёжная отправка с 3 попытками"""
    for attempt in range(3):
        try:
            return await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(1.5)
            else:
                logger.error(f"Ошибка при отправке: {e}")

# ───────────────────────────────
# 📡 Курс: запрос + кэш-фолбэк
# ───────────────────────────────
def _load_cached_rate():
    try:
        if not os.path.exists(RATE_CACHE_FILE):
            return None
        with open(RATE_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if time.time() - data.get("ts", 0) <= RATE_CACHE_MAX_AGE_SEC:
            return data
    except Exception as e:
        logger.warning(f"Не удалось прочитать кэш курса: {e}")
    return None

def _save_cached_rate(base_price: float, final_price: float):
    try:
        with open(RATE_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "base": base_price, "final": final_price}, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Не удалось сохранить кэш курса: {e}")

def get_usd_rub_with_markup() -> tuple[dict | None, str]:
    """
    Возвращает ({buy_price, sell_price}, источник), где источник: 'online' или 'cache'.
    """
    headers = {"accept": "application/xml"}
    # if ABCEX_API_KEY:
    #     headers["Authorization"] = f"Bearer {ABCEX_API_KEY}"
    
    # Логирование запроса
    logger.info(f"🔍 Отправляем запрос к ABCEX API:")
    logger.info(f"   URL: {ABCEX_URL}")
    logger.info(f"   Headers: {headers}")
    logger.info(f"   Timeout: 5 сек")

    # Несколько попыток запроса в случае 5xx
    for attempt in range(3):
        try:
            logger.info(f"   Попытка #{attempt + 1}/3")
            resp = requests.get(ABCEX_URL, headers=headers, timeout=5)
            logger.info(f"   Ответ: HTTP {resp.status_code}")
            logger.info(f"   Тело ответа: {resp.text[:500]}...")
            if resp.status_code == 200:
                # Парсинг XML
                try:
                    root = ET.fromstring(resp.text)
                    logger.info(f"   Парсинг XML: корневой элемент '{root.tag}' с {len(root)} элементами")
                    
                    usdt_to_rub_price = None
                    rub_to_usdt_price = None
                    
                    for item in root.findall('item'):
                        from_currency = item.find('from').text if item.find('from') is not None else ""
                        to_currency = item.find('to').text if item.find('to') is not None else ""
                        out_price = float(item.find('out').text) if item.find('out') is not None else 0
                        
                        logger.info(f"   Проверяем: {from_currency} -> {to_currency}, цена: {out_price}")
                        
                        if from_currency == "USDT" and to_currency == "RUB":
                            usdt_to_rub_price = out_price
                            logger.info(f"   ✅ Найден курс USDT->RUB: {usdt_to_rub_price}")
                        elif from_currency == "RUB" and to_currency == "USDT":
                            rub_to_usdt_price = out_price
                            logger.info(f"   ✅ Найден курс RUB->USDT: {rub_to_usdt_price}")
                    
                    if usdt_to_rub_price and rub_to_usdt_price:
                        # Применяем наценку 0.85%
                        # usdt_to_rub_price = цена продажи USDT (сколько RUB за 1 USDT)
                        # rub_to_usdt_price = цена покупки USDT (сколько USDT за 1 RUB)
                        sell_price = round(usdt_to_rub_price * (1 + RATE_MARKUP_PCT / 100), 2)  # Продажа USDT за RUB
                        buy_price = round(1 / rub_to_usdt_price * (1 + RATE_MARKUP_PCT / 100), 2)  # Покупка USDT за RUB
                        
                        logger.info(f"   ✅ Курсы с наценкой: покупка={buy_price}, продажа={sell_price}")
                        
                        # Сохраняем в кэш
                        _save_cached_rate(usdt_to_rub_price, buy_price)
                        
                        return {"buy_price": buy_price, "sell_price": sell_price}, "online"
                    else:
                        logger.error("Не найдены курсы USDT/RUB в XML ответе")
                        break
                        
                except ET.ParseError as e:
                    logger.error(f"Ошибка парсинга XML: {e}")
                    break
            else:
                logger.error(f"ABCEX HTTP {resp.status_code}: {resp.text}")
                if 500 <= resp.status_code < 600 and attempt < 2:
                    time.sleep(0.6)
                    continue
                break
        except Exception as e:
            logger.error(f"Ошибка запроса ABCEX: {e}")
            if attempt < 2:
                time.sleep(0.6)
                continue
            break

    logger.warning("   ❌ Все попытки запроса к ABCEX API неудачны, используем кэш")
    cached = _load_cached_rate()
    if cached:
        logger.info(f"   📦 Используем кэшированный курс: {cached['final']}")
        return {"buy_price": cached['final'], "sell_price": cached['final']}, "cache"
    logger.error("   🚫 Кэш пуст, курс недоступен")
    return None, ""

# ───────────────────────────────
# 📊 Отчёты
# ───────────────────────────────
def get_daily_report() -> str:
    file_path = "logs/orders.csv"
    if not os.path.exists(file_path):
        return "📂 Отчёт недоступен: файл логов отсутствует."

    today = datetime.now().strftime("%Y-%m-%d")
    total_sum = 0
    total_count = 0

    with open(file_path, "r", encoding="utf-8") as f:
        next(f, None)
        for line in f:
            if line.startswith(today):
                parts = line.strip().split(";")
                if len(parts) >= 5:
                    try:
                        total_sum += float(parts[4])
                        total_count += 1
                    except ValueError:
                        pass

    if total_count == 0:
        return f"📅 *Отчёт за {today}*\n\nПока нет проведённых заявок."

    return (
        f"📅 *Отчёт за {today}*\n\n"
        f"Количество заявок: *{total_count}*\n"
        f"Общая сумма: *{fmt_rub(total_sum)}*\n\n"
        "✅ Отчёт включает только проведённые заявки."
    )

async def send_daily_report():
    await safe_send_message(ADMIN_CHAT_ID, get_daily_report(), parse_mode="Markdown")

# ───────────────────────────────
# 💬 Основная логика
# ───────────────────────────────
async def handle_update(update: Update):
    # === Callback (для менеджера)
    if update.callback_query:
        query = update.callback_query
        data = query.data
        message = query.message
        user_id = query.from_user.id

        # Обработка подтверждения заявки пользователем
        if data.startswith("confirm:"):
            order_id = data.split(":")[1]
            state = user_state.get(user_id, {})
            
            if state.get("stage") == "confirmation" and state.get("order_id") == order_id:
                # Отправляем заявку менеджеру
                office = state["office"]
                operation_type = state.get("operation_type", "deposit")
                amount = state["amount"]
                usdt_amount = state["usdt_amount"]
                rub_amount = state.get("rub_amount", amount)
                rates = state["rates"]
                
                if operation_type == "deposit":
                    manager_text = (
                        f"🚨 *Новая заявка на пополнение Ufa Swap*\n\n"
                        f"🆔 Номер заявки: *{order_id}*\n"
                        f"👤 Пользователь: [{user_id}](tg://user?id={user_id})\n"
                        f"🏢 Офис: *{escape_md(office)}*\n"
                        f"💵 Сумма пополнения: *{fmt_rub(rub_amount)}*\n"
                        f"🪙 Получит USDT: *{usdt_amount:.6f} USDT*\n"
                        f"📊 Курс покупки: *{fmt_rub(rates['buy_price'])}*"
                    )
                else:  # withdrawal
                    manager_text = (
                        f"🚨 *Новая заявка на вывод Ufa Swap*\n\n"
                        f"🆔 Номер заявки: *{order_id}*\n"
                        f"👤 Пользователь: [{user_id}](tg://user?id={user_id})\n"
                        f"🏢 Офис: *{escape_md(office)}*\n"
                        f"🪙 Количество USDT: *{usdt_amount:.6f} USDT*\n"
                        f"💵 Получит рублей: *{fmt_rub(rub_amount)}*\n"
                        f"📊 Курс продажи: *{fmt_rub(rates['sell_price'])}*"
                    )

                kb_admin = InlineKeyboardMarkup([
                    [InlineKeyboardButton("📞 Связаться с клиентом", url=f"tg://user?id={user_id}")],
                    [
                        InlineKeyboardButton("✅ Проведена", callback_data=f"done:{order_id}"),
                        InlineKeyboardButton("❌ Не проведена", callback_data=f"cancel:{order_id}")
                    ]
                ])

                await safe_send_message(ADMIN_CHAT_ID, manager_text, "Markdown", kb_admin)
                
                # Обновляем сообщение пользователю
                await message.edit_text(
                    "✅ *Заявка отправлена менеджеру!*\n\n"
                    "Менеджер получил уведомление и свяжется с вами в ближайшее время.",
                    parse_mode="Markdown"
                )
                
                # Добавляем кнопку "Новая заявка"
                kb_user = ReplyKeyboardMarkup([[KeyboardButton("🔄 Новая заявка")]], resize_keyboard=True)
                await safe_send_message(
                    user_id,
                    "Вы можете создать новую заявку, нажав кнопку ниже:",
                    reply_markup=kb_user
                )
                
                # Очищаем состояние пользователя
                user_state.pop(user_id, None)
                last_submission[user_id] = time.time()
                
                await query.answer("Заявка отправлена! ✅")
                return

        # Обработка отмены заявки пользователем
        if data.startswith("cancel_order:"):
            order_id = data.split(":")[1]
            state = user_state.get(user_id, {})
            
            if state.get("stage") == "confirmation" and state.get("order_id") == order_id:
                kb_user = ReplyKeyboardMarkup([[KeyboardButton("🔄 Новая заявка")]], resize_keyboard=True)
                
                await message.edit_text(
                    "❌ *Заявка отменена*",
                    parse_mode="Markdown"
                )
                await safe_send_message(
                    user_id,
                    "Вы можете создать новую заявку, нажав кнопку ниже:",
                    reply_markup=kb_user
                )
                
                # Очищаем состояние пользователя
                user_state.pop(user_id, None)
                
                await query.answer("Заявка отменена ❌")
                return

        # Обработка выбора типа операции
        if data.startswith("op_type:"):
            parts = data.split(":")
            if len(parts) >= 3:
                operation_type = parts[1]  # deposit или withdrawal
                callback_user_id = int(parts[2])
                
                if callback_user_id == user_id:
                    state = user_state.get(user_id, {})
                    if state.get("stage") == "operation_type":
                        state["operation_type"] = operation_type
                        state["stage"] = "amount"
                        
                        if operation_type == "deposit":
                            await message.edit_text(
                                f"💰 *Пополнение*\n\n"
                                f"Введите сумму пополнения (от {fmt_rub(MIN_DEPOSIT_AMOUNT)} до {fmt_rub(MAX_DEPOSIT_AMOUNT)}).\n"
                                f"_Пример:_ 50000",
                                parse_mode="Markdown"
                            )
                        else:  # withdrawal
                            await message.edit_text(
                                f"💸 *Вывод USDT*\n\n"
                                f"Введите количество USDT для вывода.\n"
                                f"_Пример:_ 100.5",
                                parse_mode="Markdown"
                            )
                        
                        await query.answer("Тип операции выбран ✅")
                        return

        # Обработка callback'ов менеджера (существующая логика)
        if user_id != ADMIN_CHAT_ID:
            await query.answer("🚫 У вас нет прав для этого действия.", show_alert=True)
            return

        # Безопасно извлекаем order_id
        try:
            order_id = data.split(":")[1]
        except IndexError:
            await query.answer("Ошибка: неверный формат данных.", show_alert=True)
            return

        if data.startswith("done:"):
            try:
                await message.edit_text(f"✅ Заявка {order_id} проведена.")
                await query.answer("Заявка проведена ✅")
            except Exception as e:
                if "Message is not modified" in str(e):
                    logger.warning("⚠️ Повторное подтверждение — уже проведена.")
                else:
                    logger.error(e)
                return

            # парсим данные из исходного текста заявки
            lines = message.text.split("\n")
            user_line = next((l for l in lines if "👤" in l), "")
            office_line = next((l for l in lines if "🏢" in l), "")
            # Ищем сумму пополнения (новый формат использует 💵)
            amount_line = next((l for l in lines if "💵" in l or "💰" in l), "")

            try:
                user_id = int(user_line.split(":")[1].strip().split("]")[0].replace("[", ""))
            except Exception:
                user_id = 0

            office = office_line.split(":", 1)[1].strip() if ":" in office_line else "?"
            amount_text = amount_line.split(":", 1)[1].strip() if ":" in amount_line else "0"
            try:
                amount = float(amount_text.replace("₽", "").replace(" ", "").replace(" ", ""))
            except ValueError:
                amount = 0

            save_order_to_csv(order_id, user_id, office, amount)

            # 💬 Сообщение клиенту
            if user_id:
                await safe_send_message(
                    user_id,
                    "✅ Ваша заявка успешно проведена!\n\n"
                    "Спасибо, что выбрали *Ufa Swap!*\n"
                    "Ждём вас снова!",
                    parse_mode="Markdown",
                )
            return

        elif data.startswith("cancel:"):
            try:
                await message.edit_text(f"❌ Заявка {order_id} не проведена.")
                await query.answer("Заявка отменена ❌")
            except Exception as e:
                if "Message is not modified" not in str(e):
                    logger.error(e)
            return

    # === Обычные сообщения
    if not update.message:
        return

    user_id = update.message.chat_id
    text = (update.message.text or "").strip()

    if update.message.chat.type != "private":
        await safe_send_message(user_id, "⚠️ Этот бот работает только в личных сообщениях.")
        return

    # === Команда /report
    if text.lower() == "/report":
        if user_id != ADMIN_CHAT_ID:
            await safe_send_message(user_id, "⛔ У вас нет прав для этой команды.")
            return
        await safe_send_message(user_id, get_daily_report(), parse_mode="Markdown")
        return

    # === Курс биржи + 0.85%
    if text.lower() in ("курс", "💱 курс", "/rate", "/kurs", "курс обмена"):
        await safe_send_message(user_id, "Получаю актуальный курс, секунду…")
        rates, source = get_usd_rub_with_markup()
        if rates is None:
            await safe_send_message(user_id, "Не удалось получить курс. Повторите попытку позже.")
            return
        suffix = " (онлайн)" if source == "online" else " (по последнему сохранённому курсу)"
        await safe_send_message(
            user_id,
            f"💱 *RUB/USDT Курсы:*{suffix}\n\n"
            f"🟢 *Продажа USDT:* {fmt_rub(rates['buy_price'])}\n",  
            parse_mode="Markdown",
        )
        return

    # === /start
    if text in ("/start", "🔄 Новая заявка"):
        kb = [[KeyboardButton("🚀 Начать")], [KeyboardButton("Курс")]]
        await safe_send_message(
            user_id,
            (
                "👋 *Добро пожаловать в Ufa Swap!*\n\n"
                "💱 Здесь вы можете оставить заявку на пополнение или обмен.\n"
                "🕓 Работаем ежедневно с 10:00 до 22:00.\n\n"
                "Нажмите кнопку ниже, чтобы начать:"
            ),
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
        )
        user_state.pop(user_id, None)
        return

    # === Выбор офиса
    if text == "🚀 Начать":
        kb = [[KeyboardButton(o)] for o in ALLOWED_OFFICES]
        await safe_send_message(
            user_id,
            "🏢 *Выберите офис выдачи:*",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True),
        )
        user_state[user_id] = {"stage": "office"}
        return

    state = user_state.get(user_id)

    # === Этап выбора офиса
    if state and state.get("stage") == "office":
        if text not in ALLOWED_OFFICES:
            await safe_send_message(user_id, "⚠️ Пожалуйста, выберите офис из списка.")
            return
        state["office"] = text
        state["stage"] = "operation_type"
        
        # Кнопки для выбора типа операции
        kb_operation = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Пополнение", callback_data=f"op_type:deposit:{user_id}")],
            [InlineKeyboardButton("💸 Вывод", callback_data=f"op_type:withdrawal:{user_id}")]
        ])
        
        await safe_send_message(
            user_id,
            f"💼 Офис подтверждён: *{escape_md(text)}*\n\n"
            f"Выберите тип операции:",
            parse_mode="Markdown",
            reply_markup=kb_operation
        )
        return

    # === Этап ввода суммы
    if state and state.get("stage") == "amount":
        try:
            amount = float(text.replace(" ", "").replace(",", "."))
        except ValueError:
            await safe_send_message(user_id, "⚠️ Введите корректную сумму.")
            return
        
        operation_type = state.get("operation_type", "deposit")
        
        # Валидация для разных типов операций
        if operation_type == "deposit":
            if not (MIN_DEPOSIT_AMOUNT <= amount <= MAX_DEPOSIT_AMOUNT):
                await safe_send_message(user_id, "⚠️ Сумма вне допустимого диапазона.")
                return
        else:  # withdrawal
            if amount <= 0:
                await safe_send_message(user_id, "⚠️ Количество USDT должно быть больше 0.")
                return

        now = time.time()
        if now - last_submission.get(user_id, 0) < USER_COOLDOWN_SEC:
            wait = int(USER_COOLDOWN_SEC - (now - last_submission[user_id]))
            await safe_send_message(user_id, f"⏳ Подождите {wait} секунд.")
            return

        office = state["office"]
        
        # Получаем актуальный курс для расчета
        rates, source = get_usd_rub_with_markup()
        if rates is None:
            await safe_send_message(user_id, "❌ Не удалось получить курс. Попробуйте позже.")
            return
        
        # Рассчитываем в зависимости от типа операции
        if operation_type == "deposit":
            # Пополнение: сумма в RUB -> количество USDT
            usdt_amount = round(amount / rates['buy_price'], 6)
            rub_amount = amount
        else:
            # Вывод: количество USDT -> сумма в RUB
            usdt_amount = amount
            rub_amount = round(amount * rates['sell_price'], 2)
        
        # Сохраняем данные заявки для подтверждения
        order_id = generate_order_id()
        user_state[user_id] = {
            "stage": "confirmation",
            "office": office,
            "operation_type": operation_type,
            "amount": amount,
            "usdt_amount": usdt_amount,
            "rub_amount": rub_amount,
            "order_id": order_id,
            "rates": rates
        }
        
        # Показываем пользователю расчет и запрашиваем подтверждение
        kb_confirm = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Подтвердить", callback_data=f"confirm:{order_id}"),
                InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_order:{order_id}")
            ]
        ])
        
        if operation_type == "deposit":
            calculation_text = (
                f"💰 *Расчет заявки на пополнение:*\n\n"
                f"🏢 Офис: *{office}*\n"
                f"💵 Сумма пополнения: *{fmt_rub(rub_amount)}*\n"
                f"🪙 Получите USDT: *{usdt_amount:.6f} USDT*\n"
                f"📊 Курс покупки: *{fmt_rub(rates['buy_price'])}*\n\n"
                f"Подтвердить заявку?"
            )
        else:
            calculation_text = (
                f"💸 *Расчет заявки на вывод:*\n\n"
                f"🏢 Офис: *{office}*\n"
                f"🪙 Количество USDT: *{usdt_amount:.6f} USDT*\n"
                # f"💵 Получите рублей: *{fmt_rub(rub_amount)}*\n"
                # f"📊 Курс продажи: *{fmt_rub(rates['sell_price'])}*\n\n"
                f"Подтвердить заявку?"
            )
        
        await safe_send_message(
            user_id,
            calculation_text,
            parse_mode="Markdown",
            reply_markup=kb_confirm
        )
        return

    await safe_send_message(user_id, "Введите /start для начала работы.")

# ───────────────────────────────
# 🚀 Основной цикл polling + автоотчёт
# ───────────────────────────────
async def main():
    print("✅ UfaSwapBot запущен и ожидает заявки...")
    offset = None
    last_report_date = None

    while True:
        try:
            updates = await bot.get_updates(offset=offset, timeout=30)
            for upd in updates:
                await handle_update(upd)
                offset = upd.update_id + 1

            now = datetime.now()
            if last_report_date != now.date() and now.hour >= 22:
                await send_daily_report()
                last_report_date = now.date()

        except Exception as e:
            logger.exception(f"Ошибка polling: {e}")
            await asyncio.sleep(2)

# ───────────────────────────────
# 🔁 Перезапуск при сбоях
# ───────────────────────────────
if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            print("\n🛑 Бот остановлен вручную.")
            break
        except Exception:
            traceback.print_exc()
            print("♻️ Перезапуск через 10 секунд...")
            time.sleep(10)
            continue
