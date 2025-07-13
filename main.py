import os
import json
import requests
import asyncio
from datetime import datetime, timezone, timedelta
from collections import deque
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, Application
from telegram.helpers import escape_markdown
import logging
from dotenv import load_dotenv

load_dotenv()

# === CONFIG ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
SECOND_BOT_TOKEN = os.getenv("SECOND_BOT_TOKEN")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
NOTIFY_CHAT_ID = os.getenv("NOTIFY_CHAT_ID")
SUBSCRIBERS_FILE = os.getenv("SUBSCRIBERS_FILE", "subscribed_users.json")

# === LOGGING ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === LOAD/SAVE SUBSCRIBERS ===
def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    except Exception:
        return set()

def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(subscribers), f)

# === GLOBALS ===
subscribed_users = load_subscribers()
sent_news_deque = deque(maxlen=500)
sent_news_urls = set()

# === BOTS ===
main_bot = Bot(token=TELEGRAM_TOKEN)
notify_bot = Bot(token=SECOND_BOT_TOKEN)

def remember_url(url):
    if url not in sent_news_urls:
        sent_news_urls.add(url)
        sent_news_deque.append(url)
        if len(sent_news_deque) == sent_news_deque.maxlen:
            oldest = sent_news_deque.popleft()
            sent_news_urls.discard(oldest)

# === CATEGORIES ===
TOP_COMPANIES = ["Apple", "Microsoft", "Amazon", "Tesla", "Google", "Meta", "Nvidia", "Netflix", "Intel", "IBM"]
CRYPTO_KEYWORDS = ["crypto", "bitcoin", "ethereum", "blockchain", "altcoin", "Web3", "DeFi", "Binance", "Coinbase"]
ECONOMY_KEYWORDS = ["interest rate", "GDP", "inflation", "recession", "central bank", "Fed", "RBI", "tariff", "fiscal"]

def classify_article(title, description):
    text = (title + " " + description).lower()
    if any(company.lower() in text for company in TOP_COMPANIES):
        return "🏢 *Top Company News*"
    elif any(keyword in text for keyword in CRYPTO_KEYWORDS):
        return "🪙 *Crypto Market*"
    elif any(keyword in text for keyword in ECONOMY_KEYWORDS):
        return "🌍 *Global/Economic*"
    else:
        return "📰 *Other News*"

# === FETCH AND SEND NEWS ===
async def send_daily_update(chat_id):
    try:
        query = (
            "Apple OR Microsoft OR Amazon OR Tesla OR Nvidia OR "
            "Bitcoin OR Ethereum OR crypto OR blockchain OR "
            "inflation OR interest rates OR GDP OR recession OR Fed OR RBI"
        )

        now = datetime.now(timezone.utc)
        from_time = now - timedelta(hours=24)
        from_time_str = from_time.isoformat()

        url = (
            f"https://newsapi.org/v2/everything?"
            f"q={query}&"
            f"from={from_time_str}&"
            f"language=en&"
            f"pageSize=20&"
            f"sortBy=publishedAt&"
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

            title = a.get("title", "No Title")
            description = a.get("description", "No summary available.")
            source = a.get("source", {}).get("name", "")
            published = a.get("publishedAt", "")[:10]
            category = classify_article(title, description)

            simplified = description.strip().split(".")[0]  # first sentence as summary

            # Escape markdown special characters
            title = escape_markdown(title, version=2)
            description = escape_markdown(simplified, version=2)
            source = escape_markdown(source, version=2)
            article_url = escape_markdown(article_url, version=2)
            category = escape_markdown(category, version=2)

            message = (
                f"{category}\n\n"
                f"📌 *{title}*\n"
                f"📰 _{source}_ | 🗓️ {published}\n\n"
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
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    username = f"@{user.username}" if user.username else user.first_name

    if user_id not in subscribed_users:
        subscribed_users.add(user_id)
        save_subscribers(subscribed_users)

    await update.message.reply_text("✅ Subscribed to top finance, company & crypto news!")
    await send_daily_update(chat_id=user_id)

    try:
        await notify_bot.send_message(
            chat_id=NOTIFY_CHAT_ID,
            text=f"📢 New user joined:\n👤 {full_name}\n🔹 {username}\n🆔 `{user_id}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Notify failed: {e}")

async def manual_update(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text("📡 Fetching latest updates...")
    await send_daily_update(chat_id=user_id)

# === SCHEDULE ===
async def scheduled_job(app: Application):
    while True:
        logger.info("⏰ Running scheduled job")
        for user_id in subscribed_users:
            logger.info(f"🔁 Sending to {user_id}")
            await send_daily_update(chat_id=user_id)
        await asyncio.sleep(300)

# === MAIN ===
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("update", manual_update))

    async def on_startup(app):
        app.create_task(scheduled_job(app))

    app.post_init = on_startup
    app.run_polling()

if __name__ == "__main__":
    main()
