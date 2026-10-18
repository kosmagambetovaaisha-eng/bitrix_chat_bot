"""Настройки бота. Все секреты только из переменных окружения (.env), не из кода."""
import os
from zoneinfo import ZoneInfo


def _load_env():
    # Настройки читаются из env.txt (или .env, если он есть)
    path = next((p for p in ("env.txt", ".env") if os.path.exists(p)), None)
    if not path:
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_env()

# Входящий вебхук Битрикс24, вида https://<портал>.bitrix24.kz/rest/<user_id>/<ключ>/
BITRIX_WEBHOOK = os.environ.get("BITRIX_WEBHOOK", "").rstrip("/") + "/"

# Источник переписки:
#   comments  комментарии Wazzup в ленте сделок Битрикс24 (по умолчанию, с 13.10.2026 открытая линия отключена)
#   wazzup    вебхуки Wazzup (если вебхук Wazzup свободен или его дублируют боту)
#   bitrix    открытая линия Битрикс24 (до 13.10.2026)
SOURCE = os.environ.get("SOURCE", "comments")
# Сделки, по которым ищем новые комментарии: открытые и измененные за столько дней
ACTIVE_DAYS = int(os.environ.get("ACTIVE_DAYS", "30"))
# До отключения открытой линии Wazzup писал в сделки только часть сообщений (с телефона): их не берем
COMMENTS_SINCE = os.environ.get("COMMENTS_SINCE", "2026-10-13T13:19:00")
# Ответы «Телефон» (Wazzup не знает автора) засчитывать ответственному по сделке; ему же чаты, где еще никто не ответил
UNATTR_TO_RESPONSIBLE = os.environ.get("UNATTR_TO_RESPONSIBLE", "1") == "1"
# Каждый цикл опрашиваем «горячие» сделки (новые и с перепиской за HOT_DAYS дней),
# все открытые сделки обходим раз в FULL_SCAN_MIN минут (клиент написал в старую сделку)
HOT_DAYS = int(os.environ.get("HOT_DAYS", "7"))
FULL_SCAN_MIN = int(os.environ.get("FULL_SCAN_MIN", "30"))
WAZZUP_API_KEY = os.environ.get("WAZZUP_API_KEY", "")
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "8080"))
# Секретный путь вебхука, чтобы чужие запросы не попадали в базу. Задайте свой в env.txt.
WAZZUP_WEBHOOK_PATH = "/" + os.environ.get("WAZZUP_WEBHOOK_PATH", "wazzup-hook").strip("/")

# Telegram: бот и чаты получателей
TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_SUPERVISOR_CHAT = os.environ.get("TG_SUPERVISOR_CHAT", "")
# Личные чаты менеджеров: "201:123456789,305:987654321" (bitrix user id : telegram chat id)
TG_MANAGER_CHATS = dict(
    p.split(":", 1) for p in os.environ.get("TG_MANAGER_CHATS", "").split(",") if ":" in p
)

# Тестовый режим: все сообщения (и адресованные менеджерам) уходят только в TG_SUPERVISOR_CHAT
TEST_MODE = os.environ.get("TEST_MODE", "1") == "1"
# Алерты «клиент ждет ответа» (пока Wazzup теряет диалоги, по умолчанию выключены)
ALERTS = os.environ.get("ALERTS", "0") == "1"
# Кто может пользоваться командами бота (кроме TG_SUPERVISOR_CHAT): "123456789,987654321"
TG_ALLOWED_CHATS = {x.strip() for x in os.environ.get("TG_ALLOWED_CHATS", "").split(",") if x.strip()}

DB_PATH = os.environ.get("DB_PATH", "hikmet_chats.sqlite")
try:
    TZ = ZoneInfo(os.environ.get("TZ_NAME", "Asia/Almaty"))
except Exception:  # на Windows без пакета tzdata: Алматы = UTC+5
    from datetime import timezone, timedelta
    TZ = timezone(timedelta(hours=5))

# Рабочее время (используется для скорости ответа и для алертов)
WORK_START = int(os.environ.get("WORK_START", "9"))
WORK_END = int(os.environ.get("WORK_END", "18"))
# График менеджеров (смены по дням недели); рабочее время команды = от самой ранней до самой поздней смены
SCHEDULE_PATH = os.environ.get("SCHEDULE_PATH", "schedule.txt")
WORK_DAYS = {int(x) for x in os.environ.get("WORK_DAYS", "1,2,3,4,5,6,7").split(",")}  # 1 = понедельник

# Открытые линии, которые считаем (пусто = все). Астану сюда не добавлять.
OPENLINE_IDS = {x for x in os.environ.get("OPENLINE_IDS", "").split(",") if x}

# Пользователи Битрикс, которых не считаем менеджерами (технические, администратор вебхука):
# EXCLUDED_NAMES в env.txt или строки «! Имя» в names.txt
EXCLUDED_USER_IDS = {x for x in os.environ.get("EXCLUDED_USER_IDS", "").split(",") if x}
EXCLUDED_NAMES = {x.strip() for x in os.environ.get("EXCLUDED_NAMES", "").split(",") if x.strip()}
_names = os.environ.get("NAMES_PATH", "names.txt")
if os.path.exists(_names):
    EXCLUDED_NAMES |= {l.strip()[1:].strip() for l in open(_names, encoding="utf-8") if l.strip().startswith("!")}

# Пороги алертов (минуты рабочего времени)
ALERT_WAIT_MIN = int(os.environ.get("ALERT_WAIT_MIN", "15"))
ALERT_ESCALATE_MIN = int(os.environ.get("ALERT_ESCALATE_MIN", "60"))
ALERT_HOLD_MIN = int(os.environ.get("ALERT_HOLD_MIN", "30"))
FOLLOWUP_HOURS = int(os.environ.get("FOLLOWUP_HOURS", "24"))

# Сколько дней истории чата забирать при первой загрузке (через im.dialog.messages.get)
HISTORY_DAYS = int(os.environ.get("HISTORY_DAYS", "30"))

POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "90"))
DAILY_REPORT_AT = os.environ.get("DAILY_REPORT_AT", "19:30")
MORNING_REPORT_AT = os.environ.get("MORNING_REPORT_AT", "10:05")
