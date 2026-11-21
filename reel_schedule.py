"""Actual KST wall time gates all schedulers, including delayed events.
Queue rule: one reel per weekday at 17:00 KST, none on Saturday or Sunday.
Posts made directly, outside the queue, are never counted here."""
import datetime as dt
KST=dt.timezone(dt.timedelta(hours=9))
SLOT='A'
OPEN_HOUR=17
def active_slot(at):
    at=at.astimezone(KST)
    return SLOT if at.weekday()<5 and OPEN_HOUR<=at.hour<24 else None

def eligible(q,item,slot,at):
    at=at.astimezone(KST)
    if slot!=SLOT or slot!=active_slot(at) or item.get('slot')!=slot:return False
    scheduled=dt.datetime.fromisoformat(item['scheduled_at'])
    if scheduled.tzinfo is None:raise RuntimeError('Scheduled time must include timezone')
    scheduled=scheduled.astimezone(KST)
    if scheduled.strftime('%H:%M')!=q['slots'][slot] or scheduled.second or scheduled.microsecond:
        raise RuntimeError('Scheduled time does not match its configured slot')
    if at<scheduled:return False
    for row in q['done']:
        stamp=row.get('published_at') or row.get('at')
        if stamp and dt.datetime.fromisoformat(stamp).astimezone(KST).date()==at.date():return False
    return True
