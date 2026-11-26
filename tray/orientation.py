from typing import Literal


FeedDirection = Literal['head', 'foot']


def parse_feed_direction(value) -> FeedDirection:
    if value == 'head':
        return 'head'
    if value == 'foot':
        return 'foot'
    raise ValueError('direction must be head or foot')


def matches_feed_direction(expected: FeedDirection, actual: FeedDirection) -> bool:
    return expected == actual
