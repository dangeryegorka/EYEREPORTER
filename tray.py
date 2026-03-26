"""
tray.py — запускает бота и сворачивает в трей
Установи зависимости: py -m pip install pystray pillow
"""

import subprocess
import sys
import os
import threading
import time
from PIL import Image, ImageDraw
import pystray

# ─── Путь к боту ─────────────────────────────────────────────────────────────
BOT_DIR  = os.path.dirname(os.path.abspath(__file__))
BOT_FILE = os.path.join(BOT_DIR, "taskbot.py")

bot_process = None

# ─── Запуск бота ─────────────────────────────────────────────────────────────
def start_bot():
    global bot_process
    while True:
        bot_process = subprocess.Popen(
            [sys.executable, BOT_FILE],
            cwd=BOT_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW  # без окна консоли
        )
        bot_process.wait()
        time.sleep(5)  # перезапуск через 5 сек если упал

def stop_bot():
    global bot_process
    if bot_process:
        bot_process.terminate()

# ─── Иконка в трее ───────────────────────────────────────────────────────────
def create_icon():
    # Рисуем простую иконку — синий круг с молнией
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill="#0088cc")
    # Молния
    draw.polygon([(36,8),(24,36),(34,36),(28,56),(44,28),(34,28),(40,8)], fill="white")
    return img

def on_quit(icon, item):
    stop_bot()
    icon.stop()

def on_status(icon, item):
    status = "✅ работает" if bot_process and bot_process.poll() is None else "❌ не запущен"
    # Показываем статус через заголовок иконки
    icon.title = f"EYC Tasker — {status}"

def run_tray():
    icon = pystray.Icon(
        name="EYCTasker",
        icon=create_icon(),
        title="EYC Tasker Bot — работает",
        menu=pystray.Menu(
            pystray.MenuItem("EYC Tasker Bot", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("✅ Статус", on_status),
            pystray.MenuItem("❌ Остановить бота", on_quit),
        )
    )
    icon.run()

# ─── Старт ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Запускаем бота в фоновом потоке
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()

    # Показываем иконку в трее (блокирует до выхода)
    run_tray()
