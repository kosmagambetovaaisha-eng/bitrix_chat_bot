"""Запуск бота: python main.py  (бесконечный цикл опроса Битрикс24).
Флаги: --once  один цикл; --dry-run  печатать сообщения вместо отправки в Telegram; --report  сразу показать отчет за сегодня;
--all  отчет и карточки всех менеджеров.
"""
import sys
import time
import traceback
from datetime import datetime, timedelta

from bot import config
from bot.bitrix import Bitrix
from bot.store import Store
from bot.parse import Parser
from bot.collector import sync_users, discover_sessions, poll_messages
from bot.engine import tick
from bot import wazzup, tgbot
from bot.comments import active_deals, hot_deals, poll_comments


def now_local():
    return datetime.now(config.TZ).replace(tzinfo=None, microsecond=0)


def main():
    once, dry = "--once" in sys.argv, "--dry-run" in sys.argv
    bx, store = Bitrix(config.BITRIX_WEBHOOK), Store(config.DB_PATH)
    users_at = None
    full_at = None
    ctx = {"store": store, "states": None, "now": None}  # последние данные для команд Telegram
    parser_box = {"p": Parser(store.users(), config.EXCLUDED_USER_IDS, config.EXCLUDED_NAMES)}
    if config.SOURCE == "wazzup" and not once:
        # Wazzup сам присылает сообщения; Битрикс24 нужен только для списка сотрудников
        wazzup.serve(lambda: Store(config.DB_PATH), lambda: parser_box["p"], config.WEBHOOK_PORT, config.WAZZUP_WEBHOOK_PATH)
    if config.TG_TOKEN and not dry:
        tgbot.setup_commands(store)
    while True:
        try:
            now = now_local()
            if users_at is None or now - users_at > timedelta(hours=6):
                print("Сотрудников:", sync_users(bx, store)); users_at = now
            parser = Parser(store.users(), config.EXCLUDED_USER_IDS, config.EXCLUDED_NAMES)
            parser_box["p"] = parser
            if config.SOURCE == "comments":
                if full_at is None or now - full_at > timedelta(minutes=config.FULL_SCAN_MIN):
                    deals, full_at = active_deals(bx, store), now   # полный обход
                else:
                    deals = hot_deals(bx, store)
                ns = len(deals)
                nm = poll_comments(bx, store, parser, deals)
            elif config.SOURCE == "wazzup":
                ns = 0
                nm = store.db.execute("SELECT count(*) FROM messages WHERE chat_id LIKE 'wz:%'").fetchone()[0]
            else:
                last = store.get("discover_since")
                since = datetime.fromisoformat(last) - timedelta(minutes=10) if last else now - timedelta(days=3)
                ns = discover_sessions(bx, store, since)
                store.set("discover_since", now.isoformat())
                nm = poll_messages(bx, store, parser)
            states, na = tick(store, now, dry)
            ctx["states"], ctx["now"] = states, now
            if "--report" in sys.argv or "--all" in sys.argv:
                from bot import reports, telegram
                telegram.send(config.TG_SUPERVISOR_CHAT, reports.daily_report(states, now.date(), now), dry)
                if "--all" in sys.argv:
                    for name in reports.team_names(states, now.date()):
                        telegram.send(config.TG_SUPERVISOR_CHAT, reports.manager_card(states, name, now.date(), now), dry)
            if config.SOURCE == "comments":
                print(f"{now:%H:%M:%S} сделок {ns}, новых сообщений {nm}, алертов {na}")
            elif config.SOURCE == "wazzup":
                print(f"{now:%H:%M:%S} сообщений Wazzup в базе {nm}, алертов {na}")
            else:
                print(f"{now:%H:%M:%S} сессий {ns}, новых сообщений {nm}, алертов {na}")
        except Exception:
            traceback.print_exc()
        if once:
            break
        if dry:
            time.sleep(config.POLL_SECONDS)
        else:
            tgbot.serve(config.POLL_SECONDS, ctx)  # между циклами отвечаем на команды /report, /managers, /m


if __name__ == "__main__":
    main()
