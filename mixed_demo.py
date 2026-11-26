"""End-to-end demonstration of mixed-tray back printing over real HTTP.

Covers every drill in MIXED_PRINT.md:
  * open-time identification, pending identification and infeasible rejection;
  * offline-compatible candidate corrections preserving committed backs;
  * print-first vs unused-first outcomes, lost replies, restart recovery;
  * permit clearing, late old permits, re-signing after an unused ending;
  * fixed mixed-tray checkout receipts with slot backs, permits and sequences.
"""
import json

from demo import call
from mixed_example import front_sample


def open_mixed(line, tray, edition, candidates, status=200):
    return call(line, 'desk', 'POST', '/mixed-trays',
                {'tray': tray, 'edition': edition, 'candidates': candidates}, status)


def correct(line, tray, base, slot, candidates, status=200):
    return call(line, 'desk', 'POST', f'/mixed-trays/{tray}/correct',
                {'base': base, 'slot': slot, 'candidates': candidates}, status)


def permit(line, tray, slot, request, status=200):
    return call(line, 'desk', 'POST', f'/mixed-trays/{tray}/permit',
                {'slot': slot, 'request': request}, status)


def outcome(line, permit_obj, action, status=200):
    return call(line, 'station', 'POST', '/mixed-press/outcome',
                {'permit': permit_obj, 'action': action}, status)


def settle(line, tray, outcome_obj, status=200):
    return call(line, 'desk', 'POST', f'/mixed-trays/{tray}/settle',
                {'outcome': outcome_obj}, status)


def finish(line, edition, tray, status=200):
    return call(line, 'desk', 'POST', '/books/finish',
                {'edition': edition, 'trays': [tray]}, status)


def scenario_point(name, payload):
    print('POINTWISE_SCENARIO ' + json.dumps({'case_id': name, **payload}, ensure_ascii=False))


def drill_open_rules(line):
    sample = front_sample(line)
    edition = sample['edition']
    # {A,B}/{B}: slot 1 is forced to A because slot 2 must hold B.
    identified = open_mixed(line, 'identified', edition, {'1': ['A', 'B'], '2': ['B']})
    p = permit(line, 'identified', 1, 'open-permit')
    assert p['back'] == ['2', None], p
    # {A,B}/{A,B}: slot 1 still has two possible backs, so the desk waits (202).
    open_mixed(line, 'ambiguous', edition, {'1': ['A', 'B'], '2': ['A', 'B']})
    pending = permit(line, 'ambiguous', 1, 'held', status=202)
    assert pending['status'] == 'pending', pending
    # {B}/{B}: no one-to-one interpretation exists.
    open_mixed(line, 'impossible', edition, {'1': ['B'], '2': ['B']}, status=409)
    scenario_point('M1.open_rules', {
        'edition': edition,
        'identified_slots': identified['slots'],
        'permit_back': p['back'],
        'pending': pending,
        'impossible_status': 409,
    })
    return sample


def drill_corrections_offline(line, edition):
    tray = 'correction'
    open_mixed(line, tray, edition, {'1': ['A', 'B'], '2': ['B']})
    p = permit(line, tray, 1, 'held-permit')
    assert p['back'] == ['2', None]
    # The station goes offline: corrections are a desk-only compatibility action.
    line.stop('station')
    state = correct(line, tray, 1, 1, ['A'])
    state = correct(line, tray, state['revision'], 2, ['A', 'B'])
    # Re-widening slot 1 would admit B's back against the active A permit.
    correct(line, tray, state['revision'], 1, ['A', 'B'], status=409)
    assert call(line, 'desk', 'GET', f'/mixed-trays/{tray}')['revision'] == state['revision']
    line.restart('station')
    scenario_point('M2.offline_corrections', {
        'tray': tray, 'revision': state['revision'],
        'protected_permit': p['permit'], 'protected_back': p['back'],
    })
    return tray


