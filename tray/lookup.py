from tray.orders import TrayOrder, TrayOrderSlot, find_tray_order


def read_dispatched_tray(db, tray: str) -> TrayOrder:
    result = find_tray_order(db, tray=tray)
    if result is None:
        raise LookupError(f'tray {tray} has no dispatched order')
    return result


def read_dispatched_order(db, order: int) -> TrayOrder:
    result = find_tray_order(db, order=order)
    if result is None:
        raise LookupError(f'unknown tray order {order}')
    return result


def find_order_slot(order: TrayOrder, slot: int) -> TrayOrderSlot:
    for item in order.slots:
        if item.slot == slot:
            return item
    raise LookupError(f'order {order.order} has no slot {slot}')
