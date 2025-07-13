import os
import json
import requests
import asyncio
from datetime import datetime, timezone, timedelta
from collections import deque
from telegram import Bot
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# === CONFIG ===
TELEGRAM_TOKEN = '7741029568:AAGhAm5FEYTcVzZuPPMrOa5P9W2_-bFQq50'
NEWSAPI_KEY = 'fbe66da57eef4b0993a13c3572457d06'
SECOND_BOT_TOKEN = '7635757636:AAFwFOjtKWF3XFZ0VYOEs8ICMnbVhLHWf_8'
NOTIFY_CHAT_ID = '897358644'
SUBSCRIBERS_FILE = "subscribed_users.json"

# === GLOBALS ===
subscribed_users = set()
sent_news_deque = deque(maxlen=500)
sent_news_urls = set()
main_bot = Bot(token=TELEGRAM_TOKEN)
notify_bot = Bot(token=SECOND_BOT_TOKEN)

# === Load/Save Subscribers ===
def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(list(subscribers), f)

subscribed_users = load_subscribers()

# === Utility ===
def remember_url(url):
    if url not in sent_news_urls:
        sent_news_urls.add(url)
        sent_news_deque.append(url)
        if len(sent_news_deque) == sent_news_deque.maxlen:
            oldest = sent_news_deque.popleft()
            sent_news_urls.discard(oldest)

# === News Sending ===
async def send_daily_update(chat_id):
    try:
        query = (
            "finance OR stock market OR inflation OR interest rates OR "
            "bonds OR central bank OR RBI OR Fed OR crypto OR bitcoin OR ethereum OR "
            "tariffs OR monetary policy OR fiscal policy OR economy OR GDP OR recession"
        )

        now = datetime.now(timezone.utc)
        from_time = now - timedelta(hours=24)
        from_time_str = from_time.isoformat()

        url = (
            f"https://newsapi.org/v2/everything?"
            f"q={query}&"
            f"from={from_time_str}&"
            f"language=en&"
            f"pageSize=10&"
            f"sortBy=publishedAt&"
            f"apiKey={NEWSAPI_KEY}"
        )

        response = requests.get(url)
        articles = response.json().get("articles", [])
        print(f"⏰ Checking news at {now} — {len(articles)} articles found")

        if not articles:
            return

        sent_count = 0
        for a in articles:
            article_url = a.get("url")
            if article_url in sent_news_urls:
                continue

            title = a.get("title", "No Title")
            description = a.get("description", "No summary available.")
            source = a.get("source", {}).get("name", "")
            published = a.get("publishedAt", "")[:10]

            message = (
                f"📌 *{title}*\n"
                f"📰 _{source}_ | 🗓️ {published}\n\n"
                f"🧠 *Summary:* {description.strip()}\n\n"
                f"🔗 [Read Full Article]({article_url})"
            )

            await main_bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )

            remember_url(article_url)
            sent_count += 1

    except Exception as e:
        print("❌ Update error:", e)

# === Command Handlers ===
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

# === Async Scheduler (no threading) ===
async def run_schedule_async():
    while True:
        print(f"⏰ Running schedule job at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        for user_id in subscribed_users:
            print(f"🔁 Sending news to {user_id}")
            try:
                await send_daily_update(chat_id=user_id)
            except Exception as e:
                print(f"❌ Error sending to {user_id}: {e}")
        await asyncio.sleep(300)  # Wait 5 minutes

# === Main Entry Point ===
async def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("update", manual_update))

    # Start background scheduler
    asyncio.create_task(run_schedule_async())

    print("✅ Bot started. Listening for commands and sending scheduled news...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
