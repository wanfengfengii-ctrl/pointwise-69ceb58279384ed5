import sqlite3
from dataclasses import dataclass

from front.sheets import read_front_sheet
from tray.orientation import FeedDirection, parse_feed_direction


class TrayLoadConflict(Exception):
    pass


@dataclass(frozen=True)
class LoadedSlot:
    tray: str
    slot: int
    sheet: int
    edition: int
    fold: str
    direction: FeedDirection

    def as_dict(self) -> dict:
        return {
            'tray': self.tray, 'slot': self.slot, 'sheet': self.sheet,
            'edition': self.edition, 'fold': self.fold, 'direction': self.direction,
        }


@dataclass(frozen=True)
class TrayState:
    edition: int
    sealed: bool


def init_trays(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS trays (
        name TEXT PRIMARY KEY, edition INTEGER NOT NULL REFERENCES editions(id),
        sealed INTEGER NOT NULL DEFAULT 0 CHECK(sealed IN (0, 1))
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS loaded_slots (
        tray TEXT NOT NULL REFERENCES trays(name), slot INTEGER NOT NULL,
        sheet INTEGER NOT NULL REFERENCES front_sheets(id), fold TEXT NOT NULL,
        direction TEXT NOT NULL CHECK(direction IN ('head', 'foot')),
        PRIMARY KEY(tray, slot), UNIQUE(tray, sheet)
    )''')


def read_tray_state(db, tray: str) -> TrayState | None:
    row = db.execute('SELECT edition, sealed FROM trays WHERE name = ?', (tray,)).fetchone()
    return None if row is None else TrayState(row[0], bool(row[1]))


def list_loaded_slots(db, tray: str) -> tuple[LoadedSlot, ...]:
    rows = db.execute('''SELECT loaded_slots.slot, loaded_slots.sheet, trays.edition,
                                loaded_slots.fold, loaded_slots.direction
                         FROM loaded_slots JOIN trays ON trays.name = loaded_slots.tray
                         WHERE trays.name = ? ORDER BY loaded_slots.slot''', (tray,))
    return tuple(LoadedSlot(tray, slot, sheet, edition, fold, parse_feed_direction(direction))
                 for slot, sheet, edition, fold, direction in rows)


def load_slot(db, tray: str, slot: int, sheet: int, direction: FeedDirection) -> LoadedSlot:
    with db:
        db.execute('BEGIN IMMEDIATE')
        state = read_tray_state(db, tray)
        if state is not None and state.sealed:
            raise TrayLoadConflict(f'tray {tray} is sealed')
        source = read_front_sheet(db, sheet)
        if state is None:
            db.execute('INSERT INTO trays(name, edition) VALUES (?, ?)', (tray, source.edition))
        elif state.edition != source.edition:
            raise TrayLoadConflict(f'tray {tray} belongs to another edition')
        occupied = db.execute(
            'SELECT 1 FROM loaded_slots WHERE tray = ? AND (slot = ? OR sheet = ?)',
            (tray, slot, sheet),
        ).fetchone()
        if occupied:
            raise TrayLoadConflict('slot or physical sheet is already loaded in this tray')
        db.execute('INSERT INTO loaded_slots(tray, slot, sheet, fold, direction) VALUES (?, ?, ?, ?, ?)',
                   (tray, slot, sheet, source.fold, direction))
        return LoadedSlot(tray, slot, sheet, source.edition, source.fold, direction)


def mark_tray_sealed(db, tray: str) -> None:
    db.execute('UPDATE trays SET sealed = 1 WHERE name = ?', (tray,))
