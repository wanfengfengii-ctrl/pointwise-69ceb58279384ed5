import json
import sqlite3

from back.history import BackImpression, read_impression
from back.intake import BackOrder


class BackRequestConflict(Exception):
    pass


def init_back_receipts(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS back_receipts (
        request TEXT PRIMARY KEY, parameters TEXT NOT NULL,
        sequence INTEGER NOT NULL REFERENCES back_impressions(sequence)
    )''')


def find_back_receipt(db, order: BackOrder) -> BackImpression | None:
    row = db.execute('SELECT parameters, sequence FROM back_receipts WHERE request = ?',
                     (order.request,)).fetchone()
    if row is None:
        return None
    params, sequence = row
    if json.loads(params) != order.parameters():
        raise BackRequestConflict('back request already succeeded with different parameters')
    return read_impression(db, sequence)


def record_back_receipt(db, order: BackOrder, sequence: int) -> None:
    db.execute('INSERT INTO back_receipts(request, parameters, sequence) VALUES (?, ?, ?)',
               (order.request, json.dumps(order.parameters()), sequence))
