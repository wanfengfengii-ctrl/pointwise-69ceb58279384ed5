"""Station-side ledger for mixed-tray permits and their first outcomes."""
import json
import sqlite3


class MixedPressConflict(Exception):
    pass


REQUIRED_FIELDS = ('permit', 'tray', 'edition', 'slot', 'back')


def init_mixed_press(db: sqlite3.Connection) -> None:
    db.execute('''CREATE TABLE IF NOT EXISTS mixed_press_permits (
        permit TEXT PRIMARY KEY, facts TEXT NOT NULL
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS mixed_press_outcomes (
        permit TEXT PRIMARY KEY REFERENCES mixed_press_permits(permit),
        action TEXT NOT NULL CHECK(action IN ('print', 'unused')),
        sequence INTEGER,
        UNIQUE(sequence)
    )''')


def register_mixed_permit(db, permit: dict) -> None:
    for field in REQUIRED_FIELDS:
        if field not in permit:
            raise MixedPressConflict(f'permit is missing field {field}')
    permit_id = permit['permit']
    if not isinstance(permit_id, str) or not permit_id:
        raise MixedPressConflict('permit must be a nonempty string')
    payload = json.dumps(permit, sort_keys=True)
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT INTO mixed_press_permits(permit, facts) VALUES (?, ?) '
                   'ON CONFLICT(permit) DO NOTHING', (permit_id, payload))
        row = db.execute('SELECT facts FROM mixed_press_permits WHERE permit = ?',
                         (permit_id,)).fetchone()
        if row[0] != payload:
            raise MixedPressConflict('permit number already registered with different bindings')


def _stored_permit(db, permit_id: str) -> dict:
    row = db.execute('SELECT facts FROM mixed_press_permits WHERE permit = ?',
                     (permit_id,)).fetchone()
    if row is None:
        raise LookupError(f'unknown permit {permit_id}')
    return json.loads(row[0])


def record_mixed_outcome(db, permit: dict, action: str) -> dict:
    if not isinstance(permit, dict):
        raise MixedPressConflict('permit must be the original permit object')
    permit_id = permit.get('permit')
    if not isinstance(permit_id, str) or not permit_id:
        raise MixedPressConflict('permit must carry a nonempty permit number')
    if action not in ('print', 'unused'):
        raise MixedPressConflict('action must be print or unused')
    with db:
        db.execute('BEGIN IMMEDIATE')
        stored = _stored_permit(db, permit_id)
        for field in REQUIRED_FIELDS:
            if permit.get(field) != stored[field]:
                raise MixedPressConflict(f'permit binding mismatch on {field}')
        existing = db.execute('SELECT action, sequence FROM mixed_press_outcomes WHERE permit = ?',
                              (permit_id,)).fetchone()
        if existing is not None:
            prior_action, sequence = existing
            if prior_action != action:
                raise MixedPressConflict(f'permit already ended as {prior_action}')
            return _outcome_dict(stored, prior_action, sequence)
        sequence = None
        if action == 'print':
            # Sequence numbers count actual prints only; unused endings are null.
            row = db.execute('SELECT MAX(sequence) FROM mixed_press_outcomes')
            sequence = (row.fetchone()[0] or 0) + 1
        db.execute('INSERT INTO mixed_press_outcomes(permit, action, sequence) VALUES (?, ?, ?)',
                   (permit_id, action, sequence))
        return _outcome_dict(stored, action, sequence)


def _outcome_dict(permit: dict, action: str, sequence) -> dict:
    return {key: permit[key] for key in REQUIRED_FIELDS} | {'action': action, 'sequence': sequence}


def read_mixed_outcome(db, permit_id: str) -> dict:
    with db:
        db.execute('BEGIN')
        stored = _stored_permit(db, permit_id)
        row = db.execute('SELECT action, sequence FROM mixed_press_outcomes WHERE permit = ?',
                         (permit_id,)).fetchone()
    if row is None:
        raise LookupError(f'permit {permit_id} has no outcome yet')
    return _outcome_dict(stored, row[0], row[1])
