import json

from tests.fixture import DAY_PAGES, PAPER, PressLine, back_payload


def call(line, role, method, path, data=None, expected_status=200):
    status, body = line.call(role, method, path, data)
    if status != expected_status:
        raise AssertionError((role, path, expected_status, status, body))
    return body


def main():
    source = {'pages': list(DAY_PAGES), 'paper': PAPER}
    expected = [
        {'fold': 'A', 'front': [None, '1'], 'back': ['2', None]},
        {'fold': 'B', 'front': [None, '3'], 'back': ['4', '5']},
    ]
    with PressLine() as line:
        proof = call(line, 'desk', 'POST', '/drafts', source)
        version = call(line, 'desk', 'POST', '/editions', {'draft': proof['draft']})
        sheets = []
        for slot, fold, direction in ((1, 'A', 'head'), (2, 'B', 'foot')):
            sheet = call(line, 'desk', 'POST', '/front', {
                'edition': version['edition'], 'fold': fold, 'paper': PAPER, 'request': f'day-front-{fold}',
            })
            sheets.append(sheet)
            call(line, 'desk', 'POST', '/trays/day/load', {
                'slot': slot, 'sheet': sheet['sheet'], 'direction': direction,
            })
        order = call(line, 'desk', 'POST', '/trays/day/dispatch', {})
        finish = {'edition': version['edition'], 'trays': ['day']}
        back_a = call(line, 'station', 'POST', '/back', back_payload(order['order'], 1, 'day-back-a'))
        pending = call(line, 'desk', 'POST', '/books/finish', finish, expected_status=409)
        if pending['missing'] != ['B'] or pending['conflicts'] or 'book' in pending:
            raise AssertionError(pending)
        back_b = call(line, 'station', 'POST', '/back', back_payload(order['order'], 2, 'day-back-b', 'foot'))
        issued = call(line, 'desk', 'POST', '/books/finish', finish)
        line.restart('desk')
        readback = call(line, 'desk', 'GET', f'/books/{issued["book"]}')
        downstream = [{key: item[key] for key in ('fold', 'front', 'back')} for item in readback['folds']]
        if proof['folds'] != expected or version['folds'] != expected or downstream != expected:
            raise AssertionError((proof, version, readback))
        if readback != issued or [item['front_source'] for item in readback['folds']] != sheets:
            raise AssertionError(readback)
        if [item['back_source'] for item in readback['folds']] != [back_a, back_b]:
            raise AssertionError(readback)
        if back_a['sequence'] >= back_b['sequence']:
            raise AssertionError((back_a, back_b))
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'N1.multi_signature',
            'input': source,
            'expected': expected,
            'actual': version['folds'],
            'downstream_expected': expected,
            'downstream_actual': downstream,
            'code_paths': ['edition/imposition.py', 'edition/releases.py', 'front/printing.py',
                           'tray/orders.py', 'back/printing.py', 'acceptance/inspection.py',
                           'acceptance/reconcile.py', 'acceptance/readback.py'],
            'oracle': '手写八个页位的五页样例，核对已签存清单的两面和按实物、工位序号关联的 HTTP 原回包',
        }, ensure_ascii=False))
        print(json.dumps({'pending': pending, 'book': readback}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
