from edition.snapshots import PaperSpec


class FrontMediaMismatch(Exception):
    pass


def check_front_media(expected: PaperSpec, actual: PaperSpec) -> PaperSpec:
    if expected != actual:
        raise FrontMediaMismatch('front paper does not match the edition')
    return actual
