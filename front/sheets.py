import json
import sqlite3
from dataclasses import dataclass

from edition.pages import Page
from edition.snapshots import PaperSpec, parse_paper_spec


@dataclass(frozen=True)
class FrontSheet:
    sheet: int
    edition: int
    fold: str
    paper: PaperSpec
    front: tuple[Page, Page]
    request: str

    def as_dict(self) -> dict:
        return {
            'sheet': self.sheet, 'edition': self.edition, 'fold': self.fold,
            'paper': self.paper.as_dict(), 'front': list(self.front), 'request': self.request,
        }


def init_front_sheets(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS front_sheets (
        id INTEGER PRIMARY KEY, edition INTEGER NOT NULL REFERENCES editions(id),
        fold TEXT NOT NULL, paper TEXT NOT NULL, front TEXT NOT NULL, request TEXT NOT NULL
    )''')


def record_front_sheet(db, edition, fold, paper, front, request) -> FrontSheet:
    cursor = db.execute(
        'INSERT INTO front_sheets(edition, fold, paper, front, request) VALUES (?, ?, ?, ?, ?)',
        (edition, fold, json.dumps(paper.as_dict()), json.dumps(front), request),
    )
    return FrontSheet(cursor.lastrowid, edition, fold, paper, front, request)


def read_front_sheet(db: sqlite3.Connection, sheet: int) -> FrontSheet:
    row = db.execute(
        'SELECT edition, fold, paper, front, request FROM front_sheets WHERE id = ?', (sheet,),
    ).fetchone()
    if row is None:
        raise LookupError(f'unknown front sheet {sheet}')
    edition, fold, paper, front, request = row
    return FrontSheet(sheet, edition, fold, parse_paper_spec(json.loads(paper)), tuple(json.loads(front)), request)
