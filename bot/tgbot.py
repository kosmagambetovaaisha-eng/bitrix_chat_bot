"""Telegram-бот: команды и доступы.

Админ (TG_SUPERVISOR_CHAT и те, кому админ выдал роль «Админ»):
  /report [вчера]   общий отчет
  /managers         кнопки с менеджерами: карточка и разбор
  /m Имя         карточка менеджера, /razbor Имя [вчера]  разбор его диалогов
  /all              общий отчет и карточки всех менеджеров
  /access           кто имеет доступ (с кнопками «убрать»)
Менеджер (видит только себя):
  /me [вчера]       моя карточка
  /razbor [вчера]   разбор моих диалогов
Новый человек пишет боту что угодно, админу приходит заявка с кнопками: кто это (менеджер / админ / отклонить).
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from . import config, reports, schedule, telegram
from .parse import ALIASES, name_key

HELP_ADMIN = ("Команды администратора:\n/report  общий отчет (/report вчера)\n/managers  выбрать менеджера\n"
              "/m Имя  карточка менеджера\n/razbor Имя  разбор его диалогов (можно добавить «вчера»)\n"
              "/all  отчет и все менеджеры\n/access  кто имеет доступ")
HELP_MANAGER = "Команды:\n/me  моя аналитика за сегодня (/me вчера)\n/razbor  разбор моих диалогов (/razbor вчера)"


def api(method, timeout=10, **params):
    data = urllib.parse.urlencode({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in params.items()}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{config.TG_TOKEN}/{method}", data=data, timeout=timeout + 15) as r:
        return json.loads(r.read())


def role(store, chat_id):
    """-> (роль, менеджер). Роль: admin | manager | pending | blocked | None."""
    if str(chat_id) == str(config.TG_SUPERVISOR_CHAT) or str(chat_id) in config.TG_ALLOWED_CHATS:
        return "admin", ""
    u = store.tg_user(chat_id)
    return (u["role"], u["manager"]) if u else (None, "")


def admins(store):
    return list(dict.fromkeys([str(config.TG_SUPERVISOR_CHAT)] + store.tg_chats("admin"))) if config.TG_SUPERVISOR_CHAT \
        else store.tg_chats("admin")


def roster(states, day):
    """Менеджеры для кнопок: из графика и все, у кого есть диалоги."""
    names = set(schedule.sched()) | set(reports.team_names(states, day) if states else [])
    return sorted(names, key=reports.short)


def find(query, names):
    """Менеджеры из names, у которых какое-либо слово имени (в любом написании из ALIASES) начинается с query."""
    q = name_key(query)
    if not q:
        return []
    spellings = {n: {n} for n in names}
    for alias, canon in ALIASES.items():
        if canon in spellings:
            spellings[canon].add(alias)
    return [n for n, sp in spellings.items() if any(w.startswith(q) for a in sp for w in name_key(a).split())]


def keyboard(buttons, per_row=3):
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return {"inline_keyboard": [[{"text": t, "callback_data": d[:64]} for t, d in row] for row in rows]}


def _day(arg, now):
    a = arg.strip().lower()
    yesterday = a.endswith("вчера") or a.endswith("yesterday")
    rest = a[:-5].strip() if a.endswith("вчера") else a[:-9].strip() if a.endswith("yesterday") else a
    return (now.date() - timedelta(days=1) if yesterday else now.date()), rest


def answer(text, ctx, chat_id=None):
    """Ответ на команду -> список (текст, клавиатура или None)."""
    store, states, now = ctx.get("store"), ctx["states"], ctx["now"]
    r, me = role(store, chat_id) if store is not None and chat_id is not None else ("admin", "")
    cmd, _, arg = text.strip().partition(" ")
    cmd = cmd.split("@")[0].lower()
    if r == "manager":
        if states is None:
            return [("Данные еще собираются, попробуйте через пару минут.", None)]
        day, _ = _day(arg, now)
        if cmd == "/me":
            return [(reports.manager_card(states, me, day, now), None)]
        if cmd == "/razbor":
            return [(reports.review(states, me, day, now), None)]
        return [(HELP_MANAGER, None)]
    if r != "admin":
        return []
    if cmd == "/access":
        return access_list(store)
    if states is None:
        return [("Данные еще собираются, попробуйте через пару минут.", None)]
    day, name_arg = _day(arg, now)
    names = roster(states, now.date())
    if cmd == "/report":
        return [(reports.daily_report(states, day, now), None)]
    if cmd == "/managers":
        return [("Выберите менеджера:", keyboard([(reports.short(n), f"m:{n}") for n in names]))]
    if cmd in ("/m", "/manager", "/razbor"):
        found = find(name_arg, names) if name_arg else []
        kind = "r" if cmd == "/razbor" else "m"
        if len(found) == 1:
            return [(reports.review(states, found[0], day, now), None)] if kind == "r" else card(states, found[0], day, now)
        return [("Выберите менеджера:" if not found else "Нашлось несколько, выберите:",
                 keyboard([(reports.short(n), f"{kind}:{n}") for n in (found or names)]))]
    if cmd == "/all":
        return [(reports.daily_report(states, day, now), None)] + \
               [(reports.manager_card(states, n, day, now), None) for n in reports.team_names(states, day)]
    return [(HELP_ADMIN, None)]


def card(states, name, day, now):
    return [(reports.manager_card(states, name, day, now), keyboard([("Разбор диалогов", f"r:{name}")]))]


def access_list(store):
    users = [u for u in store.tg_users() if u["role"] in ("admin", "manager", "pending")]
    if not users:
        return [("Кроме вас доступа ни у кого нет. Попросите менеджера написать боту, вам придет заявка.", None)]
    out = []
    for u in users:
        who = {"admin": "админ", "manager": f"менеджер {reports.short(u['manager'])}", "pending": "ждет решения"}[u["role"]]
        out.append((f"{u['name'] or u['chat_id']}: {who}", keyboard([("Убрать доступ", f"x:{u['chat_id']}")])))
    return out


def request_access(store, msg, ctx):
    chat = msg["chat"]["id"]
    frm = msg.get("from", {})
    name = " ".join(x for x in (frm.get("first_name"), frm.get("last_name")) if x) or str(chat)
    if frm.get("username"):
        name += f" (@{frm['username']})"
    store.tg_set(chat, "pending", "", name, datetime.now().isoformat(timespec="seconds"))
    api("sendMessage", chat_id=chat, text="Заявка на доступ отправлена администратору. Как только он подтвердит, я напишу.")
    names = roster(ctx["states"], ctx["now"].date()) if ctx.get("now") else sorted(schedule.sched())
    kb = keyboard([(reports.short(n), f"a:{chat}:{n}") for n in names] + [("Админ", f"a:{chat}:ADMIN"), ("Отклонить", f"a:{chat}:NO")])
    for a in admins(store):
        api("sendMessage", chat_id=a, text=f"Запрос доступа к боту: {name}. Кто это?", reply_markup=kb)


def on_callback(cq, ctx):
    store, states, now = ctx["store"], ctx["states"], ctx["now"]
    chat = cq["message"]["chat"]["id"]
    data = cq.get("data", "")
    api("answerCallbackQuery", callback_query_id=cq["id"])
    r, me = role(store, chat)
    if r != "admin":
        return
    kind, _, rest = data.partition(":")
    if kind in ("m", "r"):
        if states is None:
            return send(chat, [("Данные еще собираются, попробуйте через пару минут.", None)])
        send(chat, card(states, rest, now.date(), now) if kind == "m" else [(reports.review(states, rest, now.date(), now), None)])
    elif kind == "a":
        target, _, val = rest.partition(":")
        u = store.tg_user(target) or {}
        ts = datetime.now().isoformat(timespec="seconds")
        if val == "NO":
            store.tg_set(target, "blocked", "", None, ts)
            send(chat, [(f"Отклонено: {u.get('name', target)}", None)])
            api("sendMessage", chat_id=target, text="Администратор не подтвердил доступ.")
        elif val == "ADMIN":
            store.tg_set(target, "admin", "", None, ts)
            setup_commands(store)
            send(chat, [(f"Готово: {u.get('name', target)} теперь администратор.", None)])
            api("sendMessage", chat_id=target, text="Доступ открыт.\n" + HELP_ADMIN)
        else:
            store.tg_set(target, "manager", val, None, ts)
            send(chat, [(f"Готово: {u.get('name', target)} это {val}. Он видит только свою аналитику.", None)])
            api("sendMessage", chat_id=target, text=f"Доступ открыт, {reports.short(val)}.\n" + HELP_MANAGER)
    elif kind == "x":
        u = store.tg_user(rest) or {}
        store.tg_set(rest, "blocked", "", None, datetime.now().isoformat(timespec="seconds"))
        send(chat, [(f"Доступ убран: {u.get('name', rest)}", None)])


def handle(u, ctx):
    store = ctx["store"]
    if "callback_query" in u:
        return on_callback(u["callback_query"], ctx)
    msg = u.get("message") or {}
    chat, text = msg.get("chat", {}).get("id"), msg.get("text", "")
    if chat is None or msg.get("chat", {}).get("type") != "private" and str(chat) != str(config.TG_SUPERVISOR_CHAT):
        return
    r, _ = role(store, chat)
    if r is None:
        return request_access(store, msg, ctx)
    if r == "pending":
        return api("sendMessage", chat_id=chat, text="Заявка уже у администратора, ждите подтверждения.")
    if r == "blocked":
        return api("sendMessage", chat_id=chat, text="Доступа нет. Обратитесь к администратору.")
    send(chat, answer(text if text.startswith("/") else "/help", ctx, chat))


def serve(seconds, ctx):
    """Слушать команды seconds секунд (long polling). ctx: {'store', 'states', 'now'} от последнего цикла."""
    if not config.TG_TOKEN:
        time.sleep(seconds)
        return
    end = time.time() + seconds
    while time.time() < end:
        try:
            res = api("getUpdates", timeout=int(max(1, min(25, end - time.time()))),
                      offset=ctx.get("offset", 0), allowed_updates=["message", "callback_query"])
        except Exception as e:
            print("Telegram getUpdates:", e)
            time.sleep(5)
            continue
        for u in res.get("result", []):
            ctx["offset"] = u["update_id"] + 1
            try:
                handle(u, ctx)
            except Exception as e:
                print("Telegram команда:", e)


def send(chat, items):
    for text, kb in items:
        if kb:
            api("sendMessage", chat_id=chat, text=text, parse_mode="HTML", disable_web_page_preview="true", reply_markup=kb)
        else:
            telegram.send(chat, text)


def setup_commands(store):
    """Меню команд: менеджерам свои, админам полные."""
    try:
        api("setMyCommands", commands=[{"command": "me", "description": "Моя аналитика"},
                                       {"command": "razbor", "description": "Разбор моих диалогов"}])
        for a in admins(store):
            api("setMyCommands", scope={"type": "chat", "chat_id": int(a)}, commands=[
                {"command": "report", "description": "Общий отчет"},
                {"command": "managers", "description": "Менеджеры: карточка и разбор"},
                {"command": "all", "description": "Отчет и все менеджеры"},
                {"command": "access", "description": "Кто имеет доступ"}])
    except Exception as e:
        print("Telegram меню команд:", e)
