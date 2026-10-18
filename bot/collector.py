"""Сбор чатов открытых линий (WhatsApp через Wazzup) из Битрикс24 опросом REST API.

Схема:
1) user.get -> кто сотрудник (менеджер), кто нет (клиенты приходят как пользователи коннектора);
2) crm.activity.list (PROVIDER_ID = IMOPENLINES_SESSION) -> сессии открытых линий, обновленные с прошлого опроса;
3) imopenlines.dialog.get -> chat_id и линия сессии;
4) im.dialog.messages.get -> вся история чата, по 50 сообщений за запрос (нужно право im).
   Без права im запасной путь imopenlines.session.history.get: он отдает только 50 последних
   сообщений одной сессии, поэтому длинные чаты и прошлые сессии теряются.
"""
from datetime import datetime, timedelta

from . import config
from .bitrix import BitrixError
from .parse import Parser, SIDE


def to_local(s):
    if not s:
        return None
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if dt.tzinfo:
        dt = dt.astimezone(config.TZ).replace(tzinfo=None)
    return dt


def sync_users(bx, store):
    rows = []
    for u in bx.list_all("user.get", {"FILTER": {"ACTIVE": True}}):
        name = " ".join(x for x in (u.get("NAME"), u.get("LAST_NAME")) if x).strip() or u.get("EMAIL", "")
        employee = u.get("USER_TYPE", "employee") == "employee" and not u.get("EXTERNAL_AUTH_ID")
        excluded = str(u["ID"]) in config.EXCLUDED_USER_IDS or name in config.EXCLUDED_NAMES
        rows.append((str(u["ID"]), name, int(employee), int(excluded)))
    store.upsert_users(rows)
    return len(rows)


def discover_sessions(bx, store, since):
    acts = bx.list_all("crm.activity.list", {
        "filter": {"PROVIDER_ID": "IMOPENLINES_SESSION", ">=LAST_UPDATED": since.strftime("%Y-%m-%dT%H:%M:%S")},
        "select": ["ID", "ASSOCIATED_ENTITY_ID", "CREATED", "LAST_UPDATED", "COMPLETED", "RESPONSIBLE_ID", "PROVIDER_PARAMS", "SUBJECT"],
        "order": {"ID": "ASC"}})
    known = {s["session_id"]: s for s in store.open_sessions()}
    need_chat = [a for a in acts if str(a["ASSOCIATED_ENTITY_ID"]) not in known or not known[str(a["ASSOCIATED_ENTITY_ID"])]["chat_id"]]
    info = {}
    if need_chat:
        res, _ = bx.batch({f"s{a['ASSOCIATED_ENTITY_ID']}": ("imopenlines.dialog.get", {"SESSION_ID": a["ASSOCIATED_ENTITY_ID"]}) for a in need_chat})
        for k, v in res.items():
            info[k[1:]] = v or {}
    n = 0
    for a in acts:
        sid = str(a["ASSOCIATED_ENTITY_ID"])
        d = info.get(sid, {})
        entity = str(d.get("entity_id", ""))  # connector|line|chat|user
        line = entity.split("|")[1] if entity.count("|") >= 1 else ""
        if config.OPENLINE_IDS and line and line not in config.OPENLINE_IDS:
            continue
        store.upsert_session({"session_id": sid, "chat_id": str(d.get("id") or d.get("chat_id") or "") or None,
                              "line_id": line, "source": entity.split("|")[0] if entity else "",
                              "created": a.get("CREATED"), "closed": int(a.get("COMPLETED") == "Y"),
                              "responsible_id": str(a.get("RESPONSIBLE_ID") or "")})
        n += 1
    store.commit()
    return n


def has_im(bx, _cache={}):
    if "im" not in _cache:
        try:
            _cache["im"] = "im" in (bx.result("scope") or [])
        except BitrixError:
            _cache["im"] = False
    return _cache["im"]


def poll_messages(bx, store, parser):
    if has_im(bx):
        return poll_chats(bx, store, parser)
    return poll_sessions(bx, store, parser)


def _learn_users(parser, users):
    items = users.items() if isinstance(users, dict) else ((u.get("id"), u) for u in (users or []) if isinstance(u, dict))
    for uid, u in items:
        if str(uid) not in parser.users and (u.get("connector") or u.get("extranet") or u.get("network")):
            parser.users[str(uid)] = {"name": u.get("name", ""), "is_employee": 0}


