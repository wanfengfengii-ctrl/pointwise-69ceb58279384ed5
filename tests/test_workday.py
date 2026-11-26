from tests.fixture import DAY_PAGES, PAPER, LineCase


class WorkdayTests(LineCase):
    def test_five_page_workday(self):
        proof = self.post('desk', '/drafts', {'pages': list(DAY_PAGES), 'paper': PAPER})
        edition = self.post('desk', '/editions', {'draft': proof['draft']})
        a = self.front(edition['edition'], 'A', 'workday-front-a')
        b = self.front(edition['edition'], 'B', 'workday-front-b')
        self.load('workday', 1, a['sheet'])
        self.load('workday', 2, b['sheet'], 'foot')
        work = self.dispatch('workday')
        finished_a = self.back(work['order'], 1, 'workday-back-a')
        missing = self.finish(edition['edition'], ['workday'], 409)
        self.assertEqual((missing['missing'], missing['conflicts']), (['B'], []))
        finished_b = self.back(work['order'], 2, 'workday-back-b', 'foot')
        receipt = self.finish(edition['edition'], ['workday'])
        expected = [('A', [None, '1'], ['2', None]), ('B', [None, '3'], ['4', '5'])]
        self.assertEqual([(row['fold'], row['front'], row['back']) for row in proof['folds']], expected)
        self.assertEqual([(row['fold'], row['front'], row['back']) for row in receipt['folds']], expected)
        self.assertEqual([row['front_source'] for row in receipt['folds']], [a, b])
        self.assertEqual([row['back_source'] for row in receipt['folds']], [finished_a, finished_b])
        self.assertEqual(self.get('desk', f'/books/{receipt["book"]}'), receipt)
