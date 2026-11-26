from dataclasses import dataclass

from edition.pages import FoldPages, find_fold_pages
from edition.releases import read_edition
from edition.snapshots import PaperSpec, parse_paper_spec


@dataclass(frozen=True)
class FrontOrder:
    edition: int
    fold: str
    paper: PaperSpec
    request: str

    def parameters(self) -> dict:
        return {'edition': self.edition, 'fold': self.fold, 'paper': self.paper.as_dict()}


def parse_front_order(data: dict) -> FrontOrder:
    edition, fold, request = data.get('edition'), data.get('fold'), data.get('request')
    if type(edition) is not int or not 0 < edition < 2**63:
        raise ValueError('edition must be a positive edition number')
    if not isinstance(fold, str) or not fold:
        raise ValueError('fold must be a nonempty string')
    if not isinstance(request, str) or not request:
        raise ValueError('request must be a nonempty string')
    return FrontOrder(edition, fold, parse_paper_spec(data.get('paper')), request)


def resolve_front_pages(db, order: FrontOrder) -> tuple[PaperSpec, FoldPages]:
    snapshot = read_edition(db, order.edition)
    return snapshot.paper, find_fold_pages(snapshot.folds, order.fold)
