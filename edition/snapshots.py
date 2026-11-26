import json
import sqlite3
from dataclasses import dataclass

from edition.pages import FoldPages, decode_fold_pages, encode_fold_pages


@dataclass(frozen=True)
class PaperSpec:
    width: int
    height: int

    def as_dict(self) -> dict:
        return {'width': self.width, 'height': self.height}


def parse_paper_spec(value) -> PaperSpec:
    if not isinstance(value, dict) or value.keys() != {'width', 'height'}:
        raise ValueError('paper requires width and height in millimeters')
    width, height = value['width'], value['height']
    if type(width) is not int or type(height) is not int or min(width, height) <= 0:
        raise ValueError('paper dimensions must be positive integer millimeters')
    return PaperSpec(width, height)


@dataclass(frozen=True)
class EditionSnapshot:
    edition: int
    draft: int
    pages: tuple[str, ...]
    paper: PaperSpec
    folds: tuple[FoldPages, ...]

    def as_dict(self) -> dict:
        return {
            'edition': self.edition,
            'draft': self.draft,
            'pages': list(self.pages),
            'paper': self.paper.as_dict(),
            'folds': [encode_fold_pages(fold) for fold in self.folds],
        }


def init_edition_snapshots(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS editions (
        id INTEGER PRIMARY KEY, draft INTEGER NOT NULL REFERENCES drafts(id),
        snapshot TEXT NOT NULL
    )''')


def insert_snapshot(db, draft, pages, paper, folds) -> EditionSnapshot:
    snapshot = json.dumps({
        'pages': list(pages),
        'paper': paper.as_dict(),
        'folds': [encode_fold_pages(fold) for fold in folds],
    })
    cursor = db.execute('INSERT INTO editions(draft, snapshot) VALUES (?, ?)', (draft, snapshot))
    return EditionSnapshot(cursor.lastrowid, draft, pages, paper, folds)


def fetch_snapshot(db: sqlite3.Connection, edition: int) -> EditionSnapshot | None:
    row = db.execute('SELECT draft, snapshot FROM editions WHERE id = ?', (edition,)).fetchone()
    if row is None:
        return None
    draft, payload = row
    data = json.loads(payload)
    return EditionSnapshot(
        edition, draft, tuple(data['pages']), parse_paper_spec(data['paper']),
        tuple(decode_fold_pages(fold) for fold in data['folds']),
    )
