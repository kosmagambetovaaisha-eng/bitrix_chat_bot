"""Отчеты и алерты в виде текста для Telegram (HTML-разметка)."""
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from html import escape

from . import config, schedule


def short(name):
    if not name or name in ("Нет менеджера", "Без автора"):
        return name or "Нет менеджера"
    return name.split(" ")[0]


def fmt_min(sec):
    if sec is None:
        return "–"
    m = sec / 60
    return f"{m:.0f} мин" if m < 120 else f"{m / 60:.1f} ч".replace(".", ",")


def pct(a, b):
    return f"{a / b * 100:.0f}%" if b else "–"


FU_DAYS = 3  # за сколько дней считаем сделанные follow-up (бот смотрит чаты с активностью за 3 дня)


def manager_table(states, day):
    """Метрики за день по менеджерам. states: список DialogState (все диалоги с активностью за день)."""
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    M = defaultdict(lambda: dict(dialogs=0, msgs=0, fr=[], waiting=0, fu_done=0, fu_due=0, hold=0, model=0, new=0,
                                 price_asked=0, price_missing=0))
    for s in states:
        for (d, a), n in s.out_by_day.items():
            if d == day:
                M[a]["msgs"] += n
        participants = {a for (d, a) in s.out_by_day if d == day}
        for a in participants:
            M[a]["dialogs"] += 1
        new = s.first_request_ts and start <= s.first_request_ts < end
        if new and s.first_response_biz_sec is not None and s.first_response_by:
            M[s.first_response_by]["fr"].append(s.first_response_biz_sec)
        owner = s.owner
        if new:
            M[owner]["new"] += 1
            if s.model:
                M[owner]["model"] += 1
            if s.price_asked:
                M[owner]["price_asked"] += 1
                if not s.price_given:
                    M[owner]["price_missing"] += 1
        if s.waiting_since is not None:
            M[owner]["waiting"] += 1
            if s.waiting_on_hold:
                M[owner]["hold"] += 1
        if s.followup_due:
            M[owner]["fu_due"] += 1
        for ts, a in s.followups:  # follow-up за FU_DAYS дней по день отчета: та же база, что у «FU!»
            if end - timedelta(days=FU_DAYS) <= ts < end:
                M[a]["fu_done"] += 1
    return M


def daily_report(states, day, now):
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    new = [s for s in states if s.first_request_ts and start <= s.first_request_ts < end]
    night = [s for s in new if not schedule.on_shift(None, s.first_request_ts)]
    fr = [s.first_response_biz_sec for s in new if s.first_response_biz_sec is not None]
    fr_cal = [s.first_response_sec for s in new if s.first_response_sec is not None]
    waiting = [s for s in states if s.waiting_since is not None]
    due = [s for s in states if s.followup_due]
    model = [s for s in new if s.model]
    unattr = sum(s.n_out_unattr for s in states)
    out_total = sum(s.n_out for s in states)
    L = [f"<b>Чаты за {day:%d.%m.%Y}</b> (на {now:%H:%M})", ""]
    L.append(f"Новых обращений: <b>{len(new)}</b>, из них вне рабочего времени {len(night)} ({pct(len(night), len(new))})")
    L.append(f"Первый ответ, медиана: <b>{fmt_min(median(fr)) if fr else '–'}</b> по сменам, {fmt_min(median(fr_cal)) if fr_cal else '–'} по календарю")
    L.append(f"Без первого ответа: {sum(1 for s in new if s.first_response_ts is None)}")
    w_today = [s for s in waiting if start <= s.waiting_since < end]
    L.append(f"Клиент ждет ответа: <b>{len(w_today)}</b> с сегодняшнего дня, еще {len(waiting) - len(w_today)} с прошлых дней "
             f"(после «менеджер напишет / уточню»: {sum(1 for s in waiting if s.waiting_on_hold)})")
    off = [s for s in waiting if s.owner != "Нет менеджера" and not schedule.shift(s.owner, now.date())]
    if off and day == now.date():
        by = defaultdict(int)
        for s in off:
            by[short(s.owner)] += 1
        L.append(f"Ждут у менеджеров на выходном: <b>{len(off)}</b> ({', '.join(f'{a} {n}' for a, n in by.items())}), нужно передать")
    fu_done = sum(1 for s in states for ts, a in s.followups if end - timedelta(days=FU_DAYS) <= ts < end)
    L.append(f"Follow-up за {FU_DAYS} дня: сделано <b>{fu_done}</b>, нужно сделать сейчас <b>{len(due)}</b> "
             f"(сделано {pct(fu_done, fu_done + len(due))})")
    L.append(f"Образцовых диалогов: {len(model)} из {len(new)} ({pct(len(model), len(new))})")
    if out_total:
        tail = ", засчитаны ответственному по сделке" if config.UNATTR_TO_RESPONSIBLE and config.SOURCE == "comments" else ""
        L.append(f"Исходящих без автора (с телефона): {unattr} из {out_total} ({pct(unattr, out_total)}){tail}")
    L += ["", "<b>По менеджерам</b>", "<pre>"]
    L.append(f"{'Менеджер':<13}{'Дл':>4}{'Отв':>8}{'Ждут':>5}{'FU':>4}{'FU!':>4}")
    M = manager_table(states, day)
    for a, v in sorted(M.items(), key=lambda kv: -kv[1]["dialogs"]):
        if a in config.EXCLUDED_NAMES:
            continue
        fr_m = fmt_min(median(v["fr"])) if v["fr"] else "–"
        L.append(f"{escape(short(a))[:12]:<13}{v['dialogs']:>4}{fr_m:>8}{v['waiting']:>5}{v['fu_done']:>4}{v['fu_due']:>4}")
    L.append("</pre>")
    L.append("Дл = диалогов с ответом за день, Отв = медиана первого ответа (по смене менеджера), "
             f"Ждут = клиенты без ответа, FU = follow-up сделано за {FU_DAYS} дня, FU! = follow-up нужно сделать сейчас")
    return "\n".join(L)


