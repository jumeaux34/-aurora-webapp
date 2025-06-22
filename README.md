# Aurora Crypto Bot

Simple Telegram bot with a Web App interface for cryptocurrency operations.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set environment variables:
   - `BOT_TOKEN` – Telegram bot token.
   - `ADMIN_CHAT_ID` – chat ID that receives deposit requests.
   - `WEBAPP_URL` – (optional) URL to `index.html` if hosted elsewhere.
3. Run the bot:
   ```bash
   python bot.py
   ```

The Web App can be opened with the `/start` command inside Telegram.
