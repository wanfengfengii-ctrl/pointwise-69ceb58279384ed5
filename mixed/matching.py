"""Interpretation engine for mixed trays.

An interpretation is a one-to-one assignment of every fold of the fixed edition
to exactly one slot, restricted to the folds each slot may still hold.
"""
from edition.pages import Page


def enumerate_matchings(slots: tuple[int, ...], candidates: dict[int, tuple[str, ...]],
                        folds: tuple[str, ...]) -> tuple[dict[int, str], ...]:
    """Return every feasible slot -> fold assignment.

    ``slots`` is ordered by slot number, ``folds`` is the edition's fixed fold
    order. Each fold must occupy exactly one slot and each slot one fold.
    """
    candidate_sets = {slot: set(candidates[slot]) for slot in slots}
    results: list[dict[int, str]] = []

    def visit(index: int, assignment: dict[int, str], used: set[str]) -> None:
        if index == len(slots):
            results.append(dict(assignment))
            return
        slot = slots[index]
        for fold in folds:
            if fold in used or fold not in candidate_sets[slot]:
                continue
            assignment[slot] = fold
            used.add(fold)
            visit(index + 1, assignment, used)
            used.remove(fold)
            del assignment[slot]

    visit(0, {}, set())
    return tuple(results)


def backs_for_slot(matchings: tuple[dict[int, str], ...], slot: int,
                   back_by_fold: dict[str, tuple[Page, Page]]) -> tuple[tuple[Page, Page], ...]:
    """Distinct backs a slot may receive across all interpretations, in fold order."""
    seen: dict[tuple[Page, Page], None] = {}
    for matching in matchings:
        back = back_by_fold[matching[slot]]
        seen.setdefault(back, None)
    return tuple(seen)


def parse_candidate_map(raw, folds: tuple[str, ...]) -> dict[int, tuple[str, ...]]:
    """Validate the ``candidates`` object used when opening a mixed tray."""
    if not isinstance(raw, dict) or not raw:
        raise ValueError('candidates must be a nonempty object keyed by slot number')
    fold_set = set(folds)
    parsed: dict[int, tuple[str, ...]] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.isascii() or not key.isdecimal() or int(key) <= 0:
            raise ValueError('candidate keys must be positive integer slot numbers')
        slot = int(key)
        if not isinstance(value, list) or not value:
            raise ValueError(f'slot {slot} candidates must be a nonempty array')
        if any(not isinstance(fold, str) or not fold for fold in value):
            raise ValueError(f'slot {slot} candidates must be nonempty fold names')
        if len(set(value)) != len(value):
            raise ValueError(f'slot {slot} candidates contain duplicates')
        unknown = [fold for fold in value if fold not in fold_set]
        if unknown:
            raise ValueError(f'slot {slot} references unknown fold {unknown[0]}')
        parsed[slot] = tuple(value)
    if set(parsed) != set(range(1, len(folds) + 1)):
        raise ValueError('candidate keys must be exactly the slot numbers 1..N')
    return {slot: parsed[slot] for slot in sorted(parsed)}