def chat_ref(chat_id, label="чат"):
    """Ссылка на чат для Telegram. Чаты Wazzup (wz:<телефон>:<канал>) ссылки в Битрикс24 не имеют: показываем номер,
    по нему чат находится в Wazzup."""
    if str(chat_id).startswith("deal"):
        portal = config.BITRIX_WEBHOOK.split("/rest/")[0]
        return f"<a href=\"{portal}/crm/deal/details/{chat_id[4:]}/\">{'Открыть сделку' if label != 'чат' else 'сделка'} {chat_id[4:]}</a>"
    if str(chat_id).startswith("wz:"):
        return f"WhatsApp +{escape(str(chat_id).split(':')[1])}"
    return f"<a href=\"{chat_link(chat_id)}\">{label} {chat_id}</a>"


def chat_link(chat_id):
    portal = config.BITRIX_WEBHOOK.split("/rest/")[0]
    return f"{portal}/online/?IM_DIALOG=chat{chat_id}" if portal else f"chat{chat_id}"


def wait_alert(s, level):
    head = "⏰ Клиент ждет ответа" if level == 1 else "🔴 Клиент ждет ответа больше часа"
    hold = " (было только «менеджер напишет / уточню»)" if s.waiting_on_hold else ""
    return (f"{head}{hold}\n"
            f"Менеджер: <b>{escape(short(s.owner))}</b>\n"
            f"Ждет: {s.waiting_biz_min:.0f} мин рабочего времени (с {s.waiting_since:%d.%m %H:%M})\n"
            f"Тема: {escape(need_text(s))}\n"
            f"{chat_ref(s.chat_id, 'Открыть чат')}")


def need_text(s):
    from .analytics import need_labels
    return need_labels(s.needs)


def morning_digest(states, now):
    """Утро: ночные обращения без ответа и список follow-up по менеджерам."""
    night_wait = [s for s in states if s.waiting_since is not None and not schedule.on_shift(None, s.waiting_since)]
    due = defaultdict(list)
    for s in states:
        if s.followup_due:
            due[s.owner].append(s)
    L = [f"<b>Доброе утро. Сводка на {now:%d.%m %H:%M}</b>", ""]
    L.append(f"Ночные и вечерние обращения без ответа: <b>{len(night_wait)}</b>")
    by = defaultdict(int)
    for s in night_wait:
        by[s.owner] += 1
    for a, n in sorted(by.items(), key=lambda kv: -kv[1]):
        L.append(f"• {escape(short(a))}: {n}")
    L += ["", f"Нужен follow-up сегодня: <b>{sum(len(v) for v in due.values())}</b>"]
    for a, lst in sorted(due.items(), key=lambda kv: -len(kv[1])):
        kinds = defaultdict(int)
        for s in lst:
            kinds[{"price": "после цены", "offer": "после предложения", "question": "после вопроса"}.get(s.last_out_kind, "другое")] += 1
        L.append(f"• {escape(short(a))}: {len(lst)} ({', '.join(f'{k} {v}' for k, v in kinds.items())})")
    return "\n".join(L)


