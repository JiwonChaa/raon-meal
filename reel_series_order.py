"""Validate explicit series order against confirmed publication history."""
import datetime as dt


def validate_series_order(queue):
    for rule in queue.get('series_order_rules', []):
        expected = rule['ordered_ids']
        if not expected or len(set(expected)) != len(expected):
            raise RuntimeError('Series order requires unique explicit episode IDs')
        wanted = set(expected)
        done = [x for x in queue['done'] if x.get('id') in wanted]
        pending = [x for x in queue['queue'] if x.get('id') in wanted]
        completed = [x['id'] for x in done]
        if completed != expected[:len(completed)]:
            raise RuntimeError('Series publication history is not a consecutive prefix')
        if any(x.get('status') != 'published' or not x.get('media_id') or
               not x.get('published_at') for x in done):
            raise RuntimeError('Completed series episodes require confirmed publication evidence')
        if [x['id'] for x in pending] != expected[len(completed):]:
            raise RuntimeError('Series queue has a missing, duplicate, or out-of-order episode')
        dates = [dt.datetime.fromisoformat(x['scheduled_at']) for x in pending]
        if any(x.tzinfo is None for x in dates) or any(a >= b for a, b in zip(dates, dates[1:])):
            raise RuntimeError('Series schedule must strictly increase with episode order')
