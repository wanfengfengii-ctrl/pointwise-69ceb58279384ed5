import json
import sqlite3
from dataclasses import dataclass

from edition.snapshots import PaperSpec, parse_paper_spec
from tray.lookup import find_order_slot
from tray.orders import TrayOrder, TrayOrderSlot
from tray.orientation import FeedDirection, parse_feed_direction


class BackIntakeConflict(Exception):
    pass


@dataclass(frozen=True)
class BackOrder:
    order: int
    slot: int
    paper: PaperSpec
    direction: FeedDirection
    request: str

    def parameters(self) -> dict:
        return {'order': self.order, 'slot': self.slot,
                'paper': self.paper.as_dict(), 'direction': self.direction}


def parse_back_order(data: dict) -> BackOrder:
    order, slot, request = data.get('order'), data.get('slot'), data.get('request')
    for field, value in (('order', order), ('slot', slot)):
        if type(value) is not int or not 0 < value < 2**63:
            raise ValueError(f'{field} must be a positive integer')
    if not isinstance(request, str) or not request:
        raise ValueError('request must be a nonempty string')
    return BackOrder(order, slot, parse_paper_spec(data.get('paper')),
                     parse_feed_direction(data.get('direction')), request)


def resolve_back_slot(order: BackOrder, fetch_order) -> tuple[TrayOrder, TrayOrderSlot]:
    frozen = fetch_order(order.order)
    if frozen.order != order.order:
        raise BackIntakeConflict('desk returned a different order')
    return frozen, find_order_slot(frozen, order.slot)


def init_back_orders(db: sqlite3.Connection) -> None:
    db.execute('CREATE TABLE IF NOT EXISTS back_orders (id INTEGER PRIMARY KEY, work TEXT NOT NULL)')


def save_work_order_copy(db, order: TrayOrder) -> None:
    payload = json.dumps(order.as_dict(), sort_keys=True)
    db.execute('INSERT INTO back_orders(id, work) VALUES (?, ?) ON CONFLICT(id) DO NOTHING',
               (order.order, payload))
    row = db.execute('SELECT work FROM back_orders WHERE id = ?', (order.order,)).fetchone()
    if row[0] != payload:
        raise BackIntakeConflict('desk order differs from its existing station copy')
