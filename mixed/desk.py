"""Desk-side ledger and rules for mixed-tray back printing."""
import json
import sqlite3
from dataclasses import dataclass

from edition.pages import Page
from edition.releases import read_edition
from mixed.matching import enumerate_matchings, parse_candidate_map


class MixedConflict(Exception):
    pass


class PendingIdentification(Exception):
    """The target slot still admits more than one back text (HTTP 202)."""

    def __init__(self, payload: dict):
        super().__init__('slot back text is not yet identifiable')
        self.payload = payload


@dataclass(frozen=True)
class MixedPermit:
    permit: str
    tray: str
    edition: int
    slot: int
    back: tuple[Page, Page]

    def as_dict(self) -> dict:
        return {'permit': self.permit, 'tray': self.tray, 'edition': self.edition,
                'slot': self.slot, 'back': list(self.back)}


def init_mixed_ledgers(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS mixed_trays (
        name TEXT PRIMARY KEY, edition INTEGER NOT NULL REFERENCES editions(id),
        revision INTEGER NOT NULL CHECK(revision > 0)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS mixed_candidates (
        tray TEXT NOT NULL REFERENCES mixed_trays(name), slot INTEGER NOT NULL,
        fold TEXT NOT NULL, PRIMARY KEY(tray, slot, fold)
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS mixed_permits (
        permit TEXT PRIMARY KEY, tray TEXT NOT NULL, slot INTEGER NOT NULL,
        edition INTEGER NOT NULL, back TEXT NOT NULL,
        state TEXT NOT NULL DEFAULT 'active'
            CHECK(state IN ('active', 'printed', 'unused')),
        settled_action TEXT, settled_sequence INTEGER
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS mixed_permit_requests (
        request TEXT PRIMARY KEY, tray TEXT NOT NULL, slot INTEGER NOT NULL,
        permit TEXT NOT NULL REFERENCES mixed_permits(permit)
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_mixed_permits_slot ON mixed_permits(tray, slot)')
    columns = {row[1] for row in db.execute('PRAGMA table_info(book_receipts)')}
    if columns and 'kind' not in columns:
        db.execute("ALTER TABLE book_receipts ADD COLUMN kind TEXT NOT NULL DEFAULT 'ordinary'")


def mixed_tray_exists(db, name: str) -> bool:
    return db.execute('SELECT 1 FROM mixed_trays WHERE name = ?', (name,)).fetchone() is not None


def ordinary_tray_exists(db, name: str) -> bool:
    return db.execute('SELECT 1 FROM trays WHERE name = ?', (name,)).fetchone() is not None


def _read_mixed_tray(db, tray: str):
    row = db.execute('SELECT edition, revision FROM mixed_trays WHERE name = ?', (tray,)).fetchone()
    if row is None:
        raise LookupError(f'unknown mixed tray {tray}')
    return row


def _read_candidates(db, tray: str) -> dict[int, list[str]]:
    rows = db.execute('SELECT slot, fold FROM mixed_candidates WHERE tray = ? ORDER BY slot, fold',
                      (tray,))
    result: dict[int, list[str]] = {}
    for slot, fold in rows:
        result.setdefault(slot, []).append(fold)
    return result


def _slot_count(edition) -> int:
    return len(edition.folds)


def _back_by_fold(edition) -> dict[str, tuple[Page, Page]]:
    return {fold.fold: fold.back for fold in edition.folds}


def _interpret(candidates: dict[int, tuple[str, ...]], edition):
    slots = tuple(sorted(candidates))
    folds = tuple(fold.fold for fold in edition.folds)
    matchings = enumerate_matchings(slots, candidates, folds)
    return slots, matchings, _back_by_fold(edition)


def open_mixed_tray(db, tray: str, edition_id: int, raw_candidates) -> dict:
    if not isinstance(tray, str) or not tray:
        raise ValueError('tray must be a nonempty name')
    snapshot = read_edition(db, edition_id)
    candidate_map = parse_candidate_map(raw_candidates, tuple(fold.fold for fold in snapshot.folds))
    if ordinary_tray_exists(db, tray) or mixed_tray_exists(db, tray):
        raise MixedConflict(f'tray name {tray} is already in use')
    _, matchings, _ = _interpret(candidate_map, snapshot)
    if not matchings:
        raise MixedConflict('mixed tray has no feasible one-to-one interpretation')
    with db:
        db.execute('BEGIN IMMEDIATE')
        if ordinary_tray_exists(db, tray) or mixed_tray_exists(db, tray):
            raise MixedConflict(f'tray name {tray} is already in use')
        db.execute('INSERT INTO mixed_trays(name, edition, revision) VALUES (?, ?, 1)',
                   (tray, snapshot.edition))
        db.executemany('INSERT INTO mixed_candidates(tray, slot, fold) VALUES (?, ?, ?)',
                       [(tray, slot, fold) for slot, folds in candidate_map.items() for fold in folds])
    return read_mixed_tray(db, tray)


def correct_mixed_candidates(db, tray: str, base, slot, raw_candidates) -> dict:
    if type(base) is not int or base <= 0:
        raise ValueError('base must be a positive revision number')
    if type(slot) is not int or slot <= 0:
        raise ValueError('slot must be a positive integer')
    if not isinstance(raw_candidates, list) or not raw_candidates:
        raise ValueError('candidates must be a nonempty array of fold names')
    if any(not isinstance(fold, str) or not fold for fold in raw_candidates):
        raise ValueError('candidates must be nonempty fold names')
    if len(set(raw_candidates)) != len(raw_candidates):
        raise ValueError('candidates contain duplicates')
    with db:
        db.execute('BEGIN IMMEDIATE')
        edition_id, revision = _read_mixed_tray(db, tray)
        snapshot = read_edition(db, edition_id)
        if slot not in range(1, _slot_count(snapshot) + 1):
            raise ValueError(f'tray {tray} has no slot {slot}')
        fold_set = {fold.fold for fold in snapshot.folds}
        if any(fold not in fold_set for fold in raw_candidates):
            raise ValueError('candidates reference an unknown fold')
        if revision != base:
            raise MixedConflict(f'revision {base} is not current; expected {revision}')
        current = {key: tuple(value) for key, value in _read_candidates(db, tray).items()}
        updated = dict(current)
        updated[slot] = tuple(raw_candidates)
        slots, matchings, back_by_fold = _interpret(updated, snapshot)
        if not matchings:
            raise MixedConflict('correction leaves the tray without a feasible interpretation')
        constraints = _binding_constraints(db, tray, slots)
        for constrained_slot, required_back in constraints.items():
            # A committed back must remain the slot's back under EVERY feasible
            # interpretation; a single violating interpretation forbids the correction.
            if any(back_by_fold[matching[constrained_slot]] != required_back
                   for matching in matchings):
                raise MixedConflict(
                    f'correction would break the committed back at slot {constrained_slot}')
        db.execute('DELETE FROM mixed_candidates WHERE tray = ? AND slot = ?', (tray, slot))
        db.executemany('INSERT INTO mixed_candidates(tray, slot, fold) VALUES (?, ?, ?)',
                       [(tray, slot, fold) for fold in raw_candidates])
        db.execute('UPDATE mixed_trays SET revision = ? WHERE name = ?', (revision + 1, tray))
    return read_mixed_tray(db, tray)


def _binding_constraints(db, tray: str, slots: tuple[int, ...]) -> dict[int, tuple[Page, Page]]:
    """Backs that remain committed: the latest permit per slot while active or printed.

    Runs inside the caller's open IMMEDIATE transaction, so it reads permits that
    the same transaction has just written as well as previously committed ones.
    """
    constraints: dict[int, tuple[Page, Page]] = {}
    for slot in slots:
        row = db.execute('''SELECT state, back FROM mixed_permits
                            WHERE tray = ? AND slot = ? ORDER BY rowid DESC LIMIT 1''',
                         (tray, slot)).fetchone()
        if row is not None and row[0] in ('active', 'printed'):
            constraints[slot] = tuple(json.loads(row[1]))
    return constraints


def _latest_permit_row(db, tray: str, slot: int):
    return db.execute('''SELECT permit, state, back FROM mixed_permits
                         WHERE tray = ? AND slot = ? ORDER BY rowid DESC LIMIT 1''',
                      (tray, slot)).fetchone()


def issue_mixed_permit(db, tray: str, slot, request: str, register) -> dict:
    if type(slot) is not int or slot <= 0:
        raise ValueError('slot must be a positive integer')
    if not isinstance(request, str) or not request:
        raise ValueError('request must be a nonempty string')
    with db:
        db.execute('BEGIN IMMEDIATE')
        edition_id, _ = _read_mixed_tray(db, tray)
        snapshot = read_edition(db, edition_id)
        if slot not in range(1, _slot_count(snapshot) + 1):
            raise ValueError(f'tray {tray} has no slot {slot}')
        receipt = db.execute('SELECT tray, slot, permit FROM mixed_permit_requests WHERE request = ?',
                             (request,)).fetchone()
        if receipt is not None:
            if (receipt[0], receipt[1]) != (tray, slot):
                raise MixedConflict('request number is already bound to another tray or slot')
            return _read_permit(db, receipt[2]).as_dict()
        latest = _latest_permit_row(db, tray, slot)
        if latest is not None and latest[1] == 'printed':
            raise MixedConflict('slot already printed; no further permit can be issued')
        if latest is not None and latest[1] == 'active':
            raise MixedConflict('slot already has an executable permit')
        candidate_map = {key: tuple(value) for key, value in _read_candidates(db, tray).items()}
        slots, matchings, back_by_fold = _interpret(candidate_map, snapshot)
        if not matchings:
            raise MixedConflict('tray has no feasible interpretation')
        distinct_backs = {}
        for matching in matchings:
            distinct_backs.setdefault(back_by_fold[matching[slot]], None)
        if len(distinct_backs) > 1:
            raise PendingIdentification({
                'status': 'pending', 'tray': tray, 'edition': edition_id, 'slot': slot,
                'error': 'back text differs across feasible interpretations',
            })
        back = next(iter(distinct_backs))
        permit = MixedPermit(request, tray, edition_id, slot, back)
        # Register at the station before committing so offline presses cannot be
        # left holding a permit the station never learned.
        register(permit.as_dict())
        db.execute('''INSERT INTO mixed_permits(permit, tray, slot, edition, back, state)
                      VALUES (?, ?, ?, ?, ?, 'active')''',
                   (permit.permit, tray, slot, edition_id, json.dumps(list(back))))
        db.execute('INSERT INTO mixed_permit_requests(request, tray, slot, permit) VALUES (?, ?, ?, ?)',
                   (request, tray, slot, permit.permit))
        return permit.as_dict()


def _read_permit(db, permit_id: str) -> MixedPermit:
    row = db.execute('SELECT permit, tray, slot, edition, back FROM mixed_permits WHERE permit = ?',
                     (permit_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown permit {permit_id}')
    permit, tray, slot, edition, back = row
    return MixedPermit(permit, tray, edition, slot, tuple(json.loads(back)))


def settle_mixed_permit(db, permit_id: str, outcome, fetch_outcome) -> dict:
    with db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('''SELECT permit, tray, slot, edition, back, state,
                                   settled_action, settled_sequence
                            FROM mixed_permits WHERE permit = ?''', (permit_id,)).fetchone()
        if row is None:
            raise LookupError(f'unknown permit {permit_id}')
        permit, tray, slot, edition, back_text, state, settled_action, settled_sequence = row
        stored_outcome = None
        if state != 'active':
            # An already-verified ending replays by its stored copy and never needs
            # fresh station evidence, so it remains available during station outages.
            stored_outcome = {
                'permit': permit, 'tray': tray, 'edition': edition, 'slot': slot,
                'back': json.loads(back_text), 'action': settled_action,
                'sequence': settled_sequence,
            }
        if stored_outcome is not None:
            if (outcome.get('action'), outcome.get('sequence')) != (settled_action, settled_sequence):
                raise MixedConflict('submitted ending disagrees with the settled outcome')
            return stored_outcome
        try:
            fact = fetch_outcome(permit)
        except LookupError as error:
            raise MixedConflict('station has no outcome for this permit') from error
        _check_outcome_binding(fact, permit, tray, edition, slot, json.loads(back_text))
        action, sequence = fact['action'], fact['sequence']
        if action not in ('print', 'unused'):
            raise MixedConflict('station returned an unknown action')
        if action == 'print':
            if type(sequence) is not int or sequence <= 0:
                raise MixedConflict('printed outcome must carry a positive sequence')
        elif sequence is not None:
            raise MixedConflict('unused outcome must not carry a sequence')
        # The desk only settles the genuine station ending: the object the client
        # hands in must itself carry the same permit binding and ending.
        for key, value in (('tray', tray), ('edition', edition), ('slot', slot),
                           ('back', json.loads(back_text)), ('action', action),
                           ('sequence', sequence)):
            if outcome.get(key) != value:
                raise MixedConflict(f'submitted outcome mismatch on {key}')
        new_state = 'printed' if action == 'print' else 'unused'
        db.execute('''UPDATE mixed_permits SET state = ?, settled_action = ?, settled_sequence = ?
                      WHERE permit = ?''', (new_state, action, sequence, permit))
        return {'permit': permit, 'tray': tray, 'edition': edition, 'slot': slot,
                'back': json.loads(back_text), 'action': action, 'sequence': sequence}


def _check_outcome_binding(fact, permit: str, tray: str, edition: int, slot: int, back) -> None:
    expected = {'permit': permit, 'tray': tray, 'edition': edition, 'slot': slot, 'back': back}
    for key, value in expected.items():
        if fact.get(key) != value:
            raise MixedConflict(f'station outcome binding mismatch on {key}')


def read_mixed_tray(db, tray: str) -> dict:
    edition_id, revision = _read_mixed_tray(db, tray)
    snapshot = read_edition(db, edition_id)
    candidate_rows = _read_candidates(db, tray)
    slots = []
    for slot in range(1, _slot_count(snapshot) + 1):
        latest = _latest_permit_row(db, tray, slot)
        slots.append({
            'slot': slot,
            'candidates': candidate_rows.get(slot, []),
            'permit': None if latest is None else {'permit': latest[0], 'state': latest[1]},
        })
    return {'tray': tray, 'edition': edition_id, 'revision': revision, 'slots': slots}


class MixedFinishConflict(Exception):
    def __init__(self, missing_slots: tuple[int, ...]):
        super().__init__('mixed tray cannot be checked out yet')
        self.missing_slots = missing_slots


def finish_mixed_book(db, edition_id: int, tray: str) -> dict:
    with db:
        db.execute('BEGIN IMMEDIATE')
        tray_edition, _ = _read_mixed_tray(db, tray)
        if tray_edition != edition_id:
            raise MixedConflict(f'mixed tray {tray} belongs to another edition')
        snapshot = read_edition(db, edition_id)
        missing: list[int] = []
        receipt_slots = []
        for slot in range(1, _slot_count(snapshot) + 1):
            row = db.execute('''SELECT permit, back, state, settled_sequence FROM mixed_permits
                                WHERE tray = ? AND slot = ? ORDER BY rowid DESC LIMIT 1''',
                             (tray, slot)).fetchone()
            if row is None or row[2] != 'printed' or row[3] is None:
                missing.append(slot)
                continue
            receipt_slots.append({'slot': slot, 'back': json.loads(row[1]),
                                  'permit': row[0], 'sequence': row[3]})
        if missing:
            raise MixedFinishConflict(tuple(missing))
        cursor = db.execute(
            "INSERT INTO book_receipts(edition, sources, kind) VALUES (?, ?, 'mixed')",
            (edition_id, json.dumps({'book': 0, 'edition': edition_id, 'tray': tray,
                                     'slots': receipt_slots}, sort_keys=True)),
        )
        book_id = cursor.lastrowid
        receipt = {'book': book_id, 'edition': edition_id, 'tray': tray, 'slots': receipt_slots}
        db.execute('UPDATE book_receipts SET sources = ? WHERE id = ?',
                   (json.dumps(receipt, sort_keys=True), book_id))
    return receipt


def read_mixed_book_receipt(db, book: int) -> dict | None:
    row = db.execute('SELECT kind, sources FROM book_receipts WHERE id = ?', (book,)).fetchone()
    if row is None:
        return None
    kind, sources = row
    if kind != 'mixed':
        return None
    return json.loads(sources)
