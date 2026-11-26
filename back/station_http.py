import argparse
from contextlib import closing

from back.history import init_back_history, list_order_impressions, read_impression
from back.intake import init_back_orders, parse_back_order
from back.printing import BackPrintConflict, print_back
from back.receipts import init_back_receipts
from mixed.press import (MixedPressConflict, init_mixed_press, read_mixed_outcome,
                         record_mixed_outcome, register_mixed_permit)
from tray.desk_http import (JsonRequestHandler, PeerUnavailable, PrintHTTPServer,
                           get_peer_json, open_database, path_number)
from tray.orders import TrayOrder


class StationRequestHandler(JsonRequestHandler):
    conflict_errors = (BackPrintConflict, MixedPressConflict)

    def _fetch_order(self, order: int) -> TrayOrder:
        data = get_peer_json(self.server.peer, f'/orders/{order}')
        try:
            return TrayOrder.from_dict(data)
        except (KeyError, TypeError, ValueError) as error:
            raise PeerUnavailable('desk work order could not be decoded') from error

    def route(self, db, method, parts, query, data) -> dict:
        match method, parts:
            case 'POST', ['back']:
                return print_back(db, parse_back_order(data), self._fetch_order).as_dict()
            case 'GET', ['impressions', sequence]:
                return read_impression(db, path_number(sequence)).as_dict()
            case 'GET', ['orders', order, 'impressions']:
                facts = list_order_impressions(db, path_number(order))
                return {'impressions': [fact.as_dict() for fact in facts]}
            case 'GET', ['impressions']:
                values = query.get('order')
                if not values:
                    raise ValueError('supply at least one order query parameter')
                orders = tuple(dict.fromkeys(path_number(value) for value in values))
                with db:
                    db.execute('BEGIN')
                    facts = [fact for order in orders for fact in list_order_impressions(db, order)]
                return {'impressions': [fact.as_dict() for fact in sorted(facts, key=lambda fact: fact.sequence)]}
            case 'POST', ['mixed-press', 'permit']:
                register_mixed_permit(db, data)
                return {'status': 'registered'}
            case 'POST', ['mixed-press', 'outcome']:
                permit = data.get('permit')
                action = data.get('action')
                if not isinstance(permit, dict):
                    raise ValueError('permit must be the original permit object')
                if action not in ('print', 'unused'):
                    raise ValueError('action must be print or unused')
                return record_mixed_outcome(db, permit, action)
            case 'GET', ['mixed-press', 'outcome', permit] if permit:
                return read_mixed_outcome(db, permit)
            case _:
                raise LookupError('unknown station route')


def initialize_station(database) -> None:
    with closing(open_database(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        init_back_orders(db)
        init_back_history(db)
        init_back_receipts(db)
        init_mixed_press(db)


def serve_station(database, desk: str, host='127.0.0.1', port=8767) -> PrintHTTPServer:
    initialize_station(database)
    return PrintHTTPServer((host, port), StationRequestHandler, database, desk)


def main() -> None:
    parser = argparse.ArgumentParser(description='Large-print booklets back station')
    parser.add_argument('--db', required=True)
    parser.add_argument('--desk', default='http://127.0.0.1:8766')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    with serve_station(args.db, args.desk, args.host, args.port) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
