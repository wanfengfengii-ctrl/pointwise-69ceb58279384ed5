from edition.pages import BLANK_PAGE, FoldPages, Page


def _fold_name(index: int) -> str:
    letters = []
    position = index + 1
    while position:
        position, digit = divmod(position - 1, 26)
        letters.append(chr(ord('A') + digit))
    return ''.join(reversed(letters))


def impose_pages(pages: tuple[str, ...]) -> tuple[FoldPages, ...]:
    padded: tuple[Page, ...] = pages + (BLANK_PAGE,) * (-len(pages) % 4)
    size = len(padded)
    folds = []
    for index in range(size // 4):
        offset = 2 * index
        front = (padded[size - 1 - offset], padded[offset])
        back = (padded[1 + offset], padded[size - 2 - offset])
        folds.append(FoldPages(_fold_name(index), front, back))
    return tuple(folds)
