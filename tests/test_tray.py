from tests.fixture import LineCase


class TrayTests(LineCase):
    def test_duplicate_sheet(self):
        edition = self.publish()['edition']
        sheet = self.front(edition, 'A', 'one-sheet')
        self.load('tray-a', 1, sheet['sheet'])
        self.load('tray-a', 2, sheet['sheet'], status=409)
        frozen = self.dispatch('tray-a')
        self.assertEqual([(slot['slot'], slot['sheet']) for slot in frozen['slots']], [(1, sheet['sheet'])])
        self.assertEqual(self.line.count('desk', 'loaded_slots'), 1)

    def test_slot_and_edition(self):
        edition = self.publish()['edition']
        other_edition = self.publish(('另册',))['edition']
        first = self.front(edition, 'A', 'first-sheet')
        second = self.front(edition, 'B', 'second-sheet')
        other = self.front(other_edition, 'A', 'foreign-sheet')
        loaded = self.load('tray-a', 1, first['sheet'], direction='foot')
        self.assertEqual((loaded['edition'], loaded['fold'], loaded['direction']), (edition, 'A', 'foot'))
        self.load('tray-a', 1, second['sheet'], status=409)
        self.load('tray-a', 2, other['sheet'], status=409)
        frozen = self.dispatch('tray-a')
        self.assertEqual(frozen['edition'], edition)
        self.assertEqual(frozen['slots'], [{'slot': 1, 'sheet': first['sheet'], 'direction': 'foot',
                                           'fold': 'A', 'front': [None, '1'], 'back': ['2', None]}])

    def test_empty_dispatch(self):
        self.dispatch('empty', 409)
        self.get('desk', '/trays/empty/order', 404)
        self.assertEqual(self.line.count('desk', 'tray_orders'), 0)
        edition = self.publish()['edition']
        sheet = self.front(edition, 'A', 'late-sheet')
        self.load('empty', 1, sheet['sheet'])
        self.assertEqual(self.dispatch('empty')['slots'][0]['sheet'], sheet['sheet'])

    def test_sealed_snapshot(self):
        edition, frozen, _ = self.loaded_order(tray='sealed')
        extra = self.front(edition, 'B', 'late-insert')
        self.load('sealed', 2, extra['sheet'], status=409)
        self.assertEqual(self.line.count('desk', 'loaded_slots'), 1)
        self.assertEqual(self.dispatch('sealed'), frozen)
        self.assertEqual(self.get('desk', '/trays/sealed/order'), frozen)
        self.assertEqual(self.get('desk', f'/orders/{frozen["order"]}'), frozen)
