import http.client
import json
import sqlite3
import unittest
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import quote

from back.station_http import serve_station
from tray.desk_http import serve_desk


PAPER = {'width': 210, 'height': 297}
DAY_PAGES = ('1', '2', '3', '4', '5')


@dataclass(frozen=True)
class PendingRequest:
    line: 'PressLine'
    role: str
    method: str
    path: str
    payload: bytes | None

    def release(self, discard_reply=False):
        return self.line.exchange(self.role, self.method, self.path, self.payload, discard_reply)


class PressLine:
    def __enter__(self):
        self.temp = TemporaryDirectory(prefix='booklet-press-')
        root = Path(self.temp.name)
        self.databases = {'desk': root / 'desk.sqlite3', 'station': root / 'station.sqlite3'}
        self.running = {}
        self.addresses = {}
        try:
            self._start('desk', '', 0)
            self._start('station', self.url('desk'), 0)
            self.running['desk'][0].peer = self.url('station')
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            for role in tuple(self.running):
                self.stop(role)
        finally:
            self.temp.cleanup()

    def _start(self, role, peer, port):
        serve = {'desk': serve_desk, 'station': serve_station}[role]
        server = serve(self.databases[role], peer, port=port)
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        try:
            thread.start()
        except BaseException:
            server.server_close()
            raise
        self.running[role] = (server, thread)
        self.addresses[role] = server.server_address

    def url(self, role):
        host, port = self.addresses[role]
        return f'http://{host}:{port}'

    def stop(self, role):
        pair = self.running.pop(role, None)
        if pair is None:
            return
        server, thread = pair
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
        if thread.is_alive():
            raise RuntimeError(f'{role} HTTP server did not stop')

    def restart(self, role):
        peer = 'station' if role == 'desk' else 'desk'
        self.stop(role)
        self._start(role, self.url(peer), self.addresses[role][1])

    def defer(self, role, method, path, data=None) -> PendingRequest:
        payload = None if data is None else json.dumps(data).encode('utf-8')
        return PendingRequest(self, role, method, path, payload)

    def exchange(self, role, method, path, payload, discard_reply):
        host, port = self.addresses[role]
        with closing(http.client.HTTPConnection(host, port, timeout=5)) as conn:
            headers = {'Content-Type': 'application/json'} if payload is not None else {}
            conn.request(method, path, body=payload, headers=headers)
            with conn.getresponse() as response:
                if discard_reply:
                    # Response headers follow the server's commit. Drop the reply at the caller.
                    return None
                return response.status, json.load(response)

    def call(self, role, method, path, data=None):
        return self.defer(role, method, path, data).release()

    def count(self, role, table):
        tables = {
            'desk': {'drafts', 'editions', 'front_sheets', 'front_receipts', 'loaded_slots',
                     'tray_orders', 'book_receipts', 'mixed_trays', 'mixed_candidates',
                     'mixed_permits', 'mixed_permit_requests'},
            'station': {'back_orders', 'back_impressions', 'back_receipts',
                        'mixed_press_permits', 'mixed_press_outcomes'},
        }
        if table not in tables[role]:
            raise ValueError('unknown test ledger')
        uri = self.databases[role].as_uri() + '?mode=ro'
        with closing(sqlite3.connect(uri, uri=True)) as db:
            return db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]


class LineCase(unittest.TestCase):
    def setUp(self):
        self.line = self.enterContext(PressLine())

    def post(self, role, path, data, status=200):
        actual, body = self.line.call(role, 'POST', path, data)
        self.assertEqual(actual, status, body)
        return body

    def get(self, role, path, status=200):
        actual, body = self.line.call(role, 'GET', path)
        self.assertEqual(actual, status, body)
        return body

    def publish(self, pages=DAY_PAGES, paper=PAPER):
        draft = self.post('desk', '/drafts', {'pages': list(pages), 'paper': paper})
        return self.post('desk', '/editions', {'draft': draft['draft']})

    def front(self, edition, fold, request, paper=PAPER, status=200):
        return self.post('desk', '/front', {'edition': edition, 'fold': fold,
                                          'request': request, 'paper': paper}, status)

    def load(self, tray, slot, sheet, direction='head', status=200):
        return self.post('desk', f'/trays/{quote(tray, safe="")}/load',
                         {'slot': slot, 'sheet': sheet, 'direction': direction}, status)

    def dispatch(self, tray, status=200):
        return self.post('desk', f'/trays/{quote(tray, safe="")}/dispatch', {}, status)

    def back(self, order, slot, request, direction='head', paper=PAPER, status=200):
        return self.post('station', '/back', back_payload(order, slot, request, direction, paper), status)

    def finish(self, edition, trays, status=200):
        return self.post('desk', '/books/finish', {'edition': edition, 'trays': trays}, status)

    def impressions(self, order):
        return self.get('station', f'/orders/{order}/impressions')['impressions']

    def loaded_order(self, folds=('A',), tray='ordinary', edition=None):
        if edition is None:
            edition = self.publish()['edition']
        sheets = {}
        for slot, fold in enumerate(folds, 1):
            sheet = self.front(edition, fold, f'{tray}-front-{slot}')
            sheets[fold] = sheet
            self.load(tray, slot, sheet['sheet'])
        return edition, self.dispatch(tray), sheets


def back_payload(order, slot, request, direction='head', paper=PAPER):
    return {'order': order, 'slot': slot, 'request': request, 'direction': direction, 'paper': paper}
