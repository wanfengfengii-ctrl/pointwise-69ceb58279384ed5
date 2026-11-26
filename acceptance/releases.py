import json
import sqlite3
from dataclasses import dataclass

from acceptance.inspection import InspectedFold


@dataclass(frozen=True)
class BookReceipt:
    book: int
    edition: int
    folds: tuple[dict, ...]

    def as_dict(self) -> dict:
        return {'book': self.book, 'edition': self.edition, 'folds': list(self.folds)}


def init_book_receipts(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS book_receipts (
        id INTEGER PRIMARY KEY, edition INTEGER NOT NULL REFERENCES editions(id),
        sources TEXT NOT NULL
    )''')


def issue_book_receipt(db, edition: int, folds: tuple[InspectedFold, ...]) -> BookReceipt:
    sources = tuple(fold.as_dict() for fold in folds)
    with db:
        cursor = db.execute('INSERT INTO book_receipts(edition, sources) VALUES (?, ?)',
                            (edition, json.dumps(sources)))
    return BookReceipt(cursor.lastrowid, edition, sources)
