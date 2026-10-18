"""Сбор переписки из комментариев Wazzup в ленте сделок Битрикс24 (с 13.10.2026 открытая линия отключена).

Wazzup пишет каждое сообщение WhatsApp отдельным комментарием в сделку (автор комментария: владелец интеграции):
  [img]https://static.wazzup24.com/images/bitrix/whatsapp.png[/img]&nbsp; Сделка по обращению Имя (77011234567):
  текст            <- входящее от клиента (в заголовке номер в скобках)
  ... Имя Фамилия:
  текст            <- исходящее, в заголовке имя менеджера
  ... Телефон:     <- исходящее с телефона, автор неизвестен
Комментарии не меняют дату изменения сделки, поэтому опрашиваем все открытые сделки, измененные за ACTIVE_DAYS.
Чат в базе: deal<ID сделки>.
"""
import re
from datetime import datetime, timedelta

from . import config
from .collector import to_local
from .parse import SIDE, clean_text, name_key, norm_name, canonical, ALIAS_KEY

WZ_MARK = "static.wazzup24.com"
IMG = re.compile(r"\[img[^\]]*\].*?\[/img\]", re.I | re.S)
URL = re.compile(r"\[url[^\]]*\].*?\[/url\]|\[/?url[^\]]*\]", re.I | re.S)
CLIENT_HDR = re.compile(r"\(\+?\d[\d\s\-]{7,}\)\s*$")


def is_manager(parser, head):
    """Заголовок = известный менеджер: сотрудник из Битрикс24 или вариант имени из ALIASES (parse.py / NAME_ALIASES)."""
    canonical("")  # заполняет ALIAS_KEY
    k = name_key(head)
    return k in parser.by_key or k in ALIAS_KEY


def parse_comment(parser, text):
    """-> (kind, author, body) или None, если комментарий не от Wazzup.
    Заголовок клиента бывает разным («Сделка по обращению Имя (телефон)», имя контакта, «Имя - WAZZUP ...»,
    эмодзи), поэтому менеджером считаем только известное имя, «Телефон» = исходящее без автора, остальное = клиент.
    Для клиента в author кладем заголовок (только в локальную базу, в отчеты он не идет)."""
    if WZ_MARK not in text:
        return None
    t = IMG.sub("", text).replace("&nbsp;", " ")
    t = URL.sub(" ", t).strip()
    head, _, body = t.partition(":")
    head = re.sub(r"\s+", " ", head).strip()
    body = clean_text(body)
    if norm_name(head) in ("Телефон", "[ИМЯ]"):
        return "OUT_UNATTR", "", body
    if CLIENT_HDR.search(head) or "WAZZUP" in head.upper() or not is_manager(parser, head):
        return "CLI", head[:80], body
    name = parser.manager_name(head)
    if name_key(name) in parser.excluded_keys:
        return "TECH", name, body
    return "MGR", name, body


def _deals(bx, store, flt):
    rows = bx.list_all("crm.deal.list", {"filter": flt, "select": ["ID", "ASSIGNED_BY_ID"], "order": {"ID": "DESC"}})
    store.set_deals([(str(d["ID"]), str(d.get("ASSIGNED_BY_ID") or "")) for d in rows])
    return [str(d["ID"]) for d in rows]


def active_deals(bx, store):
    """Все открытые сделки, измененные за ACTIVE_DAYS (полный обход, раз в FULL_SCAN_MIN)."""
    since = (datetime.now(config.TZ) - timedelta(days=config.ACTIVE_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    return _deals(bx, store, {"CLOSED": "N", ">=DATE_MODIFY": since})


def hot_deals(bx, store):
    """Сделки для частого опроса: созданные за 2 дня (новые обращения) и с перепиской за HOT_DAYS дней."""
    since = (datetime.now(config.TZ) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    new = _deals(bx, store, {">=DATE_CREATE": since})
    ts = (datetime.now(config.TZ).replace(tzinfo=None) - timedelta(days=config.HOT_DAYS)).isoformat(timespec="seconds")
    talk = [r[0][4:] for r in store.db.execute(
        "SELECT DISTINCT chat_id FROM messages WHERE chat_id LIKE 'deal%' AND ts>=?", (ts,))]
    return sorted(set(new) | set(talk), key=int, reverse=True)


def poll_comments(bx, store, parser, deals):
    """Забрать комментарии Wazzup по сделкам. Повторно загруженные комментарии игнорируются (по ID)."""
    cutoff = max(datetime.now(config.TZ).replace(tzinfo=None) - timedelta(days=config.HISTORY_DAYS),
                 datetime.fromisoformat(config.COMMENTS_SINCE))
    sel = ["ID", "CREATED", "AUTHOR_ID", "COMMENT"]
    cmds = {f"d{d}": ("crm.timeline.comment.list", {"filter": {"ENTITY_TYPE": "deal", "ENTITY_ID": d},
                                                    "select": sel, "order": {"ID": "DESC"}}) for d in deals}
    res, errs = bx.batch(cmds)
    items = {}
    for d in deals:
        got = res.get(f"d{d}") or []
        if isinstance(got, dict):
            got = got.get("items") or list(got.values())
        if len(got) >= 50:  # больше одной страницы: дочитываем отдельно
            got = bx.list_all("crm.timeline.comment.list", {"filter": {"ENTITY_TYPE": "deal", "ENTITY_ID": d}, "select": sel})
        items[d] = got
    rows = []
    for d, got in items.items():
        for c in got:
            p = parse_comment(parser, str(c.get("COMMENT") or ""))
            if not p:
                continue
            ts = to_local(c.get("CREATED"))
            if ts is None or ts < cutoff:
                continue
            kind, author, body = p
            rows.append({"msg_id": int(c["ID"]), "chat_id": f"deal{d}", "session_id": "", "ts": ts.isoformat(timespec="seconds"),
                         "author_id": str(c.get("AUTHOR_ID") or ""), "side": SIDE[kind], "kind": kind, "author": author, "text": body})
    before = store.db.total_changes
    store.add_messages(rows)
    if errs:
        print(f"Ошибки загрузки комментариев по {len(errs)} сделкам, пример: {list(errs.items())[:1]}")
    return store.db.total_changes - before