def followup_list(states, manager):
    lst = [s for s in states if s.followup_due and s.owner == manager]
    if not lst:
        return None
    L = [f"<b>{escape(short(manager))}, напишите повторно этим клиентам</b> ({len(lst)}):"]
    for s in sorted(lst, key=lambda s: s.last_out_ts or datetime.min)[:30]:
        what = {"price": "цена отправлена", "offer": "предложение отправлено", "question": "задан вопрос"}.get(s.last_out_kind, "ответ отправлен")
        L.append(f"• {chat_ref(s.chat_id)}: {what} {s.last_out_ts:%d.%m}")
    return "\n".join(L)


def team_names(states, day):
    """Менеджеры, о которых есть что сказать: отвечали за день, ведут ждущих клиентов или follow-up."""
    M = manager_table(states, day)
    return sorted((a for a, v in M.items() if a not in config.EXCLUDED_NAMES and a != "Нет менеджера"
                   and (v["dialogs"] or v["waiting"] or v["fu_due"] or v["fu_done"] or v["new"])), key=short)


def manager_card(states, name, day, now, limit=10):
    """Аналитика одного менеджера: за день и что висит сейчас (со ссылками на сделки)."""
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    v = manager_table(states, day).get(name) or dict(dialogs=0, msgs=0, fr=[], waiting=0, fu_done=0, fu_due=0, hold=0,
                                                       model=0, new=0, price_asked=0, price_missing=0)
    team_fr = [s.first_response_biz_sec for s in states
               if s.first_request_ts and start <= s.first_request_ts < end and s.first_response_biz_sec is not None]
    mine = [s for s in states if s.owner == name]
    waiting = sorted((s for s in mine if s.waiting_since is not None), key=lambda s: s.waiting_since)
    due = sorted((s for s in mine if s.followup_due), key=lambda s: s.last_out_ts or datetime.min)
    unattr = sum(s.n_out_unattr for s in mine)
    L = [f"<b>{escape(name)}</b> · {day:%d.%m.%Y} (на {now:%H:%M})", f"Смена: {schedule.describe(name, day)}", "", "<b>За день</b>"]
    L.append(f"• Диалогов с ответом: <b>{v['dialogs']}</b>, отправлено сообщений: {v['msgs']}")
    L.append(f"• Новых обращений: {v['new']}, первый ответ (медиана, по смене): "
             f"<b>{fmt_min(median(v['fr'])) if v['fr'] else '–'}</b> (по команде {fmt_min(median(team_fr)) if team_fr else '–'})")
    L.append(f"• Образцовых диалогов: {v['model']} из {v['new']} ({pct(v['model'], v['new'])})")
    if v["price_asked"]:
        L.append(f"• Спрашивали цену: {v['price_asked']}, цену не назвали: {v['price_missing']}")
    L += ["", "<b>Сейчас</b>"]
    L.append(f"• Клиенты ждут ответа: <b>{len(waiting)}</b>"
             + (f" (после «менеджер напишет / уточню»: {v['hold']})" if v["hold"] else ""))
    L.append(f"• Follow-up: сделано за {FU_DAYS} дня <b>{v['fu_done']}</b>, нужно сделать <b>{len(due)}</b>")
    if unattr and config.UNATTR_TO_RESPONSIBLE:
        L.append(f"• Ответов «Телефон» засчитано как ответственному: {unattr}")
    if waiting:
        L += ["", "<b>Ждут ответа</b>, самые давние:"]
        for s in waiting[:limit]:
            hold = ", было «менеджер напишет»" if s.waiting_on_hold else ""
            L.append(f"• {chat_ref(s.chat_id)}: с {s.waiting_since:%d.%m %H:%M}{hold}")
        if len(waiting) > limit:
            L.append(f"… и еще {len(waiting) - limit}")
    if due:
        L += ["", "<b>Нужен follow-up</b>:"]
        for s in due[:limit]:
            what = {"price": "цена отправлена", "offer": "предложение отправлено", "question": "задан вопрос"}.get(s.last_out_kind, "ответ отправлен")
            L.append(f"• {chat_ref(s.chat_id)}: {what} {s.last_out_ts:%d.%m}")
        if len(due) > limit:
            L.append(f"… и еще {len(due) - limit}")
    return "\n".join(L)


