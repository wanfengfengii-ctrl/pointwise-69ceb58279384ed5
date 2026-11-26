import json
import sqlite3

from front.orders import FrontOrder


class FrontRequestConflict(Exception):
    pass


def init_front_receipts(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS front_receipts (
        request TEXT PRIMARY KEY, parameters TEXT NOT NULL,
        sheet INTEGER NOT NULL REFERENCES front_sheets(id)
    )''')


def find_front_receipt(db, order: FrontOrder) -> int | None:
    row = db.execute(
        'SELECT parameters, sheet FROM front_receipts WHERE request = ?', (order.request,),
    ).fetchone()
    if row is None:
        return None
    params, sheet = row
    if json.loads(params) != order.parameters():
        raise FrontRequestConflict('front request already succeeded with different parameters')
    return sheet


def record_front_receipt(db, order: FrontOrder, sheet: int) -> None:
    db.execute(
        'INSERT INTO front_receipts(request, parameters, sheet) VALUES (?, ?, ?)',
        (order.request, json.dumps(order.parameters()), sheet),
    )
