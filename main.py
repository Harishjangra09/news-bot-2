import os
import json
import requests
import asyncio
import re
from datetime import datetime, timezone, timedelta
from collections import deque
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Application
import logging
from dotenv import load_dotenv

load_dotenv()

# === BOT TOKENS ===
MAIN_NEWS_BOT_TOKEN = os.getenv("MAIN_NEWS_BOT_TOKEN")  # First bot: sends news updates
SUB_NOTIFY_BOT_TOKEN = os.getenv("SUB_NOTIFY_BOT_TOKEN")  # Second bot: for admin subscribe alert
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
SUBSCRIBERS_FILE = os.getenv("SUBSCRIBERS_FILE", "subscribed_users.json")

# === LOGGING ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === GLOBALS ===
subscribed_users = set()
sent_news_deque = deque(maxlen=500)
sent_news_urls = set()

main_bot = Bot(token=MAIN_NEWS_BOT_TOKEN)
notify_bot = Bot(token=SUB_NOTIFY_BOT_TOKEN)

# === HELPERS ===
def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(subscribers), f)

def remember_url(url):
    if url not in sent_news_urls:
        sent_news_urls.add(url)
        sent_news_deque.append(url)
        if len(sent_news_deque) == sent_news_deque.maxlen:
            oldest = sent_news_deque.popleft()
            sent_news_urls.discard(oldest)

def safe_md(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters."""
    escape_chars = r"_*[]()~`>#+=|{}.!-"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text or "")

# === CATEGORY TAGS ===
TOP_COMPANIES = ["Apple", "Microsoft", "Amazon", "Tesla", "Google", "Meta", "Nvidia", "Netflix", "Intel", "IBM"]
CRYPTO_KEYWORDS = ["crypto", "bitcoin", "ethereum", "blockchain", "altcoin", "Web3", "DeFi", "Binance", "Coinbase"]
ECONOMY_KEYWORDS = ["interest rate", "GDP", "inflation", "recession", "central bank", "Fed", "RBI", "tariff", "fiscal"]
COUNTRY_KEYWORDS = {
    "🇺🇸": ["US", "America", "United States", "Fed"],
    "🇨🇳": ["China", "Beijing"],
    "🇯🇵": ["Japan", "Tokyo", "Yen"],
    "🇩🇪": ["Germany", "Berlin", "Bundesbank"],
    "🇮🇳": ["India", "Delhi", "Mumbai", "RBI"],
    "🇬🇧": ["UK", "Britain", "London", "BOE"],
    "🇫🇷": ["France", "Paris"],
    "🇮🇹": ["Italy", "Rome"],
    "🇧🇷": ["Brazil", "Brasilia", "Bovespa"],
    "🇨🇦": ["Canada", "Ottawa"]
}

def classify_article(title, description):
    text = (title + " " + description).lower()
    if any(company.lower() in text for company in TOP_COMPANIES):
        return "🏢 *Top Company News*"
    elif any(keyword in text for keyword in CRYPTO_KEYWORDS):
        return "🪙 *Crypto Market*"
    elif any(keyword in text for keyword in ECONOMY_KEYWORDS):
        for flag, keywords in COUNTRY_KEYWORDS.items():
            if any(k.lower() in text for k in keywords):
                return f"{flag} *Economic News*"
        return "🌍 *Global/Economic*"
    else:
        return "📰 *Other News*"

# === FETCH AND SEND NEWS ===
async def send_news_update(chat_id):
    try:
        query = (
            "Apple OR Microsoft OR Amazon OR Tesla OR Nvidia OR "
            "Bitcoin OR Ethereum OR crypto OR blockchain OR "
            "inflation OR interest rates OR GDP OR recession OR Fed OR RBI OR "
            "United States OR China OR Japan OR Germany OR India OR UK OR France OR Italy OR Brazil OR Canada"
        )

        now = datetime.now(timezone.utc)
        from_time = now - timedelta(hours=24)
        url = (
            f"https://newsapi.org/v2/everything?"
            f"q={query}&"
            f"from={from_time.isoformat()}&to={now.isoformat()}&"
            f"language=en&sortBy=publishedAt&pageSize=20&"
            f"apiKey={NEWSAPI_KEY}"
        )

        response = requests.get(url)
        articles = response.json().get("articles", [])
        logger.info(f"⏰ Checked at {now}, {len(articles)} articles found")

        if not articles:
            await main_bot.send_message(chat_id=chat_id, text="⚠️ No new important news in last 24 hours.")
            return

        for a in articles:
            article_url = a.get("url")
            if article_url in sent_news_urls:
                continue

            title = safe_md(a.get("title", "No Title"))
            description = safe_md((a.get("description") or "").split(".")[0])
            source = safe_md(a.get("source", {}).get("name", ""))
            date = a.get("publishedAt", "")[:10]
            category = safe_md(classify_article(title, description))

            message = (
                f"{category}\n"
                f"📌 *{title}*\n"
                f"📰 _{source}_ \\| 🗓️ {date}\n\n"
                f"🧠 *Summary:* {description}\n\n"
                f"🔗 [Read Full Article]({article_url})"
            )

            await main_bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="MarkdownV2",
                disable_web_page_preview=True
            )
            remember_url(article_url)

    except Exception as e:
        logger.error(f"❌ Error sending update: {e}")

# === COMMANDS ===
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    if user_id not in subscribed_users:
        subscribed_users.add(user_id)
        save_subscribers(subscribed_users)

    await update.message.reply_text("✅ Subscribed to finance & global news alerts!")
    await send_news_update(chat_id=user_id)

    try:
        full_name = f"{user.first_name} {user.last_name or ''}".strip()
        username = f"@{user.username}" if user.username else user.first_name
        await notify_bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📢 New subscriber:\n👤 {full_name}\n🔹 {username}\n🆔 `{user_id}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Notify failed: {e}")

async def update_command(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📡 Fetching fresh news...")
    await send_news_update(chat_id=update.effective_user.id)

# === ERROR HANDLER ===
async def error_handler(update, context):
    logger.error(f"⚠️ Error: {context.error}", exc_info=context.error)

# === SCHEDULER ===
async def news_scheduler():
    while True:
        logger.info("⏰ Running scheduled update")
        for user_id in subscribed_users:
            try:
                await send_news_update(chat_id=user_id)
            except Exception as e:
                logger.error(f"❌ Failed for {user_id}: {e}")
        await asyncio.sleep(600)  # every 10 minutes

# === MAIN FUNCTION ===
def main():
    global subscribed_users
    subscribed_users = load_subscribers()

    app = ApplicationBuilder().token(MAIN_NEWS_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("update", update_command))
    app.add_error_handler(error_handler)

    async def on_startup(app):
        await app.bot.delete_webhook()
        asyncio.create_task(news_scheduler())

    app.post_init = on_startup
    app.run_polling()

if __name__ == "__main__":
    main()
