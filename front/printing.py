from front.media import FrontMediaMismatch, check_front_media
from front.orders import FrontOrder, resolve_front_pages
from front.receipts import FrontRequestConflict, find_front_receipt, record_front_receipt
from front.sheets import FrontSheet, read_front_sheet, record_front_sheet


class FrontPrintConflict(Exception):
    pass


def print_front(db, order: FrontOrder) -> FrontSheet:
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            prior = find_front_receipt(db, order)
            if prior is not None:
                return read_front_sheet(db, prior)
            expected, pages = resolve_front_pages(db, order)
            paper = check_front_media(expected, order.paper)
            sheet = record_front_sheet(db, order.edition, order.fold, paper, pages.front, order.request)
            record_front_receipt(db, order, sheet.sheet)
            return sheet
    except (FrontMediaMismatch, FrontRequestConflict) as error:
        raise FrontPrintConflict(str(error)) from error