TIPS = {
    "slow": "Отвечайте на первое сообщение в течение 15 минут своей смены, и сразу по сути: цена, даты, варианты.",
    "noanswer": "На каждое новое обращение нужен содержательный ответ, а не только приветствие или «менеджер напишет».",
    "price": "Если клиент спрашивает цену, называйте цену или вилку в первом же ответе.",
    "open": "Закрывайте все вопросы клиента: даты, места, отель, перелет, документы.",
    "waiting": "Ответьте клиентам, которые ждут: последнее сообщение в чате от них.",
    "hold": "Если пообещали уточнить, вернитесь с ответом в тот же день.",
    "fu": "Напишите повторно клиентам, которые замолчали после цены или предложения.",
    "hot": "Клиент готов покупать: предложите бронь и следующий шаг.",
}


def dialog_issues(s, name, day):
    """Замечания по одному диалогу: [(ключ, текст)]. Тексты клиента не используются, только признаки."""
    from .analytics import need_labels
    start = datetime.combine(day, datetime.min.time())
    new = s.first_request_ts and start <= s.first_request_ts < start + timedelta(days=1)
    out = []
    if new and s.first_response_ts is None:
        out.append(("noanswer", "нет содержательного ответа на обращение"))
    elif new and s.first_response_by == name and (s.first_response_biz_sec or 0) > 900:
        out.append(("slow", f"первый ответ через {fmt_min(s.first_response_biz_sec)} рабочего времени (норма 15 мин)"))
    if s.price_asked and not s.price_given:
        out.append(("price", "спросили цену, цена не названа"))
    open_needs = s.needs - s.covered - {"price"}
    if open_needs:
        out.append(("open", "не закрыто: " + need_labels(open_needs).lower()))
    if s.waiting_since is not None:
        if s.waiting_on_hold:
            out.append(("hold", f"обещали уточнить и не вернулись (клиент ждет с {s.waiting_since:%d.%m %H:%M})"))
        else:
            out.append(("waiting", f"клиент ждет ответа с {s.waiting_since:%d.%m %H:%M}"))
    if s.followup_due:
        what = {"price": "после цены", "offer": "после предложения", "question": "после вопроса"}.get(s.last_out_kind, "")
        out.append(("fu", f"нужен повторный контакт {what}".rstrip()))
    if s.client_hot and not s.client_booked and s.waiting_since is None and not s.followup_due:
        out.append(("hot", "клиент готов покупать, бронь не предложена"))
    return out


def review(states, name, day, now, limit=20):
    """Разбор диалогов менеджера за день: итог, что улучшить, по каждой сделке замечания."""
    from collections import Counter
    from .analytics import need_labels
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    mine = [s for s in states if (day, name) in s.out_by_day
            or (s.owner == name and s.first_request_ts and start <= s.first_request_ts < end)]
    L = [f"<b>Разбор диалогов: {escape(name)}</b> за {day:%d.%m.%Y} (на {now:%H:%M})",
         f"Смена: {schedule.describe(name, day)}", ""]
    if not mine:
        L.append("За этот день диалогов нет.")
        return "\n".join(L)
    rows = [(s, dialog_issues(s, name, day)) for s in mine]
    cnt = Counter(k for _, iss in rows for k, _ in iss)
    good = [s for s, iss in rows if not iss]
    model = [s for s in mine if s.model]
    fr = [s.first_response_biz_sec for s in mine if s.first_response_by == name and s.first_response_biz_sec is not None
          and s.first_request_ts and start <= s.first_request_ts < end]
    L.append(f"Диалогов: <b>{len(mine)}</b>, без замечаний: {len(good)}, образцовых: {len(model)}")
    L.append(f"Первый ответ, медиана по вашей смене: <b>{fmt_min(median(fr)) if fr else '–'}</b>")
    if cnt:
        L += ["", "<b>Что улучшить</b>"]
        for k, n in cnt.most_common(3):
            L.append(f"• {TIPS[k]} ({n})")
        L += ["", "<b>По сделкам</b>"]
        bad = sorted(((s, iss) for s, iss in rows if iss), key=lambda x: -len(x[1]))
        for s, iss in bad[:limit]:
            L.append(f"• {chat_ref(s.chat_id)} ({escape(need_labels(s.needs).lower())}): " + "; ".join(t for _, t in iss))
        if len(bad) > limit:
            L.append(f"… и еще {len(bad) - limit}")
    else:
        L.append("Замечаний нет, отличная работа.")
    return "\n".join(L)
