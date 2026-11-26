import argparse
import json
import sqlite3
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

from acceptance.evidence import EvidenceUnavailable
from acceptance.readback import read_book_receipt
from acceptance.reconcile import FinishConflict, finish_book
from acceptance.releases import init_book_receipts
from back.history import BackImpression
from edition.drafts import create_draft, init_drafts, read_draft
from edition.releases import publish_edition, read_edition
from edition.snapshots import init_edition_snapshots
from front.orders import parse_front_order
from front.printing import FrontPrintConflict, print_front
from front.receipts import init_front_receipts
from front.sheets import init_front_sheets, read_front_sheet
from mixed.desk import (MixedConflict, MixedFinishConflict, PendingIdentification,
                        correct_mixed_candidates, finish_mixed_book, init_mixed_ledgers,
                        issue_mixed_permit, mixed_tray_exists, open_mixed_tray,
                        read_mixed_book_receipt, read_mixed_tray, settle_mixed_permit)
from tray.loading import TrayLoadConflict, init_trays, load_slot
from tray.lookup import read_dispatched_order, read_dispatched_tray
from tray.orders import TrayDispatchConflict, dispatch_tray, init_tray_orders
from tray.orientation import parse_feed_direction


class PeerUnavailable(Exception):
    pass


def open_database(path):
    db = sqlite3.connect(path, timeout=5.0)
    db.execute('PRAGMA foreign_keys = ON')
    return db


def number(value, field: str) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise ValueError(f'{field} must be a positive integer')
    return value


def path_number(value: str) -> int:
    if not value.isascii() or not value.isdecimal():
        raise ValueError('numbered route requires a positive integer')
    return number(int(value), 'route number')


def get_peer_json(base: str, path: str) -> dict:
    if not base:
        raise PeerUnavailable('peer URL is unavailable')
    try:
        with urlopen(base.rstrip('/') + path, timeout=2.0) as response:
            data = json.load(response)
    except HTTPError as error:
        error.close()
        if error.code == 404:
            raise LookupError('peer has no matching record') from error
        raise PeerUnavailable(f'peer returned HTTP {error.code}') from error
    except (URLError, OSError, ValueError, UnicodeError) as error:
        raise PeerUnavailable('peer response is unavailable') from error
    if not isinstance(data, dict):
        raise PeerUnavailable('peer did not return a JSON object')
    return data


def post_peer_json(base: str, path: str, payload: dict) -> dict:
    if not base:
        raise PeerUnavailable('peer URL is unavailable')
    body = json.dumps(payload).encode('utf-8')
    request = Request(base.rstrip('/') + path, data=body,
                      headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=2.0) as response:
            data = json.load(response)
    except HTTPError as error:
        error.close()
        raise PeerUnavailable(f'peer returned HTTP {error.code}') from error
    except (URLError, OSError, ValueError, UnicodeError) as error:
        raise PeerUnavailable('peer response is unavailable') from error
    if not isinstance(data, dict):
        raise PeerUnavailable('peer did not return a JSON object')
    return data


class PrintHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, database, peer):
        self.database = database
        self.peer = peer
        super().__init__(address, handler)

    @property
    def url(self) -> str:
        host, port = self.server_address
        return f'http://{host}:{port}'


class JsonRequestHandler(BaseHTTPRequestHandler):
    conflict_errors = ()

    def log_message(self, format, *args):
        pass

    def _body(self) -> dict:
        length = int(self.headers.get('Content-Length', '0'))
        if length < 0:
            raise ValueError('invalid content length')
        payload = self.rfile.read(length) if length else b'{}'
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError('request body must be a JSON object')
        return data

    def _reply(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=True).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # A client may disconnect after its business transaction has committed.
            return

    def _handle_json(self) -> None:
        try:
            url = urlsplit(self.path)
            parts = [unquote(part, errors='strict') for part in url.path.split('/')[1:]]
            query = parse_qs(url.query, keep_blank_values=True)
            data = self._body() if self.command == 'POST' else {}
            with closing(open_database(self.server.database)) as db:
                result = self.route(db, self.command, parts, query, data)
        except FinishConflict as error:
            self._reply(409, {'error': str(error), 'missing': list(error.check.missing),
                              'conflicts': list(error.check.conflicts)})
        except MixedFinishConflict as error:
            self._reply(409, {'error': str(error),
                              'missing_slots': list(error.missing_slots)})
        except PendingIdentification as error:
            self._reply(202, error.payload)
        except self.conflict_errors as error:
            self._reply(409, {'error': str(error)})
        except LookupError as error:
            self._reply(404, {'error': str(error)})
        except (ValueError, UnicodeError) as error:
            self._reply(400, {'error': str(error)})
        except (EvidenceUnavailable, PeerUnavailable) as error:
            self._reply(503, {'error': str(error)})
        except sqlite3.Error:
            self._reply(500, {'error': 'database operation failed'})
        else:
            self._reply(200, result)

    def do_GET(self):
        self._handle_json()

    def do_POST(self):
        self._handle_json()