def _row(parser, m, chat_id, session_id):
    author_id = m.get("author_id") if m.get("author_id") is not None else m.get("senderid")
    kind, author, text = parser.classify(author_id, m.get("text") or "")
    return {"msg_id": int(m["id"]), "chat_id": str(chat_id), "session_id": session_id or "",
            "ts": to_local(m.get("date")).isoformat(timespec="seconds"), "author_id": str(author_id or 0),
            "side": SIDE[kind], "kind": kind, "author": author, "text": text}


def poll_chats(bx, store, parser):
    """Новые сообщения по всем чатам с открытыми сессиями через im.dialog.messages.get.
    Первая страница: 50 самых новых сообщений чата. Если среди них нет уже известных, листаем назад (LAST_ID)
    до последнего известного сообщения, а при первой загрузке чата до HISTORY_DAYS дней назад."""
    sess = [s for s in store.open_sessions() if s["chat_id"]]
    if not sess:
        return 0
    if config.OPENLINE_IDS:
        sess = [s for s in sess if not s.get("line_id") or s["line_id"] in config.OPENLINE_IDS]
    chat_sess = {}
    for s in sorted(sess, key=lambda s: int(s["session_id"])):
        chat_sess[s["chat_id"]] = s["session_id"]  # последняя сессия чата
    known = store.chat_last_ids()
    cutoff = datetime.now(config.TZ).replace(tzinfo=None) - timedelta(days=config.HISTORY_DAYS)
    now = datetime.now(config.TZ).replace(tzinfo=None).isoformat(timespec="seconds")
    got = {c: {} for c in chat_sess}
    todo = {c: None for c in chat_sess}  # chat -> LAST_ID для следующей страницы (None = первая)
    errs_all = {}
    while todo:
        cmds = {}
        for c, last_id in todo.items():
            p = {"DIALOG_ID": f"chat{c}", "LIMIT": 50}
            if last_id:
                p["LAST_ID"] = last_id
            cmds[f"m{c}"] = ("im.dialog.messages.get", p)
        res, errs = bx.batch(cmds)
        errs_all.update(errs)
        nxt = {}
        for c in todo:
            r = res.get(f"m{c}") or {}
            _learn_users(parser, r.get("users"))
            msgs = r.get("messages") or []
            for m in msgs:
                got[c][int(m["id"])] = m
            if len(msgs) < 50:
                continue
            oldest = min(msgs, key=lambda m: int(m["id"]))
            prev = known.get(c, 0)
            if prev and int(oldest["id"]) <= prev:
                continue
            if not prev and to_local(oldest.get("date")) < cutoff:
                continue
            nxt[c] = int(oldest["id"])
        todo = nxt
    rows = []
    for c, msgs in got.items():
        prev = known.get(c, 0)
        last = prev
        for mid in sorted(msgs):
            if mid <= prev:
                continue
            m = msgs[mid]
            if not prev and to_local(m.get("date")) < cutoff:
                continue
            rows.append(_row(parser, m, c, chat_sess[c]))
            last = max(last, mid)
        if c not in errs_all:
            store.mark_chat(c, now, last)
            store.mark_polled(chat_sess[c], now, last)
    store.add_messages(rows)
    if errs_all:
        print(f"Ошибки загрузки по {len(errs_all)} чатам, пример: {list(errs_all.items())[:1]}")
    return len(rows)


def poll_sessions(bx, store, parser):
    """Запасной путь без права im: история по сессиям (не больше 50 последних сообщений сессии)."""
    sess = [s for s in store.open_sessions() if s["chat_id"]]
    if not sess:
        return 0
    cmds = {f"h{s['session_id']}": ("imopenlines.session.history.get", {"CHAT_ID": s["chat_id"], "SESSION_ID": s["session_id"]}) for s in sess}
    res, errs = bx.batch(cmds)
    rows, now = [], datetime.now(config.TZ).replace(tzinfo=None).isoformat(timespec="seconds")
    for s in sess:
        r = res.get(f"h{s['session_id']}") or {}
        _learn_users(parser, r.get("users"))
        msgs = r.get("message") or {}
        msgs = list(msgs.values()) if isinstance(msgs, dict) else list(msgs)
        msgs.sort(key=lambda m: int(m["id"]))  # Битрикс отдает от новых к старым
        last = s["last_msg_id"] or 0
        for m in msgs:
            mid = int(m["id"])
            if config.OPENLINE_IDS and s.get("line_id") and s["line_id"] not in config.OPENLINE_IDS:
                continue
            if mid <= last:
                continue
            rows.append(_row(parser, m, s["chat_id"], s["session_id"]))
            last = max(last, mid)
        store.mark_polled(s["session_id"], now, last)
    store.add_messages(rows)
    if errs:
        print(f"Ошибки истории по {len(errs)} сессиям, пример: {list(errs.items())[:1]}")
    return len(rows)
