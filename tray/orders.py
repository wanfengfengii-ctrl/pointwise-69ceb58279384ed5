import json
import sqlite3
from dataclasses import dataclass

from edition.pages import FoldPages, decode_fold_pages, encode_fold_pages, find_fold_pages
from edition.releases import read_edition
from edition.snapshots import PaperSpec, parse_paper_spec
from tray.loading import list_loaded_slots, mark_tray_sealed, read_tray_state
from tray.orientation import FeedDirection, parse_feed_direction


class TrayDispatchConflict(Exception):
    pass


@dataclass(frozen=True)
class TrayOrderSlot:
    slot: int
    sheet: int
    direction: FeedDirection
    pages: FoldPages

    def as_dict(self) -> dict:
        return {'slot': self.slot, 'sheet': self.sheet, 'direction': self.direction,
                **encode_fold_pages(self.pages)}

    @classmethod
    def from_dict(cls, data: dict):
        return cls(data['slot'], data['sheet'], parse_feed_direction(data['direction']), decode_fold_pages(data))


@dataclass(frozen=True)
class TrayOrder:
    order: int
    tray: str
    edition: int
    paper: PaperSpec
    slots: tuple[TrayOrderSlot, ...]

    def as_dict(self) -> dict:
        return {
            'order': self.order, 'tray': self.tray, 'edition': self.edition,
            'paper': self.paper.as_dict(), 'slots': [slot.as_dict() for slot in self.slots],
        }

    @classmethod
    def from_dict(cls, data: dict):
        return cls(data['order'], data['tray'], data['edition'], parse_paper_spec(data['paper']),
                   tuple(TrayOrderSlot.from_dict(slot) for slot in data['slots']))


def init_tray_orders(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS tray_orders (
        id INTEGER PRIMARY KEY, tray TEXT NOT NULL UNIQUE REFERENCES trays(name),
        edition INTEGER NOT NULL REFERENCES editions(id), work TEXT NOT NULL
    )''')


def find_tray_order(db, *, tray: str | None = None, order: int | None = None) -> TrayOrder | None:
    if (tray is None) == (order is None):
        raise ValueError('identify the order by exactly one key')
    if order is None:
        row = db.execute('SELECT id, tray, edition, work FROM tray_orders WHERE tray = ?', (tray,)).fetchone()
    else:
        row = db.execute('SELECT id, tray, edition, work FROM tray_orders WHERE id = ?', (order,)).fetchone()
    if row is None:
        return None
    number, name, edition, payload = row
    return TrayOrder.from_dict({'order': number, 'tray': name, 'edition': edition, **json.loads(payload)})


def dispatch_tray(db, tray: str) -> TrayOrder:
    with db:
        db.execute('BEGIN IMMEDIATE')
        prior = find_tray_order(db, tray=tray)
        if prior is not None:
            return prior
        state = read_tray_state(db, tray)
        loaded = list_loaded_slots(db, tray)
        if state is None or not loaded:
            raise TrayDispatchConflict(f'tray {tray} has no loaded slots')
        edition = read_edition(db, state.edition)
        slots = tuple(
            TrayOrderSlot(item.slot, item.sheet, item.direction, find_fold_pages(edition.folds, item.fold))
            for item in loaded
        )
        payload = json.dumps({'paper': edition.paper.as_dict(), 'slots': [slot.as_dict() for slot in slots]})
        cursor = db.execute('INSERT INTO tray_orders(tray, edition, work) VALUES (?, ?, ?)',
                            (tray, edition.edition, payload))
        mark_tray_sealed(db, tray)
        return TrayOrder(cursor.lastrowid, tray, edition.edition, edition.paper, slots)