class DeskRequestHandler(JsonRequestHandler):
    conflict_errors = (FrontPrintConflict, TrayLoadConflict, TrayDispatchConflict, MixedConflict)

    def _fetch_impressions(self, orders: tuple[int, ...]) -> tuple[BackImpression, ...]:
        query = urlencode({'order': orders}, doseq=True)
        try:
            response = get_peer_json(self.server.peer, '/impressions?' + query)
            return tuple(BackImpression.from_dict(item) for item in response['impressions'])
        except (LookupError, PeerUnavailable, TypeError, ValueError) as error:
            raise EvidenceUnavailable('could not obtain station impression evidence') from error

    def _register_mixed_permit(self, permit: dict) -> None:
        try:
            post_peer_json(self.server.peer, '/mixed-press/permit', permit)
        except PeerUnavailable as error:
            raise EvidenceUnavailable('could not register the mixed permit at the station') from error

    def _fetch_mixed_outcome(self, permit: str) -> dict:
        try:
            return get_peer_json(self.server.peer, f'/mixed-press/outcome/{quote(permit, safe="")}')
        except LookupError:
            raise
        except PeerUnavailable as error:
            raise EvidenceUnavailable('could not obtain the station outcome') from error

    def route(self, db, method, parts, query, data) -> dict:
        match method, parts:
            case 'POST', ['drafts']:
                return create_draft(db, data).as_dict()
            case 'GET', ['drafts', draft]:
                return read_draft(db, path_number(draft)).as_dict()
            case 'POST', ['editions']:
                return publish_edition(db, number(data.get('draft'), 'draft')).as_dict()
            case 'GET', ['editions', edition]:
                return read_edition(db, path_number(edition)).as_dict()
            case 'POST', ['front']:
                return print_front(db, parse_front_order(data)).as_dict()
            case 'GET', ['front', sheet]:
                return read_front_sheet(db, path_number(sheet)).as_dict()
            case 'POST', ['trays', tray, 'load'] if tray:
                return load_slot(db, tray, number(data.get('slot'), 'slot'),
                                 number(data.get('sheet'), 'sheet'),
                                 parse_feed_direction(data.get('direction'))).as_dict()
            case 'POST', ['trays', tray, 'dispatch'] if tray:
                return dispatch_tray(db, tray).as_dict()
            case 'GET', ['trays', tray, 'order'] if tray:
                return read_dispatched_tray(db, tray).as_dict()
            case 'GET', ['orders', order]:
                return read_dispatched_order(db, path_number(order)).as_dict()
            case 'POST', ['books', 'finish']:
                edition = number(data.get('edition'), 'edition')
                trays = data.get('trays')
                if not isinstance(trays, list) or not trays or any(not isinstance(tray, str) or not tray for tray in trays):
                    raise ValueError('trays must be a nonempty array of tray names')
                names = tuple(dict.fromkeys(trays))
                mixed_names = tuple(name for name in names if mixed_tray_exists(db, name))
                if mixed_names:
                    if len(names) != 1 or len(mixed_names) != 1:
                        raise MixedConflict('a mixed-tray checkout must name only that mixed tray')
                    return finish_mixed_book(db, edition, mixed_names[0])
                return finish_book(db, edition, names, self._fetch_impressions).as_dict()
            case 'GET', ['books', book]:
                book_id = path_number(book)
                mixed_receipt = read_mixed_book_receipt(db, book_id)
                if mixed_receipt is not None:
                    return mixed_receipt
                return read_book_receipt(db, book_id).as_dict()
            case 'POST', ['mixed-trays']:
                tray = data.get('tray')
                if not isinstance(tray, str) or not tray:
                    raise ValueError('tray must be a nonempty name')
                return open_mixed_tray(db, tray, number(data.get('edition'), 'edition'),
                                       data.get('candidates'))
            case 'GET', ['mixed-trays', tray] if tray:
                return read_mixed_tray(db, tray)
            case 'POST', ['mixed-trays', tray, 'correct'] if tray:
                return correct_mixed_candidates(db, tray, data.get('base'),
                                                data.get('slot'), data.get('candidates'))
            case 'POST', ['mixed-trays', tray, 'permit'] if tray:
                request = data.get('request')
                if not isinstance(request, str) or not request:
                    raise ValueError('request must be a nonempty string')
                return issue_mixed_permit(db, tray, data.get('slot'), request,
                                          self._register_mixed_permit)
            case 'POST', ['mixed-trays', tray, 'settle'] if tray:
                outcome = data.get('outcome')
                if not isinstance(outcome, dict) or not isinstance(outcome.get('permit'), str) \
                        or not outcome['permit']:
                    raise ValueError('outcome must be the original station outcome object')
                return settle_mixed_permit(db, outcome['permit'], outcome,
                                           self._fetch_mixed_outcome)
            case _:
                raise LookupError('unknown desk route')


def initialize_desk(database) -> None:
    with closing(open_database(database)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        init_drafts(db)
        init_edition_snapshots(db)
        init_front_sheets(db)
        init_front_receipts(db)
        init_trays(db)
        init_tray_orders(db)
        init_book_receipts(db)
        init_mixed_ledgers(db)


def serve_desk(database, station: str, host='127.0.0.1', port=8766) -> PrintHTTPServer:
    initialize_desk(database)
    return PrintHTTPServer((host, port), DeskRequestHandler, database, station)


def main() -> None:
    parser = argparse.ArgumentParser(description='Large-print booklet desk')
    parser.add_argument('--db', required=True)
    parser.add_argument('--station', default='http://127.0.0.1:8767')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    with serve_desk(args.db, args.station, args.host, args.port) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
