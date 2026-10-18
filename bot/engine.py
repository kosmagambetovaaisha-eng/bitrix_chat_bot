"""Один «тик» бота: собрать состояния диалогов, разослать алерты, по расписанию отчеты."""
from datetime import datetime, timedelta

from . import config, reports, schedule, telegram
from .analytics import analyze, in_work_hours, biz_seconds


def load_states(store, now, days=3):
    since = (now - timedelta(days=days)).isoformat(timespec="seconds")
    out = []
    resp = _responsibles(store) if config.UNATTR_TO_RESPONSIBLE else {}
    for chat, msgs in store.messages_for_chats(store.chats_active_since(since)).items():
        r = resp.get(chat[4:]) if chat.startswith("deal") else None
        attributed = 0
        for m in msgs:
            m["ts"] = datetime.fromisoformat(m["ts"])
            if r and m["kind"] == "OUT_UNATTR":  # ответ «Телефон»: засчитываем ответственному по сделке
                m["kind"], m["author"] = "MGR", r
                attributed += 1
        s = analyze(chat, msgs, now)
        s.n_out_unattr = attributed
        if r and not s.last_manager and not s.primary_manager:
            s.primary_manager = r  # никто еще не ответил: чат за ответственным
        by_schedule(s, now)
        out.append(s)
    return out


def by_schedule(s, now):
    """Скорость ответа и ожидание считаем по смене конкретного менеджера (schedule.txt), а не по общему графику."""
    if s.first_response_ts and s.first_response_by not in ("", "Без автора"):
        s.first_response_biz_sec = biz_seconds(s.first_request_ts, s.first_response_ts, s.first_response_by)
    if s.waiting_since is not None and s.owner != "Нет менеджера":
        s.waiting_biz_min = biz_seconds(s.waiting_since, now, s.owner) / 60


def _responsibles(store):
    """deal_id -> каноническое имя ответственного (кроме исключенных в names.txt)."""
    from .parse import canonical
    users = store.users()
    out = {}
    for deal, uid in store.deal_responsibles().items():
        u = users.get(uid)
        if u and u.get("is_employee") and not u.get("is_excluded") and u["name"] not in config.EXCLUDED_NAMES:
            out[deal] = canonical(u["name"])
    return out


def manager_chat(name, store):
    """Telegram-чат менеджера: кому админ выдал доступ в боте, иначе из TG_MANAGER_CHATS. В тестовом режиме никому."""
    if config.TEST_MODE:
        return None
    chats = store.tg_chats("manager", name)
    if chats:
        return chats[0]
    for uid, u in store.users().items():
        if u["name"] == name:
            return config.TG_MANAGER_CHATS.get(uid)
    return None


def run_alerts(store, states, now, dry_run=False):
    """Менеджеру: клиент ждет ответа 15+ мин рабочего времени (по свежим обращениям, пришедшим в рабочее время).
    Руководителю: раз в час список тех, кто ждет 60+ мин. Ожидания старше суток и ночные идут в утреннюю сводку."""
    if not config.ALERTS or not in_work_hours(now):
        return 0
    fresh = [s for s in states if s.waiting_since is not None and s.owner not in config.EXCLUDED_NAMES
             and now - s.waiting_since <= timedelta(hours=24)]
    sent = 0
    for s in fresh:
        today_work = in_work_hours(s.waiting_since, s.owner) and in_work_hours(now, s.owner) and s.waiting_since.date() == now.date()
        if today_work and s.waiting_biz_min >= config.ALERT_WAIT_MIN:
            key = f"wait:{s.chat_id}:{s.waiting_since:%Y%m%d%H%M}"
            if not store.alert_sent(key):
                to = manager_chat(s.owner, store) or config.TG_SUPERVISOR_CHAT
                telegram.send(to, reports.wait_alert(s, 1), dry_run)
                store.mark_alert(key, now.isoformat())
                sent += 1
    overdue = [s for s in fresh if s.waiting_biz_min >= config.ALERT_ESCALATE_MIN]
    hour_key = f"escalate:{now:%Y%m%d%H}"
    if overdue and now.minute >= 0 and not store.alert_sent(hour_key):
        lines = [f"🔴 Ждут ответа больше {config.ALERT_ESCALATE_MIN} мин: <b>{len(overdue)}</b> клиентов"]
        for s in sorted(overdue, key=lambda x: -x.waiting_biz_min)[:25]:
            hold = ", было «менеджер напишет»" if s.waiting_on_hold else ""
            lines.append(f"• {reports.escape(reports.short(s.owner))}: {s.waiting_biz_min:.0f} мин{hold}, "
                         f"{reports.chat_ref(s.chat_id)}")
        telegram.send(config.TG_SUPERVISOR_CHAT, "\n".join(lines), dry_run)
        store.mark_alert(hour_key, now.isoformat())
        sent += 1
    return sent


def due(store, name, hhmm, now, window_min=90):
    """Отчет отправляется один раз в день, в течение window_min минут после назначенного времени
    (чтобы при запуске бота в 18:00 не пришла утренняя сводка)."""
    h, m = map(int, hhmm.split(":"))
    at = now.replace(hour=h, minute=m, second=0)
    if not (at <= now <= at + timedelta(minutes=window_min)) or now.isoweekday() not in config.WORK_DAYS:
        return False
    key = f"report:{name}:{now:%Y-%m-%d}"
    if store.alert_sent(key):
        return False
    store.mark_alert(key, now.isoformat())
    return True


def run_reports(store, states, now, dry_run=False):
    if due(store, "morning", config.MORNING_REPORT_AT, now):
        telegram.send(config.TG_SUPERVISOR_CHAT, reports.morning_digest(states, now), dry_run)
        for name in {s.owner for s in states if s.followup_due}:
            text = reports.followup_list(states, name)
            to = manager_chat(name, store)
            if text and to:
                telegram.send(to, text, dry_run)
    # разбор диалогов: каждому менеджеру после окончания его смены (в тестовом режиме не отправляется)
    for name in reports.team_names(states, now.date()):
        sp = schedule.shift(name, now.date())
        to = manager_chat(name, store)
        key = f"review:{name}:{now:%Y-%m-%d}"
        if to and sp and sp[1] + timedelta(minutes=10) <= now <= sp[1] + timedelta(hours=3) and not store.alert_sent(key):
            telegram.send(to, reports.review(states, name, now.date(), now), dry_run)
            store.mark_alert(key, now.isoformat())
    if due(store, "daily", config.DAILY_REPORT_AT, now):
        telegram.send(config.TG_SUPERVISOR_CHAT, reports.daily_report(states, now.date(), now), dry_run)
        for name in reports.team_names(states, now.date()):
            # тест: карточки всех менеджеров руководителю; потом каждому менеджеру его карточка
            to = config.TG_SUPERVISOR_CHAT if config.TEST_MODE else manager_chat(name, store)
            if to:
                telegram.send(to, reports.manager_card(states, name, now.date(), now), dry_run)


def tick(store, now, dry_run=False):
    states = load_states(store, now)
    n = run_alerts(store, states, now, dry_run)
    run_reports(store, states, now, dry_run)
    return states, n
