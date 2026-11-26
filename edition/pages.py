from dataclasses import dataclass


Page = str | None
BLANK_PAGE = None


@dataclass(frozen=True)
class FoldPages:
    fold: str
    front: tuple[Page, Page]
    back: tuple[Page, Page]


def find_fold_pages(folds, fold: str) -> FoldPages:
    for pages in folds:
        if pages.fold == fold:
            return pages
    raise LookupError(f'unknown fold {fold}')


def encode_fold_pages(pages: FoldPages) -> dict:
    return {'fold': pages.fold, 'front': list(pages.front), 'back': list(pages.back)}


def decode_fold_pages(data: dict) -> FoldPages:
    return FoldPages(data['fold'], tuple(data['front']), tuple(data['back']))
