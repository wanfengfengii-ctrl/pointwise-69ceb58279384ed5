from tests.fixture import LineCase


class BookTests(LineCase):
    def test_missing_back(self):
        edition, frozen, _ = self.loaded_order(('A', 'B'))
        order = frozen['order']
        printed = self.back(order, 1, 'only-a')
        self.assertEqual(self.impressions(order), [printed])
        result = self.finish(edition, ['ordinary'], 409)
        self.assertEqual(result['missing'], ['B'])
        self.assertEqual(result['conflicts'], [])
        self.assertNotIn('book', result)
        self.assertEqual(self.line.count('desk', 'book_receipts'), 0)

    def test_foreign_tray(self):
        edition, regular, _ = self.loaded_order(('A', 'B'), tray='regular')
        _, foreign, _ = self.loaded_order(tray='foreign')
        self.back(regular['order'], 1, 'regular-a')
        self.back(regular['order'], 2, 'regular-b')
        self.back(foreign['order'], 1, 'foreign-a')
        result = self.finish(edition, ['regular', 'foreign'], 409)
        self.assertEqual(result['missing'], [])
        self.assertEqual(result['conflicts'], ['foreign: another edition'])
        self.assertNotIn('book', result)
        self.assertEqual(self.line.count('desk', 'book_receipts'), 0)

    def test_completed_book(self):
        edition, frozen, sheets = self.loaded_order(('A', 'B'))
        order = frozen['order']
        back_b = self.back(order, 2, 'back-b')
        back_a = self.back(order, 1, 'back-a')
        receipt = self.finish(edition, ['ordinary'])
        self.assertEqual(receipt['edition'], edition)
        self.assertEqual([row['fold'] for row in receipt['folds']], ['A', 'B'])
        for row, back in zip(receipt['folds'], (back_a, back_b)):
            self.assertEqual(row['sheet'], sheets[row['fold']]['sheet'])
            self.assertEqual(row['front_source'], sheets[row['fold']])
            self.assertEqual(row['back_source'], back)
            self.assertEqual(row['sequence'], back['sequence'])
        self.line.restart('station')
        self.line.restart('desk')
        self.assertEqual(self.get('desk', f'/books/{receipt["book"]}'), receipt)
        self.assertEqual(self.line.count('desk', 'book_receipts'), 1)

    def test_first_source(self):
        edition, early, first = self.loaded_order(('A',), tray='early')
        _, late, second = self.loaded_order(('A', 'B'), tray='late', edition=edition)
        initial = self.back(early['order'], 1, 'first-a')
        additional = self.back(late['order'], 1, 'second-a')
        self.back(late['order'], 2, 'only-b')
        self.assertLess(initial['sequence'], additional['sequence'])
        self.assertNotEqual(first['A']['sheet'], second['A']['sheet'])
        receipt = self.finish(edition, ['late', 'early'])
        self.assertEqual([row['fold'] for row in receipt['folds']], ['A', 'B'])
        item = receipt['folds'][0]
        self.assertEqual(item['sequence'], initial['sequence'])
        self.assertEqual(item['front_source'], first['A'])
        self.assertEqual(item['back_source'], initial)

    def test_unknown_book(self):
        edition, frozen, _ = self.loaded_order(('A', 'B'))
        self.back(frozen['order'], 1, 'first-back')
        self.back(frozen['order'], 2, 'second-back')
        receipt = self.finish(edition, ['ordinary'])
        self.get('desk', f'/books/{receipt["book"] + 1}', 404)
        self.assertEqual(self.get('desk', f'/books/{receipt["book"]}'), receipt)
