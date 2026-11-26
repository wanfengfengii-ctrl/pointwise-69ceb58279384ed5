import json
import sqlite3
from dataclasses import dataclass

from edition.pages import Page
from edition.snapshots import PaperSpec, parse_paper_spec
from tray.orders import TrayOrder, TrayOrderSlot
from tray.orientation import FeedDirection, parse_feed_direction


@dataclass(frozen=True)
class BackImpression:
    sequence: int
    order: int
    tray: str
    slot: int
    edition: int
    sheet: int
    fold: str
    paper: PaperSpec
    direction: FeedDirection
    back: tuple[Page, Page]
    request: str

    def as_dict(self) -> dict:
        return {
            'sequence': self.sequence, 'order': self.order, 'tray': self.tray,
            'slot': self.slot, 'edition': self.edition, 'sheet': self.sheet, 'fold': self.fold,
            'paper': self.paper.as_dict(), 'direction': self.direction,
            'back': list(self.back), 'request': self.request,
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(data['sequence'], data['order'], data['tray'], data['slot'], data['edition'],
                   data['sheet'], data['fold'], parse_paper_spec(data['paper']),
                   parse_feed_direction(data['direction']), tuple(data['back']), data['request'])


def init_back_history(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS back_impressions (
        sequence INTEGER PRIMARY KEY, work_order INTEGER NOT NULL REFERENCES back_orders(id),
        slot INTEGER NOT NULL, facts TEXT NOT NULL,
        UNIQUE(work_order, slot)
    )''')


def record_impression(db, work: TrayOrder, slot: TrayOrderSlot, request: str) -> BackImpression:
    facts = {
        'tray': work.tray, 'edition': work.edition, 'sheet': slot.sheet, 'fold': slot.pages.fold,
        'paper': work.paper.as_dict(), 'direction': slot.direction,
        'back': list(slot.pages.back), 'request': request,
    }
    cursor = db.execute('INSERT INTO back_impressions(work_order, slot, facts) VALUES (?, ?, ?)',
                        (work.order, slot.slot, json.dumps(facts)))
    return BackImpression.from_dict({'sequence': cursor.lastrowid, 'order': work.order, 'slot': slot.slot, **facts})


def _from_row(row) -> BackImpression:
    sequence, order, slot, payload = row
    return BackImpression.from_dict({'sequence': sequence, 'order': order, 'slot': slot, **json.loads(payload)})


def find_slot_impression(db, order: int, slot: int) -> BackImpression | None:
    row = db.execute('''SELECT sequence, work_order, slot, facts FROM back_impressions
                        WHERE work_order = ? AND slot = ?''', (order, slot)).fetchone()
    return None if row is None else _from_row(row)


def read_impression(db, sequence: int) -> BackImpression:
    row = db.execute('SELECT sequence, work_order, slot, facts FROM back_impressions WHERE sequence = ?',
                     (sequence,)).fetchone()
    if row is None:
        raise LookupError(f'unknown impression {sequence}')
    return _from_row(row)


def list_order_impressions(db, order: int) -> tuple[BackImpression, ...]:
    rows = db.execute('''SELECT sequence, work_order, slot, facts FROM back_impressions
                         WHERE work_order = ? ORDER BY sequence''', (order,))
    return tuple(_from_row(row) for row in rows)
