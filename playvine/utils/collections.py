import itertools
from typing import Iterable, Iterator, Optional, Sequence, TypeVar

T = TypeVar("T")


def as_lists(*args):
    """Convert any input objects to list objects."""
    for item in args:
        yield item if isinstance(item, list) else [item]


def as_list(*args):
    """
    Convert any input objects to a single merged list object.

    Example:
    >>> as_list('foo', ['buzz', 'bizz'], 'bazz', 'bozz', ['bar'], ['bur'])
    ['foo', 'buzz', 'bizz', 'bazz', 'bozz', 'bar', 'bur']
    """
    if args == (None,):
        return []
    return list(itertools.chain.from_iterable(as_lists(*args)))


def flatten(items, ignore_types=str):
    """
    Flatten items recursively.

    Example:
    >>> list(flatten(["foo", [["bar", ["buzz", [""]], "bee"]]]))
    ['foo', 'bar', 'buzz', '', 'bee']
    >>> list(flatten("foo"))
    ['foo']
    >>> list(flatten({1}, set))
    [{1}]
    """
    if isinstance(items, (Iterable, Sequence)) and not isinstance(items, ignore_types):
        for i in items:
            yield from flatten(i, ignore_types)
    else:
        yield items


def merge_dict(*dicts):
    """Recursively merge dicts into dest in-place."""
    dest = dicts[0]
    for d in dicts[1:]:
        for key, value in d.items():
            if isinstance(value, dict):
                node = dest.setdefault(key, {})
                merge_dict(node, value)
            else:
                dest[key] = value


def first_or_none(iterable: Iterable[T]) -> Optional[T]:
    """Return the first element of an iterable, or None if it is empty."""
    return next(iter(iterable), None)


def first(iterable: Iterable[T]) -> T:
    """Return the first element of an iterable; raise ValueError if empty."""
    _sentinel = object()
    result = next(iter(iterable), _sentinel)
    if result is _sentinel:
        raise ValueError("Iterable is empty")
    return result  # type: ignore[return-value]


def first_or_else(iterable: Iterable[T], default: T) -> T:
    """Return the first element of an iterable, or *default* if it is empty."""
    return next(iter(iterable), default)


class CaseInsensitiveDict(dict):
    """
    A dict subclass whose keys are stored lower-case so look-ups are
    case-insensitive, while the original insertion case is preserved
    for iteration and display purposes.
    """

    def __init__(self, data=None, **kwargs):
        super().__init__()
        self._original_keys: dict = {}
        for k, v in (data or {}).items():
            self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    def _lower(self, key):
        return key.lower() if isinstance(key, str) else key

    def __setitem__(self, key, value):
        lower = self._lower(key)
        self._original_keys[lower] = key
        super().__setitem__(lower, value)

    def __getitem__(self, key):
        return super().__getitem__(self._lower(key))

    def __delitem__(self, key):
        lower = self._lower(key)
        self._original_keys.pop(lower, None)
        super().__delitem__(lower)

    def __contains__(self, key):
        return super().__contains__(self._lower(key))

    def get(self, key, default=None):
        return super().get(self._lower(key), default)

    def pop(self, key, *args):
        lower = self._lower(key)
        self._original_keys.pop(lower, None)
        return super().pop(lower, *args)

    def keys(self) -> Iterator:
        return (self._original_keys.get(k, k) for k in super().keys())

    def items(self) -> Iterator:
        return ((self._original_keys.get(k, k), v) for k, v in super().items())

    def copy(self) -> "CaseInsensitiveDict":
        return CaseInsensitiveDict(dict(self.items()))
