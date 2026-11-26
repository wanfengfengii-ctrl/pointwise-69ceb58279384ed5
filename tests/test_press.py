from tests.fixture import PAPER, LineCase


class PressTests(LineCase):
    def test_wrong_media(self):
        edition = self.publish()['edition']
        self.front(edition, 'A', 'paper-retry', {'width': 200, 'height': 297}, 409)
        self.assertEqual(self.line.count('desk', 'front_sheets'), 0)
        self.assertEqual(self.line.count('desk', 'front_receipts'), 0)
        sheet = self.front(edition, 'A', 'paper-retry')
        self.assertEqual(sheet['paper'], PAPER)
        self.assertEqual(sheet['front'], [None, '1'])
        self.assertEqual(self.line.count('desk', 'front_sheets'), 1)

    def test_exact_dimensions(self):
        edition = self.publish()['edition']
        self.front(edition, 'A', 'rotated', {'width': 297, 'height': 210}, 409)
        self.get('desk', '/front/1', 404)
        sheet = self.front(edition, 'A', 'upright')
        self.assertEqual(sheet['sheet'], 1)
        self.assertEqual(sheet['paper'], PAPER)
        self.assertEqual(self.line.count('desk', 'front_sheets'), 1)

    def test_front_replay(self):
        edition = self.publish()['edition']
        first = self.front(edition, 'A', 'front-original')
        self.line.restart('desk')
        self.assertEqual(self.front(edition, 'A', 'front-original'), first)
        self.front(edition, 'B', 'front-original', status=409)
        self.assertEqual(self.get('desk', f'/front/{first["sheet"]}'), first)
        self.assertEqual(self.line.count('desk', 'front_sheets'), 1)

    def test_wrong_orientation(self):
        _, frozen, sheets = self.loaded_order()
        order = frozen['order']
        self.back(order, 1, 'press-direction', direction='foot', status=409)
        self.assertEqual(self.impressions(order), [])
        self.assertEqual(self.line.count('station', 'back_orders'), 0)
        self.assertEqual(self.line.count('station', 'back_receipts'), 0)
        printed = self.back(order, 1, 'press-direction')
        self.assertEqual(printed['sheet'], sheets['A']['sheet'])
        self.assertEqual(printed['direction'], 'head')
        self.assertEqual(self.impressions(order), [printed])

    def test_back_media(self):
        _, frozen, _ = self.loaded_order()
        order = frozen['order']
        self.back(order, 1, 'press-media', paper={'width': 297, 'height': 210}, status=409)
        self.assertEqual(self.impressions(order), [])
        printed = self.back(order, 1, 'press-media')
        self.assertEqual(printed['paper'], PAPER)
        self.assertEqual(self.impressions(order), [printed])

    def test_reopen_receipt(self):
        _, frozen, sheets = self.loaded_order(('A', 'B'))
        order = frozen['order']
        printed = self.back(order, 1, 'press-first')
        self.line.restart('station')
        self.assertEqual(self.back(order, 1, 'press-first'), printed)
        self.back(order, 2, 'press-first', status=409)
        self.assertEqual(printed['sheet'], sheets['A']['sheet'])
        self.assertEqual(self.impressions(order), [printed])
        self.assertEqual(self.get('station', f'/impressions/{printed["sequence"]}'), printed)

    def test_slot_replay(self):
        _, frozen, _ = self.loaded_order()
        order = frozen['order']
        printed = self.back(order, 1, 'first-number')
        self.back(order, 1, 'new-number', direction='foot', status=409)
        self.assertEqual(self.back(order, 1, 'new-number'), printed)
        self.assertEqual(self.impressions(order), [printed])
        self.assertEqual(self.line.count('station', 'back_receipts'), 2)
        self.assertEqual(self.line.count('station', 'back_orders'), 1)

    def test_order_slot_identity(self):
        edition, first, sheets_a = self.loaded_order(tray='a-tray')
        _, second, sheets_b = self.loaded_order(('B',), tray='b-tray', edition=edition)
        impression_a = self.back(first['order'], 1, 'a-back')
        self.line.restart('station')
        impression_b = self.back(second['order'], 1, 'b-back')
        self.assertLess(impression_a['sequence'], impression_b['sequence'])
        self.assertEqual(impression_a['sheet'], sheets_a['A']['sheet'])
        self.assertEqual(impression_b['sheet'], sheets_b['B']['sheet'])
        self.assertEqual(self.impressions(first['order']), [impression_a])
        self.assertEqual(self.impressions(second['order']), [impression_b])
