from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
import httpx
import os
import time
import logging
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_URL = "https://openrouter.ai/api/v1/chat/completions"
API_KEY = os.getenv("OPENAI_API_KEY")

# ===== LOGGING =====
logging.basicConfig(level=logging.INFO)

# ===== DATABASE =====
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

MAX_HISTORY = 3   # reduce = faster

# ===== RATE LIMIT =====
user_last_message_time = {}
COOLDOWN = 3

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
    await update.message.reply_text("Hi! I’m your AI bot 🤖")

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

    # ===== LOADING MESSAGE =====
    thinking_msg = await update.message.reply_text("⏳ Thinking...")

    # ===== MEMORY =====
    history = get_user_history(user_id)
    history.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "openrouter/free",  # auto free + faster
        "messages": history
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(API_URL, headers=headers, json=payload)
            data = response.json()

        ai_reply = data.get('choices', [{}])[0].get('message', {}).get('content', "No response")

        # ===== SAVE MEMORY =====
        save_message(user_id, "user", user_message)
        save_message(user_id, "assistant", ai_reply)

        # edit thinking message instead of sending new one
        await thinking_msg.edit_text(ai_reply)

    except Exception as e:
        logging.error(str(e))
        await thinking_msg.edit_text("⚠️ AI is slow or busy. Try again.")

# ===== APP =====
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))


def _start_port_for_render_healthcheck():
    """Render Web Services expect a process listening on $PORT; polling alone never binds it."""
    port_raw = os.getenv("PORT")
    if not port_raw:
        return
    port = int(port_raw)

    class _HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(204)
            self.end_headers()

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()


if __name__ == "__main__":
    _start_port_for_render_healthcheck()
    app.run_polling()