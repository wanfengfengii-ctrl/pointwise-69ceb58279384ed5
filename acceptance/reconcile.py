from dataclasses import dataclass

from acceptance.evidence import collect_book_evidence
from acceptance.inspection import InspectedFold, SlotSourceConflict, inspect_slot, pick_first_impression
from acceptance.releases import BookReceipt, issue_book_receipt
from edition.releases import read_edition


@dataclass(frozen=True)
class FinishCheck:
    edition: int
    folds: tuple[InspectedFold, ...]
    missing: tuple[str, ...]
    conflicts: tuple[str, ...]


class FinishConflict(Exception):
    def __init__(self, check: FinishCheck):
        super().__init__('book cannot be issued')
        self.check = check


def reconcile_book(db, edition: int, trays: tuple[str, ...], fetch_impressions) -> FinishCheck:
    snapshot = read_edition(db, edition)
    evidence = collect_book_evidence(db, edition, trays, fetch_impressions)
    accepted = {}
    conflicts = []
    for tray in evidence:
        conflicts.extend(tray.conflicts)
        if tray.order is None:
            continue
        for item in tray.slots:
            try:
                fold = inspect_slot(snapshot, tray.order, item)
            except SlotSourceConflict as error:
                conflicts.append(str(error))
                continue
            if fold is not None:
                key = fold.pages.fold
                accepted[key] = pick_first_impression(accepted.get(key), fold)
    order = tuple(fold.fold for fold in snapshot.folds)
    return FinishCheck(edition, tuple(accepted[key] for key in order if key in accepted),
                       tuple(key for key in order if key not in accepted), tuple(conflicts))


def finish_book(db, edition: int, trays: tuple[str, ...], fetch_impressions) -> BookReceipt:
    result = reconcile_book(db, edition, trays, fetch_impressions)
    if result.missing or result.conflicts:
        raise FinishConflict(result)
    return issue_book_receipt(db, edition, result.folds)
