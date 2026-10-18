"""Проверка вебхука и доступных данных. Запуск: python probe.py
Тексты клиентов не печатаются: только поля, количества и длины.
"""
from datetime import datetime, timedelta

from bot import config
from bot.bitrix import Bitrix, BitrixError

NEED_SCOPES = {"imopenlines": "открытые линии и история чатов", "im": "сообщения", "crm": "сессии открытых линий как дела CRM",
               "user": "список сотрудников (кто менеджер)"}


def step(title, fn):
    print(f"\n== {title}")
    try:
        return fn()
    except BitrixError as e:
        print("   ОШИБКА:", e)
    except Exception as e:  # noqa
        print("   ОШИБКА:", type(e).__name__, e)


def main():
    bx = Bitrix(config.BITRIX_WEBHOOK)
    p = step("Вебхук живой? (profile)", lambda: bx.result("profile"))
    if p:
        print(f"   Да. Владелец вебхука: id {p.get('ID')}, {p.get('NAME', '')} {p.get('LAST_NAME', '')}, админ: {p.get('ADMIN')}")
    sc = step("Права вебхука (scope)", lambda: bx.result("scope"))
    if sc is not None:
        print("   Есть:", ", ".join(sc))
        for k, why in NEED_SCOPES.items():
            print(f"   {'OK ' if k in sc else 'НЕТ'} {k}: {why}")
    users = step("Сотрудники (user.get)", lambda: bx.list_all("user.get", {"FILTER": {"ACTIVE": True}}))
    if users:
        print(f"   Активных пользователей: {len(users)}")
    lines = step("Открытые линии (imopenlines.config.list.get)", lambda: bx.result("imopenlines.config.list.get", {"PARAMS": {"select": ["ID", "LINE_NAME", "ACTIVE"]}}))
    for l in lines or []:
        print(f"   линия {l.get('ID')}: {l.get('LINE_NAME')} (активна: {l.get('ACTIVE')})")
    since = (datetime.now(config.TZ) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    acts = step("Сессии открытых линий за сутки (crm.activity.list)", lambda: bx.list_all(
        "crm.activity.list", {"filter": {"PROVIDER_ID": "IMOPENLINES_SESSION", ">=LAST_UPDATED": since},
                              "select": ["ID", "ASSOCIATED_ENTITY_ID", "CREATED", "COMPLETED", "RESPONSIBLE_ID", "SUBJECT"]}, limit=200))
    if acts is not None:
        print(f"   Сессий: {len(acts)}" + (f", пример полей: {sorted(acts[0].keys())}" if acts else ""))
    if acts:
        emp = {str(u["ID"]): " ".join(x for x in (u.get("NAME"), u.get("LAST_NAME")) if x) for u in (users or [])}
        # берем 3 сессии с ответами: смотрим последние 40 и выбираем те, где больше сообщений
        cand = []
        res, _ = bx.batch({f"s{a['ASSOCIATED_ENTITY_ID']}": ("imopenlines.dialog.get", {"SESSION_ID": a["ASSOCIATED_ENTITY_ID"]}) for a in acts[-40:]})
        for k, d in res.items():
            if d:
                cand.append((int(d.get("message_count") or 0), k[1:], d))
        cand.sort(reverse=True)
        for _, sid, d in cand[:3]:
            print(f"\n== Сессия {sid}, chat_id={d.get('id')}, сообщений в чате {d.get('message_count')}")
            h = step("История (imopenlines.session.history.get)", lambda: bx.result(
                "imopenlines.session.history.get", {"CHAT_ID": d.get("id"), "SESSION_ID": sid}))
            if not h:
                continue
            msgs = h.get("message") or {}
            msgs = list(msgs.values()) if isinstance(msgs, dict) else msgs
            msgs.sort(key=lambda m: int(m["id"]))
            us = h.get("users") or {}
            import re
            from collections import Counter
            hdr = Counter(re.search(r"=== Исходящее сообщение, автор: (.*?) ===", m.get("text") or "").group(1)
                          for m in msgs if "Исходящее сообщение, автор" in (m.get("text") or ""))
            print(f"   Авторы в заголовках Wazzup: {dict(hdr) or 'нет'}")
            for m in msgs[:12]:
                t = m.get("text") or ""
                sid_ = str(m.get("senderid") or m.get("author_id") or 0)
                who = ("сотрудник: " + emp[sid_]) if sid_ in emp else ("система" if sid_ == "0" else "клиент/коннектор")
                prm = m.get("params") or {}
                print(f"   {str(m.get('date'))[:19]} sender={sid_} ({who}) len={len(t)} "
                      f"заголовок_wazzup={'Исходящее сообщение, автор' in t} system_wz={'SYSTEM WZ' in t} "
                      f"params={sorted(prm.keys())[:6] if isinstance(prm, dict) else '-'}")
    print("\nГотово. Пришлите этот вывод: по нему настроим сбор.")


if __name__ == "__main__":
    main()
