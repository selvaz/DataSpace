"""DataSpace's error types.

Three distinct failures, three distinct types — a caller that wants to
handle "this deployment isn't ready yet" differently from "the composition
root has a bug" can do so without matching on message text.

All inherit :class:`DataSpaceError`, so ``except DataSpaceError`` catches
everything this package raises and nothing it doesn't.
"""

from __future__ import annotations


class DataSpaceError(Exception):
    """Base class for every error raised by DataSpace."""


class DuplicateSourceError(DataSpaceError):
    """Two Sources were registered under the same logical name.

    A composition-root bug: the winner would otherwise depend on
    registration order, and the two adapters usually point at different
    databases.
    """


class UnknownSourceError(DataSpaceError):
    """A Source was requested by a name that is not registered.

    Usually a typo, or a source the composition root forgot to add.
    """


class SourceNotReadyError(DataSpaceError):
    """A readiness gate failed: one or more Sources are not reachable.

    Raised by :meth:`~dataspace.space.DataSpace.require_ready`, typically
    at the start of a scheduled run, before anything is written.
    """


__all__ = [
    "DataSpaceError",
    "DuplicateSourceError",
    "SourceNotReadyError",
    "UnknownSourceError",
]
