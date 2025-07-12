import os
import json
import requests
import schedule
import time
import threading
import asyncio  # <-- ✅ THIS LINE IS REQUIRED
from datetime import datetime
from collections import deque
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


# === CONFIG ===
TELEGRAM_TOKEN = '7741029568:AAGhAm5FEYTcVzZuPPMrOa5P9W2_-bFQq50'
NEWSAPI_KEY = 'fbe66da57eef4b0993a13c3572457d06'
SECOND_BOT_TOKEN = '7635757636:AAFwFOjtKWF3XFZ0VYOEs8ICMnbVhLHWf_8'
NOTIFY_CHAT_ID = '897358644'
SUBSCRIBERS_FILE = "subscribed_users.json"

# === LOAD & SAVE SUBSCRIBERS ===
def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
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

# === REMEMBER URL FUNCTION ===
def remember_url(url):
    if url not in sent_news_urls:
        sent_news_urls.add(url)
        sent_news_deque.append(url)
        if len(sent_news_deque) == sent_news_deque.maxlen:
            oldest = sent_news_deque.popleft()
            sent_news_urls.discard(oldest)

# === FETCH NEWS ===
def get_all_financial_news():
    query = (
        "finance OR stock market OR inflation OR interest rates OR "
        "bonds OR central bank OR RBI OR Fed OR crypto OR bitcoin OR ethereum OR "
        "tariffs OR monetary policy OR fiscal policy OR economy OR GDP OR recession"
    )
    today_str = datetime.utcnow().strftime("%Y-%m-%d")  # Use UTC date

    url = (
        f"https://newsapi.org/v2/everything?"
        f"q={query}&"
        f"from={today_str}&"  # <-- Filter from today's date
        f"language=en&"
        f"pageSize=5&"
        f"sortBy=publishedAt&"
        f"apiKey={NEWSAPI_KEY}"
    )

    response = requests.get(url)
    articles = response.json().get("articles", [])

    if not articles:
        return None

    message = "📰 *Latest Financial News (Live):*\n\n"
    new_found = False

    for a in articles:
        article_url = a.get("url")
        if article_url in sent_news_urls:
            continue

        title = a.get("title", "No Title")
        description = a.get("description", "")
        content = a.get("content", "")
        source = a.get("source", {}).get("name", "")
        published = a.get("publishedAt", "")[:10]

        message += (
            f"📌 *{title}*\n"
            f"📰 _{source}_ | 🗓️ {published}\n\n"
            f"{description}\n\n"
            f"📖 _{content}_\n"
            f"🔗 [Read more]({article_url})\n"
            f"━━━━━━━━━━━━━━━\n"
        )

        remember_url(article_url)
        new_found = True

    return message if new_found else None

# === SEND NEWS TO USER ===
async def send_daily_update(chat_id):
    try:
        news = get_all_financial_news()
        print(f"✅ Sending update to {chat_id}")
        if news:
            await main_bot.send_message(
                chat_id=chat_id,
                text=news,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        else:
            print("⚠️ No new news to send.")
    except Exception as e:
        print("❌ Update error:", e)

# === /start COMMAND ===
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    username = f"@{user.username}" if user.username else user.first_name

    if user_id not in subscribed_users:
        subscribed_users.add(user_id)
        save_subscribers(subscribed_users)

    await update.message.reply_text("✅ You are now subscribed to finance updates!")
    await update.message.reply_text("📡 Sending the latest news...")
    await send_daily_update(chat_id=user_id)

    try:
        await notify_bot.send_message(
            chat_id=NOTIFY_CHAT_ID,
            text=f"📢 New user started the bot:\n👤 Name: {full_name}\n🔹 Username: {username}\n🆔 User ID: `{user_id}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        print("❌ Error notifying admin:", e)

# === /update COMMAND ===
async def manual_update(update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "unknown"
    await update.message.reply_text("📡 Sending latest updates...")
    await send_daily_update(chat_id=user_id)

    try:
        await notify_bot.send_message(
            chat_id=NOTIFY_CHAT_ID,
            text=f"📢 Update triggered by `{username}` (ID: `{user_id}`)",
            parse_mode="Markdown"
        )
    except Exception as e:
        print("❌ Notify failed:", e)

# === SCHEDULER ===
def run_schedule():
    def job():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def send_to_all():
            print(f"⏰ Running schedule job at {time.ctime()}")
            for user_id in subscribed_users:
                print(f"🔁 Sending news to {user_id}")
                await send_daily_update(chat_id=user_id)

        loop.run_until_complete(send_to_all())
        loop.close()

    schedule.every(5).minutes.do(job)

    def schedule_loop():
        while True:
            schedule.run_pending()
            time.sleep(60)

    threading.Thread(target=schedule_loop, name="schedule_loop", daemon=True).start()

# === MAIN ===
def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("update", manual_update))

    run_schedule()
    app.run_polling()

if __name__ == "__main__":
    main()
