from back.history import BackImpression, find_slot_impression, record_impression
from back.intake import BackIntakeConflict, BackOrder, resolve_back_slot, save_work_order_copy
from back.receipts import BackRequestConflict, find_back_receipt, record_back_receipt
from tray.orientation import matches_feed_direction


class BackPrintConflict(Exception):
    pass


def _check_setup(request: BackOrder, paper, direction) -> None:
    if request.paper != paper:
        raise BackPrintConflict('back paper does not match the work order')
    if not matches_feed_direction(direction, request.direction):
        raise BackPrintConflict('back direction does not match the loaded slot')


def print_back(db, request: BackOrder, fetch_order) -> BackImpression:
    try:
        prior = find_back_receipt(db, request)
        if prior is not None:
            return prior
        existing = find_slot_impression(db, request.order, request.slot)
        source = resolve_back_slot(request, fetch_order) if existing is None else None
        with db:
            db.execute('BEGIN IMMEDIATE')
            prior = find_back_receipt(db, request)
            if prior is not None:
                return prior
            impression = find_slot_impression(db, request.order, request.slot)
            if impression is None:
                # An existing impression cannot disappear. Only a new slot uses the desk lookup.
                assert source is not None
                work, slot = source
                _check_setup(request, work.paper, slot.direction)
                save_work_order_copy(db, work)
                impression = record_impression(db, work, slot, request.request)
            else:
                _check_setup(request, impression.paper, impression.direction)
            record_back_receipt(db, request, impression.sequence)
            return impression
    except (BackIntakeConflict, BackRequestConflict) as error:
        raise BackPrintConflict(str(error)) from error
