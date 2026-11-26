from dataclasses import dataclass

from acceptance.evidence import SlotEvidence
from back.history import BackImpression
from edition.pages import FoldPages, encode_fold_pages, find_fold_pages
from edition.snapshots import EditionSnapshot
from front.sheets import FrontSheet
from tray.orders import TrayOrder
from tray.orientation import matches_feed_direction


class SlotSourceConflict(Exception):
    pass


@dataclass(frozen=True)
class InspectedFold:
    pages: FoldPages
    sheet: FrontSheet
    impression: BackImpression

    def as_dict(self) -> dict:
        return {
            **encode_fold_pages(self.pages),
            'sheet': self.sheet.sheet,
            'tray': self.impression.tray,
            'order': self.impression.order,
            'slot': self.impression.slot,
            'sequence': self.impression.sequence,
            'front_source': self.sheet.as_dict(),
            'back_source': self.impression.as_dict(),
        }


def inspect_slot(edition: EditionSnapshot, work: TrayOrder, evidence: SlotEvidence) -> InspectedFold | None:
    slot, sheet, back = evidence.slot, evidence.sheet, evidence.impression
    location = f'{work.tray} slot {slot.slot}'
    try:
        expected = find_fold_pages(edition.folds, slot.pages.fold)
    except LookupError as error:
        raise SlotSourceConflict(f'{location}: unknown fold in work order') from error
    if (work.edition, work.paper, slot.pages) != (edition.edition, edition.paper, expected):
        raise SlotSourceConflict(f'{location}: frozen work order disagrees with edition')
    if sheet is None or (sheet.sheet, sheet.edition, sheet.fold, sheet.paper, sheet.front) != (
        slot.sheet, edition.edition, expected.fold, edition.paper, expected.front,
    ):
        raise SlotSourceConflict(f'{location}: front sheet disagrees with work order')
    if back is None:
        return None
    actual_source = (back.order, back.tray, back.slot, back.edition, back.sheet, back.fold)
    expected_source = (work.order, work.tray, slot.slot, edition.edition, sheet.sheet, expected.fold)
    if (actual_source != expected_source or back.paper != work.paper or back.back != expected.back
            or not matches_feed_direction(slot.direction, back.direction)):
        raise SlotSourceConflict(f'{location}: back impression disagrees with work order')
    return InspectedFold(expected, sheet, back)


def pick_first_impression(current: InspectedFold | None, candidate: InspectedFold) -> InspectedFold:
    if current is None or candidate.impression.sequence < current.impression.sequence:
        return candidate
    return current
