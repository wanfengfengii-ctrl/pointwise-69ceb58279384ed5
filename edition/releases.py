from edition.drafts import read_draft
from edition.snapshots import EditionSnapshot, fetch_snapshot, insert_snapshot


def publish_edition(db, draft: int) -> EditionSnapshot:
    proof = read_draft(db, draft)
    with db:
        return insert_snapshot(db, proof.draft, proof.pages, proof.paper, proof.folds)


def read_edition(db, edition: int) -> EditionSnapshot:
    snapshot = fetch_snapshot(db, edition)
    if snapshot is None:
        raise LookupError(f'unknown edition {edition}')
    return snapshot
