"""Exemples de transformations courantes sur les collections."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import TypeVar

T = TypeVar("T")
K = TypeVar("K")


def chunks(items: Sequence[T], size: int) -> Iterator[list[T]]:
    """Produit des lots de taille maximale size."""
    if size <= 0:
        raise ValueError("size doit être supérieur à zéro.")
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def unique(items: Iterable[T]) -> list[T]:
    """Supprime les doublons en conservant le premier ordre d'apparition."""
    return list(dict.fromkeys(items))


def group_by(items: Iterable[T], key: Callable[[T], K]) -> dict[K, list[T]]:
    """Regroupe les éléments selon la valeur calculée par key."""
    groups: dict[K, list[T]] = {}
    for item in items:
        groups.setdefault(key(item), []).append(item)
    return groups


def paginate(items: Sequence[T], page: int, page_size: int) -> list[T]:
    """Retourne une page numérotée à partir de 1."""
    if page < 1 or page_size < 1:
        raise ValueError("page et page_size doivent être supérieurs à zéro.")
    start = (page - 1) * page_size
    return list(items[start : start + page_size])


def flatten(items: Iterable[Iterable[T]]) -> list[T]:
    """Aplati un niveau d'itérables."""
    return [item for group in items for item in group]


def find_first(items: Iterable[T], predicate: Callable[[T], bool], default=None):
    """Retourne le premier élément qui satisfait predicate, ou default."""
    return next((item for item in items if predicate(item)), default)