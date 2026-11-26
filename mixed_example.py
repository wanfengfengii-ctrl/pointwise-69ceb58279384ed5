"""Prepare the two mixed-tray examples using the original print-line API."""
import json

from demo import call
from tests.fixture import DAY_PAGES, PAPER, PressLine


EQUAL_BACK_PAGES = ('封', '同左', '里', '同左', '同右', '折', '同右', '尾')


def front_sample(line, *, equal_back=False):
    pages = EQUAL_BACK_PAGES if equal_back else DAY_PAGES
    expected = {'A': ['同左', '同右'], 'B': ['同左', '同右']} if equal_back else {
        'A': ['2', None], 'B': ['4', '5'],
    }
    draft = call(line, 'desk', 'POST', '/drafts', {'pages': list(pages), 'paper': PAPER})
    edition = call(line, 'desk', 'POST', '/editions', {'draft': draft['draft']})
    edition_id = edition['edition']
    back_by_fold = {fold['fold']: fold['back'] for fold in edition['folds']}
    if back_by_fold != expected:
        raise AssertionError((back_by_fold, expected))
    fronts = {}
    for fold in expected:
        front = call(line, 'desk', 'POST', '/front', {
            'edition': edition_id, 'fold': fold, 'paper': PAPER,
            'request': f'mixed-example-{edition_id}-{fold}',
        })
        if front['edition'] != edition_id or front['fold'] != fold:
            raise AssertionError(front)
        fronts[fold] = front
    if fronts['A']['sheet'] == fronts['B']['sheet']:
        raise AssertionError(fronts)
    return {'edition': edition_id, 'fronts': fronts, 'back_by_fold': back_by_fold}


def main():
    with PressLine() as line:
        different = front_sample(line)
        same = front_sample(line, equal_back=True)
    print(json.dumps({'different_backs': different, 'same_back': same}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
