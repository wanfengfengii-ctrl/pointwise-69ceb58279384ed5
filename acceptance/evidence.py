from dataclasses import dataclass

from back.history import BackImpression
from front.sheets import FrontSheet, read_front_sheet
from tray.lookup import read_dispatched_tray
from tray.orders import TrayOrder, TrayOrderSlot


class EvidenceUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SlotEvidence:
    slot: TrayOrderSlot
    sheet: FrontSheet | None
    impression: BackImpression | None


@dataclass(frozen=True)
class TrayEvidence:
    tray: str
    order: TrayOrder | None
    slots: tuple[SlotEvidence, ...] = ()
    conflicts: tuple[str, ...] = ()


def collect_book_evidence(db, edition: int, trays: tuple[str, ...], fetch_impressions) -> tuple[TrayEvidence, ...]:
    orders = {}
    rejected = {}
    for tray in trays:
        try:
            order = read_dispatched_tray(db, tray)
        except LookupError:
            rejected[tray] = TrayEvidence(tray, None, conflicts=(f'{tray}: no dispatched order',))
            continue
        if order.edition != edition:
            rejected[tray] = TrayEvidence(tray, order, conflicts=(f'{tray}: another edition',))
            continue
        orders[tray] = order

    known_slots = {work.order: {slot.slot for slot in work.slots} for work in orders.values()}
    impressions = {order: {} for order in known_slots}
    bad_orders = set()
    if known_slots:
        for fact in fetch_impressions(tuple(known_slots)):
            if fact.order not in known_slots:
                raise EvidenceUnavailable('station returned an impression outside the requested orders')
            facts = impressions[fact.order]
            if fact.slot not in known_slots[fact.order] or fact.slot in facts:
                bad_orders.add(fact.order)
            else:
                facts[fact.slot] = fact

    result = []
    for tray in trays:
        if tray in rejected:
            result.append(rejected[tray])
            continue
        order = orders[tray]
        if order.order in bad_orders:
            conflict = f'{tray}: station returned conflicting slots for order {order.order}'
            result.append(TrayEvidence(tray, order, conflicts=(conflict,)))
            continue
        slots = []
        for slot in order.slots:
            try:
                sheet = read_front_sheet(db, slot.sheet)
            except LookupError:
                sheet = None
            slots.append(SlotEvidence(slot, sheet, impressions[order.order].get(slot.slot)))
        result.append(TrayEvidence(tray, order, tuple(slots)))
    return tuple(result)
