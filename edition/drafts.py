import json
import sqlite3
from dataclasses import dataclass

from edition.imposition import impose_pages
from edition.pages import FoldPages, decode_fold_pages, encode_fold_pages
from edition.snapshots import PaperSpec, parse_paper_spec


@dataclass(frozen=True)
class DraftProof:
    draft: int
    pages: tuple[str, ...]
    paper: PaperSpec
    folds: tuple[FoldPages, ...]

    def as_dict(self) -> dict:
        return {
            'draft': self.draft,
            'pages': list(self.pages),
            'paper': self.paper.as_dict(),
            'folds': [encode_fold_pages(fold) for fold in self.folds],
        }


def init_drafts(db: sqlite3.Connection) -> None:
    db.execute('CREATE TABLE IF NOT EXISTS drafts (id INTEGER PRIMARY KEY, proof TEXT NOT NULL)')


def create_draft(db: sqlite3.Connection, data: dict) -> DraftProof:
    raw_pages = data.get('pages')
    if not isinstance(raw_pages, list) or not raw_pages or any(not isinstance(page, str) for page in raw_pages):
        raise ValueError('pages must be a nonempty array of text pages')
    pages = tuple(raw_pages)
    paper = parse_paper_spec(data.get('paper'))
    folds = impose_pages(pages)
    proof = json.dumps({
        'pages': raw_pages,
        'paper': paper.as_dict(),
        'folds': [encode_fold_pages(fold) for fold in folds],
    })
    with db:
        cursor = db.execute('INSERT INTO drafts(proof) VALUES (?)', (proof,))
    return DraftProof(cursor.lastrowid, pages, paper, folds)


def read_draft(db: sqlite3.Connection, draft: int) -> DraftProof:
    row = db.execute('SELECT proof FROM drafts WHERE id = ?', (draft,)).fetchone()
    if row is None:
        raise LookupError(f'unknown draft {draft}')
    data = json.loads(row[0])
    return DraftProof(
        draft, tuple(data['pages']), parse_paper_spec(data['paper']),
        tuple(decode_fold_pages(fold) for fold in data['folds']),
    )
