from collections import Counter

from tests.fixture import DAY_PAGES, PAPER, LineCase


class EditionTests(LineCase):
    def test_three_pages(self):
        proof = self.post('desk', '/drafts', {'pages': ['1', '2', '3'], 'paper': PAPER})
        expected = [{'fold': 'A', 'front': [None, '1'], 'back': ['2', '3']}]
        self.assertEqual(proof['folds'], expected)
        version = self.post('desk', '/editions', {'draft': proof['draft']})
        self.assertEqual(version['folds'], expected)
        self.assertEqual(self.get('desk', f'/editions/{version["edition"]}'), version)

    def test_multi_signature(self):
        version = self.publish()
        self.assertEqual(version['pages'], list(DAY_PAGES))
        self.assertEqual(version['folds'], [
            {'fold': 'A', 'front': [None, '1'], 'back': ['2', None]},
            {'fold': 'B', 'front': [None, '3'], 'back': ['4', '5']},
        ])
        actual = Counter(page for fold in version['folds'] for face in ('front', 'back')
                         for page in fold[face] if page is not None)
        self.assertEqual(actual, Counter(DAY_PAGES))

    def test_version_readback(self):
        original = self.publish(('触读入口', '地层', '海岸'))
        later = self.publish(('新入口', '湿地', '林海'), {'width': 180, 'height': 240})
        self.assertNotEqual(later['edition'], original['edition'])
        self.assertEqual(self.get('desk', f'/editions/{original["edition"]}'), original)
        self.assertEqual(original['paper'], PAPER)
        self.assertEqual(original['folds'][0]['back'], ['地层', '海岸'])

    def test_empty_draft(self):
        for pages in ([], [None]):
            with self.subTest(pages=pages):
                self.post('desk', '/drafts', {'pages': pages, 'paper': PAPER}, 400)
        self.assertEqual(self.line.count('desk', 'drafts'), 0)
        self.post('desk', '/editions', {'draft': 1}, 404)

    def test_invalid_media(self):
        for paper in ({'width': 0, 'height': 297}, {'width': 210, 'height': 297.5},
                      {'width': True, 'height': 297}):
            with self.subTest(paper=paper):
                self.post('desk', '/drafts', {'pages': ['入口'], 'paper': paper}, 400)
        self.assertEqual(self.line.count('desk', 'drafts'), 0)
        self.post('desk', '/editions', {'draft': 1}, 404)

    def test_unknown_draft(self):
        self.post('desk', '/editions', {'draft': 99}, 404)
        self.assertEqual(self.line.count('desk', 'editions'), 0)
        self.get('desk', '/editions/1', 404)
