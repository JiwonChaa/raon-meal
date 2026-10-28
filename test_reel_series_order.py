import copy
import unittest
from reel_series_order import validate_series_order


class SeriesOrderTests(unittest.TestCase):
    def fixture(self):
        return {'series_order_rules': [{'ordered_ids': ['one', 'two', 'three']}],
                'done': [{'id': 'old-mistaken-ten', 'status': 'published'}],
                'queue': [{'id': name, 'scheduled_at': f'2026-11-0{i}T12:00:00+09:00'}
                          for i, name in enumerate(['one', 'two', 'three'], 1)]}

    def test_start_and_complete(self):
        q = self.fixture()
        validate_series_order(q)
        for _ in range(3):
            row = q['queue'].pop(0)
            row.update(status='published', media_id='123', published_at=row['scheduled_at'])
            q['done'].append(row)
            validate_series_order(q)

    def test_reject_missing_first(self):
        q = self.fixture(); q['queue'].pop(0)
        with self.assertRaises(RuntimeError): validate_series_order(q)

    def test_reject_reordered_or_duplicate(self):
        for rows in [[1, 0, 2], [0, 1, 1, 2]]:
            q = self.fixture(); q['queue'] = [q['queue'][i] for i in rows]
            with self.assertRaises(RuntimeError): validate_series_order(q)

    def test_reject_unconfirmed_or_later_history(self):
        for index in [0, 1]:
            q = self.fixture(); q['done'].append(q['queue'].pop(index))
            with self.assertRaises(RuntimeError): validate_series_order(q)

    def test_reject_reversed_schedule(self):
        q = self.fixture(); q['queue'][1]['scheduled_at'] = q['queue'][0]['scheduled_at']
        with self.assertRaises(RuntimeError): validate_series_order(q)

    def test_existing_unrelated_queues_unchanged(self):
        validate_series_order({'queue': [], 'done': []})


if __name__ == '__main__': unittest.main()