def drill_print_first(line, edition):
    tray = 'print-first'
    open_mixed(line, tray, edition, {'1': ['A', 'B'], '2': ['B']})
    p = permit(line, tray, 1, 'P-print')
    # Submit at the station and deliberately drop the reply.
    pending = line.defer('station', 'POST', '/mixed-press/outcome',
                         {'permit': p, 'action': 'print'})
    assert call(line, 'station', 'GET', f"/mixed-press/outcome/{p['permit']}",
                expected_status=404) is not None
    pending.release(discard_reply=True)
    # Restart the station and recover the durable first outcome by its permit number.
    line.restart('station')
    printed = call(line, 'station', 'GET', f"/mixed-press/outcome/{p['permit']}")
    assert printed['action'] == 'print' and printed['sequence'] > 0, printed
    # The reverse action can no longer win the first outcome.
    outcome(line, p, 'unused', status=409)
    settle(line, tray, printed)
    # The printed A back still forbids widening slot 1.
    correct(line, tray, 1, 1, ['A'])
    correct(line, tray, 2, 2, ['A', 'B'])
    correct(line, tray, 3, 1, ['A', 'B'], status=409)
    scenario_point('M3.print_first', {
        'tray': tray, 'permit': p['permit'], 'recovered_outcome': printed,
        'reverse_action_status': 409, 'correction_status': 409,
    })
    # Complete slot 2 and check the fixed list out.
    q = permit(line, tray, 2, 'P2-print')
    second = outcome(line, q, 'print')
    assert second['sequence'] == printed['sequence'] + 1, (printed, second)
    settle(line, tray, second)
    receipt = finish(line, edition, tray)
    assert [row['slot'] for row in receipt['slots']] == [1, 2]
    line.restart('desk')
    line.restart('station')
    readback = call(line, 'desk', 'GET', f"/books/{receipt['book']}")
    assert readback == receipt, (readback, receipt)
    scenario_point('M4.print_first_receipt', {
        'book': receipt['book'], 'tray': tray, 'slots': receipt['slots'],
        'readback_after_restart': readback,
    })


def drill_unused_first(line, edition):
    tray = 'unused-first'
    open_mixed(line, tray, edition, {'1': ['A', 'B'], '2': ['B']})
    p = permit(line, tray, 1, 'P-unused')
    unused = outcome(line, p, 'unused')
    assert unused['sequence'] is None, unused
    # A late attempt to print under the same old permit number is refused.
    outcome(line, p, 'print', status=409)
    settle(line, tray, unused)
    # Only the verified unused ending releases the back constraint.
    state = correct(line, tray, 1, 1, ['A', 'B'])
    state = correct(line, tray, state['revision'], 2, ['A'])
    # Slot 1 is now forced to B and may be re-signed with B's back.
    q = permit(line, tray, 1, 'Q-resign')
    assert q['back'] == ['4', '5'], q
    # Re-settling the old permit replays the original ending and never clears Q.
    old_outcome = call(line, 'station', 'GET', f"/mixed-press/outcome/{p['permit']}")
    again = settle(line, tray, old_outcome)
    assert again['action'] == 'unused', again
    assert call(line, 'desk', 'GET', f'/mixed-trays/{tray}')['slots'][0]['permit'] == \
        {'permit': q['permit'], 'state': 'active'}
    # The old permit cannot print after the new permit took the slot.
    outcome(line, p, 'print', status=409)
    scenario_point('M5.unused_first_resign', {
        'tray': tray, 'old_permit': p['permit'], 'new_permit': q['permit'],
        'new_back': q['back'], 'late_old_print_status': 409,
    })
    # Printing the new permit still leaves slot 2 short.
    settle(line, tray, outcome(line, q, 'print'))
    pending = finish(line, edition, tray, status=409)
    assert pending['missing_slots'] == [2], pending
    r = permit(line, tray, 2, 'R-slot2')
    settle(line, tray, outcome(line, r, 'print'))
    receipt = finish(line, edition, tray)
    line.restart('desk')
    readback = call(line, 'desk', 'GET', f"/books/{receipt['book']}")
    assert readback == receipt
    scenario_point('M6.unused_first_receipt', {
        'missing_before_slot2': pending['missing_slots'],
        'book': receipt['book'], 'tray': tray, 'slots': receipt['slots'],
    })


def drill_equal_backs(line):
    sample = front_sample(line, equal_back=True)
    edition = sample['edition']
    open_mixed(line, 'same-back', edition, {'1': ['A', 'B'], '2': ['A', 'B']})
    shared = permit(line, 'same-back', 1, 'shared-back')
    assert shared['back'] == ['同左', '同右'], shared
    scenario_point('M7.equal_back_edition', {
        'edition': edition, 'permit': shared['permit'], 'back': shared['back'],
    })


def main():
    from tests.fixture import PressLine
    with PressLine() as line:
        sample = drill_open_rules(line)
        edition = sample['edition']
        drill_corrections_offline(line, edition)
        drill_print_first(line, edition)
        drill_unused_first(line, edition)
        drill_equal_backs(line)
    print('mixed-tray demonstration finished without assertion failures')


if __name__ == '__main__':
    main()
