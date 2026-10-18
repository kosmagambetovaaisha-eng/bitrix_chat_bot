"""Подключение Telegram-бота. Запуск из папки бота: python3 tg_setup.py
1. В Telegram откройте @BotFather, отправьте /newbot, придумайте имя. BotFather пришлет токен.
2. Впишите его в env.txt строкой TG_TOKEN=... (токен никому не пересылайте).
3. Запустите этот скрипт и напишите своему боту в Telegram /start.
Скрипт найдет ваш chat id, запишет его в env.txt как TG_SUPERVISOR_CHAT и пришлет тестовое сообщение.
"""
import os
import time

from bot import config
from bot.tgbot import api

if not config.TG_TOKEN:
    raise SystemExit("В env.txt нет строки TG_TOKEN=... Получите токен у @BotFather и впишите его.")
try:
    me = api("getMe")["result"]
except Exception as e:
    raise SystemExit(f"Telegram не принял токен ({e}). Проверьте строку TG_TOKEN в env.txt.")
print(f"Бот: @{me['username']}. Напишите ему в Telegram /start (жду 3 минуты)...")

chat, offset, end = None, 0, time.time() + 180
while not chat and time.time() < end:
    for u in api("getUpdates", timeout=20, offset=offset).get("result", []):
        offset = u["update_id"] + 1
        m = u.get("message") or {}
        if m.get("chat"):
            chat, who = m["chat"]["id"], m["chat"].get("first_name") or m["chat"].get("title", "")
api("getUpdates", timeout=0, offset=offset)  # отметить сообщения прочитанными
if not chat:
    raise SystemExit("Сообщение не пришло. Запустите скрипт еще раз и напишите боту /start.")
print(f"Ваш chat id: {chat} ({who})")

path = "env.txt" if os.path.exists("env.txt") else ".env"
lines = [l for l in open(path, encoding="utf-8").read().splitlines() if not l.startswith("TG_SUPERVISOR_CHAT=")]
lines.append(f"TG_SUPERVISOR_CHAT={chat}")
open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(f"Записала TG_SUPERVISOR_CHAT в {path}.")
api("setMyCommands", commands=[
    {"command": "report", "description": "Общий отчет за сегодня"},
    {"command": "managers", "description": "Аналитика по менеджеру"},
    {"command": "all", "description": "Отчет и все менеджеры"}])
api("sendMessage", chat_id=chat, text="Бот аналитики чатов Hickmet подключен. Команды: /report, /managers, /m Имя, /all")
print("Тестовое сообщение отправлено. Теперь запустите: python3 main.py")
