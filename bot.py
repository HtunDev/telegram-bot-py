from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
import httpx
import os
import time
import logging
import sqlite3

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.getenv("OPENAI_API_KEY")

# ===== LOGGING =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ===== DATABASE (SQLite) =====
conn = sqlite3.connect("memory.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    user_id INTEGER,
    role TEXT,
    content TEXT
)
""")
conn.commit()

MAX_HISTORY = 6  # number of messages to keep

# ===== RATE LIMIT =====
user_last_message_time = {}
COOLDOWN = 3  # seconds

# ===== FUNCTIONS =====

def get_user_history(user_id):
    cursor.execute(
        "SELECT role, content FROM messages WHERE user_id=? ORDER BY rowid DESC LIMIT ?",
        (user_id, MAX_HISTORY)
    )
    rows = cursor.fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]

def save_message(user_id, role, content):
    cursor.execute(
        "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content)
    )
    conn.commit()

# ===== HANDLERS =====

async def start(update, context):
    await update.message.reply_text("Hi! I’m your AI bot 🤖 (with memory)")

async def chat(update, context):
    user_id = update.message.from_user.id
    user_message = update.message.text

    # ===== RATE LIMIT =====
    now = time.time()
    last_time = user_last_message_time.get(user_id, 0)

    if now - last_time < COOLDOWN:
        await update.message.reply_text("⏳ Slow down bro 😅")
        return

    user_last_message_time[user_id] = now

    # ===== LOAD MEMORY =====
    history = get_user_history(user_id)
    history.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "qwen/qwen3.6-plus-preview:free",
        "messages": history
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(API_URL, headers=headers, json=payload)
            data = response.json()

        ai_reply = data.get('choices', [{}])[0].get('message', {}).get('content', "No response")

        # ===== SAVE MEMORY =====
        save_message(user_id, "user", user_message)
        save_message(user_id, "assistant", ai_reply)

        await update.message.reply_text(ai_reply)

    except Exception as e:
        logging.error(f"Error for user {user_id}: {str(e)}")
        await update.message.reply_text("⚠️ Something went wrong. Try again later.")

# ===== APP =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

if __name__ == "__main__":
    app.run_polling()