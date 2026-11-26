import json
import sqlite3

from acceptance.releases import BookReceipt


class BookNotFound(LookupError):
    pass


def read_book_receipt(db: sqlite3.Connection, book: int) -> BookReceipt:
    row = db.execute('SELECT edition, sources FROM book_receipts WHERE id = ?', (book,)).fetchone()
    if row is None:
        raise BookNotFound(f'unknown book {book}')
    edition, sources = row
    return BookReceipt(book, edition, tuple(json.loads(sources)))
