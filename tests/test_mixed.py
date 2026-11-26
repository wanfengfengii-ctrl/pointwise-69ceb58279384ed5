import json

from tests.fixture import LineCase
from mixed_example import EQUAL_BACK_PAGES, front_sample


class MixedTrayTests(LineCase):
    def prepare(self, *, equal_back=False):
        return front_sample(self.line, equal_back=equal_back)

    def open_mixed(self, tray, edition, candidates, status=200):
        return self.post('desk', f'/mixed-trays',
                         {'tray': tray, 'edition': edition, 'candidates': candidates}, status)

    def correct(self, tray, base, slot, candidates, status=200):
        return self.post('desk', f'/mixed-trays/{tray}/correct',
                         {'base': base, 'slot': slot, 'candidates': candidates}, status)

    def permit(self, tray, slot, request, status=200):
        return self.post('desk', f'/mixed-trays/{tray}/permit',
                         {'slot': slot, 'request': request}, status)

    def settle(self, tray, outcome, status=200):
        return self.post('desk', f'/mixed-trays/{tray}/settle', {'outcome': outcome}, status)

    def outcome(self, permit, action, status=200):
        return self.post('station', '/mixed-press/outcome',
                         {'permit': permit, 'action': action}, status)

    def test_open_and_readback(self):
        sample = self.prepare()
        edition = sample['edition']
        state = self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        self.assertEqual(state['revision'], 1)
        self.assertEqual(state['slots'], [
            {'slot': 1, 'candidates': ['A', 'B'], 'permit': None},
            {'slot': 2, 'candidates': ['B'], 'permit': None},
        ])
        self.assertEqual(self.get('desk', '/mixed-trays/mix'), state)

    def test_infeasible_open_rejected(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('dead', edition, {'1': ['B'], '2': ['B']}, 409)
        self.get('desk', '/mixed-trays/dead', 404)
        self.assertEqual(self.line.count('desk', 'mixed_trays'), 0)

    def test_ambiguous_back_waits(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['A', 'B']})
        pending = self.permit('mix', 1, 'maybe', 202)
        self.assertEqual(pending['status'], 'pending')
        # 202 does not reserve the request number.
        self.assertEqual(self.line.count('desk', 'mixed_permit_requests'), 0)
        self.assertEqual(self.line.count('desk', 'mixed_permits'), 0)

    def test_equal_back_edition_permits(self):
        sample = self.prepare(equal_back=True)
        edition = sample['edition']
        self.open_mixed('same', edition, {'1': ['A', 'B'], '2': ['A', 'B']})
        permit = self.permit('same', 1, 'shared')
        self.assertEqual(permit['back'], ['同左', '同右'])
        self.assertEqual(permit['permit'], 'shared')

    def test_tray_name_isolation(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('name-x', edition, {'1': ['A', 'B'], '2': ['B']})
        # A mixed name cannot serve ordinary loading or ordinary sealing.
        sheet = sample['fronts']['A']
        self.post('desk', '/trays/name-x/load',
                  {'slot': 1, 'sheet': sheet['sheet'], 'direction': 'head'}, 409)
        self.post('desk', '/trays/name-x/dispatch', {}, 409)
        # An ordinary name cannot open a mixed tray.
        self.load('plain', 1, sheet['sheet'])
        self.open_mixed('plain', edition, {'1': ['A', 'B'], '2': ['B']}, 409)
        # Reopening an existing mixed tray also conflicts.
        self.open_mixed('name-x', edition, {'1': ['A'], '2': ['B']}, 409)

    def test_invalid_candidate_shape(self):
        sample = self.prepare()
        edition = sample['edition']
        for candidates in ({}, {'1': ['A']}, {'0': ['A'], '2': ['B']},
                           {'1': ['A', 'A'], '2': ['B']}, {'1': ['C'], '2': ['B']},
                           {'1': ['A'], '2': ['B', 'A'], '3': ['B']}):
            with self.subTest(candidates=candidates):
                self.open_mixed('bad', edition, candidates, 400)
        self.assertEqual(self.line.count('desk', 'mixed_trays'), 0)

    def test_revision_corrections_and_constraints(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        self.assertEqual(permit['back'], ['2', None])
        state = self.correct('mix', 1, 1, ['A'])
        self.assertEqual(state['revision'], 2)
        state = self.correct('mix', 2, 2, ['A', 'B'])
        self.assertEqual(state['revision'], 3)
        # A stale base is rejected and leaves the revision untouched.
        self.correct('mix', 2, 1, ['A', 'B'], 409)
        self.assertEqual(self.get('desk', '/mixed-trays/mix')['revision'], 3)
        # Re-widening slot 1 admits an interpretation (slot1=B, slot2=A) whose
        # back breaks the active A permit.
        self.correct('mix', 3, 1, ['A', 'B'], 409)
        self.assertEqual(self.get('desk', '/mixed-trays/mix')['revision'], 3)

    def test_correction_works_with_station_offline(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        self.line.stop('station')
        state = self.correct('mix', 1, 1, ['A'])
        self.assertEqual(state['revision'], 2)
        self.line.restart('station')

    def test_correction_to_no_solution_rejected(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['A', 'B']})
        # Narrowing both slots to the same fold leaves no one-to-one interpretation.
        self.correct('mix', 1, 1, ['A'])
        self.correct('mix', 2, 2, ['A'], 409)
        self.assertEqual(self.get('desk', '/mixed-trays/mix')['revision'], 2)

    def test_permit_replay_and_conflict(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        self.assertEqual(self.permit('mix', 1, 'P'), permit)
        # The same request number cannot be rebound to another slot or tray.
        self.permit('mix', 2, 'P', 409)
        self.open_mixed('other', edition, {'1': ['A'], '2': ['B']})
        self.permit('other', 1, 'P', 409)
        # A second executable permit for the same slot is refused.
        self.permit('mix', 1, 'Q', 409)

    def test_print_first_keeps_back_constraint(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        printed = self.outcome(permit, 'print')
        self.assertEqual(printed['sequence'], 1)
        # Repeating the same action replays the original ending.
        self.assertEqual(self.outcome(permit, 'print'), printed)
        # The reverse action is rejected.
        self.outcome(permit, 'unused', 409)
        self.settle('mix', printed)
        # Printed backs still constrain corrections: after narrowing slot 1 to A
        # and widening slot 2, re-widening slot 1 would admit B's printed-incompatible back.
        self.correct('mix', 1, 1, ['A'])
        self.correct('mix', 2, 2, ['A', 'B'])
        self.correct('mix', 3, 1, ['A', 'B'], 409)
        # A printed slot cannot get a new permit.
        self.permit('mix', 1, 'Q', 409)
        state = self.get('desk', '/mixed-trays/mix')
        self.assertEqual(state['slots'][0]['permit'], {'permit': 'P', 'state': 'printed'})

    def test_unused_first_allows_resign(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        unused = self.outcome(permit, 'unused')
        self.assertIsNone(unused['sequence'])
        self.outcome(permit, 'print', 409)
        self.settle('mix', unused)
        # The unused ending lifts the back constraint after desk verification.
        self.correct('mix', 1, 1, ['A', 'B'])
        self.correct('mix', 2, 2, ['A'])
        # Slot 1 must then be B; the new permit carries B's back.
        new_permit = self.permit('mix', 1, 'Q')
        self.assertEqual(new_permit['back'], ['4', '5'])
        state = self.get('desk', '/mixed-trays/mix')
        self.assertEqual(state['slots'][0]['permit'], {'permit': 'Q', 'state': 'active'})
        # A late print attempt under the old permit number is refused.
        self.outcome(permit, 'print', 409)

    def test_settle_requires_station_facts(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        self.line.stop('station')
        fabricated = {**permit, 'action': 'unused', 'sequence': None}
        self.settle('mix', fabricated, 503)
        self.line.restart('station')
        # No station record means the constraint cannot be lifted.
        self.settle('mix', fabricated, 409)
        self.correct('mix', 1, 1, ['A'])
        self.correct('mix', 2, 2, ['A', 'B'])
        self.correct('mix', 3, 1, ['A', 'B'], 409)

    def test_settle_rejects_wrong_binding(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        self.outcome(permit, 'print')
        fact = self.get('station', '/mixed-press/outcome/P')
        wrong = dict(fact)
        wrong['slot'] = 2
        self.settle('mix', wrong, 409)
        # The genuine outcome still settles.
        self.settle('mix', fact)

    def test_repeated_settle_is_idempotent(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        p = self.permit('mix', 1, 'P')
        self.settle('mix', self.outcome(p, 'unused'))
        self.correct('mix', 1, 1, ['A', 'B'])
        self.correct('mix', 2, 2, ['A'])
        q = self.permit('mix', 1, 'Q')
        # Re-settling P replays the original ending and never touches Q.
        old_outcome = self.get('station', '/mixed-press/outcome/P')
        again = self.settle('mix', old_outcome)
        self.assertEqual(again['action'], 'unused')
        self.assertEqual(self.get('desk', '/mixed-trays/mix')['slots'][0]['permit'],
                         {'permit': 'Q', 'state': 'active'})
        self.assertEqual(q, self.permit('mix', 1, 'Q'))

    def test_repeated_settle_replays_while_station_offline(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        p = self.permit('mix', 1, 'P')
        original = self.settle('mix', self.outcome(p, 'unused'))
        self.line.stop('station')
        # The already-verified ending is replayed from the desk's own durable copy.
        replay = self.settle('mix', original)
        self.assertEqual(replay, original)
        # A different ending cannot overwrite the settled one, even offline.
        self.settle('mix', {**original, 'action': 'print', 'sequence': 9}, 409)
        self.line.restart('station')

    def test_outcome_persistence_across_restart(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        pending = self.line.defer('station', 'POST', '/mixed-press/outcome',
                                  {'permit': permit, 'action': 'print'})
        self.get('station', '/mixed-press/outcome/P', 404)
        self.assertIsNone(pending.release(discard_reply=True))
        self.line.restart('station')
        recovered = self.get('station', '/mixed-press/outcome/P')
        self.assertEqual(recovered['action'], 'print')
        self.assertEqual(recovered['sequence'], 1)
        self.line.restart('desk')
        settled = self.settle('mix', recovered)
        self.assertEqual(settled['permit'], 'P')

    def test_unknown_and_unsigned_permits(self):
        self.get('station', '/mixed-press/outcome/ghost', 404)
        status, body = self.line.call('station', 'POST', '/mixed-press/outcome', {
            'permit': {'permit': 'ghost', 'tray': 't', 'edition': 1, 'slot': 1,
                       'back': ['x', None]}, 'action': 'print',
        })
        self.assertEqual(status, 404, body)
        self.assertEqual(self.line.count('station', 'mixed_press_outcomes'), 0)

    def test_finish_requires_every_printed_slot(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        p1 = self.permit('mix', 1, 'P1')
        self.settle('mix', self.outcome(p1, 'print'))
        result = self.post('desk', '/books/finish',
                           {'edition': edition, 'trays': ['mix']}, 409)
        self.assertEqual(result['missing_slots'], [2])
        self.assertNotIn('book', result)
        # An unused permit does not count as a completed slot.
        p2 = self.permit('mix', 2, 'P2')
        self.settle('mix', self.outcome(p2, 'unused'))
        result = self.post('desk', '/books/finish',
                           {'edition': edition, 'trays': ['mix']}, 409)
        self.assertEqual(result['missing_slots'], [2])

    def test_full_mixed_checkout_and_readback(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        p1 = self.permit('mix', 1, 'P1')
        o1 = self.outcome(p1, 'print')
        self.settle('mix', o1)
        p2 = self.permit('mix', 2, 'P2')
        o2 = self.outcome(p2, 'print')
        self.assertEqual(o2['sequence'], 2)
        self.settle('mix', o2)
        receipt = self.post('desk', '/books/finish',
                            {'edition': edition, 'trays': ['mix']})
        expected_slots = [
            {'slot': 1, 'back': ['2', None], 'permit': 'P1', 'sequence': 1},
            {'slot': 2, 'back': ['4', '5'], 'permit': 'P2', 'sequence': 2},
        ]
        self.assertEqual(receipt['tray'], 'mix')
        self.assertEqual(receipt['slots'], expected_slots)
        self.line.restart('desk')
        self.line.restart('station')
        readback = self.get('desk', f"/books/{receipt['book']}")
        self.assertEqual(readback, receipt)

    def test_finish_rejects_mixed_and_ordinary_mix(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        sheet = sample['fronts']['A']
        self.load('plain', 1, sheet['sheet'])
        self.post('desk', '/books/finish',
                  {'edition': edition, 'trays': ['mix', 'plain']}, 409)

    def test_station_registers_permit_for_offline_press(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        self.line.stop('station')
        # Issuance must fail while the station cannot retain the permit.
        self.permit('mix', 1, 'P', 503)
        self.assertEqual(self.line.count('desk', 'mixed_permits'), 0)
        self.line.restart('station')
        permit = self.permit('mix', 1, 'P')
        # The press works with the desk offline: it only needs the original permit.
        self.line.stop('desk')
        outcome = self.outcome(permit, 'print')
        self.assertEqual(outcome['permit'], 'P')
        self.line.restart('desk')
        # Desk verification later fetches the station's durable outcome.
        self.settle('mix', outcome)

    def test_outcome_query_has_no_side_effects(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        self.get('station', '/mixed-press/outcome/P', 404)
        self.assertEqual(self.line.count('station', 'mixed_press_outcomes'), 0)
        self.outcome(permit, 'unused')
        self.get('station', '/mixed-press/outcome/P')
        self.assertEqual(self.line.count('station', 'mixed_press_outcomes'), 1)

    def test_http_input_validation(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        # Unknown named records return 404.
        self.get('desk', '/mixed-trays/ghost', 404)
        # Malformed bodies return 400 rather than 409.
        self.post('desk', '/mixed-trays', {'tray': 'x', 'edition': edition}, 400)
        self.post('desk', '/mixed-trays',
                  {'tray': 'x', 'edition': edition, 'candidates': {'1': ['A'], '2': []}}, 400)
        self.post('desk', '/mixed-trays/mix/correct',
                  {'base': '1', 'slot': 1, 'candidates': ['A']}, 400)
        self.post('desk', '/mixed-trays/mix/correct',
                  {'base': 1, 'slot': 1, 'candidates': ['NOPE']}, 400)
        self.post('desk', '/mixed-trays/mix/permit', {'slot': 1}, 400)
        self.post('desk', '/mixed-trays/mix/settle', {'outcome': {'permit': ''}}, 400)
        self.post('station', '/mixed-press/outcome',
                  {'permit': {'permit': 'P'}, 'action': 'explode'}, 400)
        self.assertEqual(self.line.count('desk', 'mixed_trays'), 1)

    def test_corrections_and_revision_persist_across_restart(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        self.correct('mix', 1, 1, ['A'])
        self.correct('mix', 2, 2, ['A', 'B'])
        expected = self.get('desk', '/mixed-trays/mix')
        self.line.restart('desk')
        self.assertEqual(self.get('desk', '/mixed-trays/mix'), expected)
        self.assertEqual(expected['revision'], 3)

    def test_permit_request_remains_replayable_after_settlement(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        self.settle('mix', self.outcome(permit, 'unused'))
        # The same request number still returns the original permit even after clearing.
        self.assertEqual(self.permit('mix', 1, 'P'), permit)
        state = self.get('desk', '/mixed-trays/mix')
        self.assertEqual(state['slots'][0]['permit'],
                         {'permit': 'P', 'state': 'unused'})

    def test_unknown_tray_routes_are_not_mixed_conflicts(self):
        # An unopened name on the ordinary order route keeps its original 404 semantics.
        self.get('desk', '/trays/never/order', 404)

    def test_station_rejects_tampered_permit(self):
        sample = self.prepare()
        edition = sample['edition']
        self.open_mixed('mix', edition, {'1': ['A', 'B'], '2': ['B']})
        permit = self.permit('mix', 1, 'P')
        tampered = dict(permit)
        tampered['back'] = ['9', '9']
        self.outcome(tampered, 'print', 409)
        self.assertEqual(self.line.count('station', 'mixed_press_outcomes'), 0)
        # The genuine permit still records its first outcome.
        self.outcome(permit, 'print')

