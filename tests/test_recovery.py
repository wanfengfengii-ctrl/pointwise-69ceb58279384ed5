from back.station_http import initialize_station
from tests.fixture import LineCase, back_payload
from tray.desk_http import initialize_desk


class RecoveryTests(LineCase):
    def test_lost_reply(self):
        edition, frozen, sheets = self.loaded_order()
        order = frozen['order']
        request = self.line.defer('station', 'POST', '/back', back_payload(order, 1, 'held-back'))
        self.assertEqual(self.impressions(order), [])
        self.assertEqual(self.finish(edition, ['ordinary'], 409)['missing'], ['A', 'B'])
        self.assertIsNone(request.release(discard_reply=True))
        committed, = self.impressions(order)
        self.assertEqual(committed['sheet'], sheets['A']['sheet'])
        self.assertEqual(committed['request'], 'held-back')
        self.assertEqual(committed['back'], ['2', None])
        self.line.restart('desk')
        self.line.restart('station')
        self.line.stop('desk')
        self.assertEqual(self.back(order, 1, 'held-back'), committed)
        self.assertEqual(self.impressions(order), [committed])
        self.assertEqual(self.line.count('station', 'back_impressions'), 1)

    def test_repeat_init(self):
        version = self.publish(('馆员自己的展签', '触摸指引', '离场信息'))
        edition, work, sheets = self.loaded_order(tray='custom', edition=version['edition'])
        printed = self.back(work['order'], 1, 'custom-back')
        receipt = self.finish(edition, ['custom'])
        for _ in range(2):
            initialize_desk(self.line.databases['desk'])
            initialize_station(self.line.databases['station'])
        self.line.restart('desk')
        self.line.restart('station')
        self.assertEqual(self.get('desk', f'/editions/{edition}'), version)
        self.assertEqual(self.get('desk', '/trays/custom/order'), work)
        self.assertEqual(self.get('desk', f'/front/{sheets["A"]["sheet"]}'), sheets['A'])
        self.assertEqual(self.get('station', f'/impressions/{printed["sequence"]}'), printed)
        self.assertEqual(self.get('desk', f'/books/{receipt["book"]}'), receipt)
        other = self.publish(('另一份馆员正文',))
        other_edition, other_work, _ = self.loaded_order(tray='next', edition=other['edition'])
        newer = self.back(other_work['order'], 1, 'next-back')
        next_receipt = self.finish(other_edition, ['next'])
        self.assertGreater(newer['sequence'], printed['sequence'])
        self.assertNotEqual(next_receipt['book'], receipt['book'])
        self.assertEqual(self.get('desk', f'/books/{receipt["book"]}'), receipt)

    def test_station_unavailable(self):
        edition, frozen, _ = self.loaded_order(('A', 'B'))
        self.back(frozen['order'], 1, 'back-a')
        self.line.stop('station')
        unavailable = self.finish(edition, ['ordinary'], 503)
        self.assertNotIn('missing', unavailable)
        self.assertNotIn('book', unavailable)
        self.assertEqual(self.line.count('desk', 'book_receipts'), 0)
        self.line.restart('station')
        self.assertEqual(self.finish(edition, ['ordinary'], 409)['missing'], ['B'])
        self.back(frozen['order'], 2, 'back-b')
        self.assertEqual(len(self.finish(edition, ['ordinary'])['folds']), 2)
