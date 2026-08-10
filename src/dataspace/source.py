"""The ``Source`` protocol: what a registrable data endpoint must provide.

A Source is *not* a database handle, a connection pool, or a resolver. It is
the thin, typed description an owning repository publishes about one of its
data endpoints, plus a way to ask "are you actually reachable right now?".

Every adapter lives in the repository that owns the data — market-data-hub
implements its own Source over its own canonical resolver, LazyCrawler over
its own, and so on. DataSpace itself imports none of them; it only ever sees
this protocol. That is the whole reason the protocol is this small: anything
bigger would push domain knowledge into the composition layer.

Implementations are ordinary classes. There is no registration decorator, no
metaclass and no base class to inherit — :class:`Source` is a
``typing.Protocol`` checked structurally, so an adapter satisfies it by
having the right attributes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Health:
    """The outcome of one real readiness check against a Source.

    Attributes:
        ready: ``True`` only when the endpoint was actually reached. A
            configured-but-unreachable source is ``False``, not ``True``:
            "the env var is set" is not readiness, and conflating the two
            is what this type exists to prevent.
        detail: Human-readable explanation. Required when ``ready`` is
            ``False`` so a failing aggregate health report names the cause
            instead of just counting failures.
    """

    ready: bool
    detail: str = ""

    def __post_init__(self) -> None:
        if not self.ready and not self.detail:
            raise ValueError("Health(ready=False) requires a detail explaining why")


@dataclass(frozen=True)
class SourceInfo:
    """A Source's self-description, intended for logs and operators.

    The *shape* provides no field for a path, DSN or credential: an adapter
    that needs one keeps it privately, and there is nowhere here to put it
    even by accident.

    That is a structural guarantee about the fields, **not** about their
    contents. ``description`` is free text, so keeping secrets out of it is
    the adapter's obligation — this type cannot enforce it. Write
    descriptions as if they will be logged and shown to an agent, because
    they will be.

    Attributes:
        name: Stable logical identifier, unique within a DataSpace.
        owner: The repository that owns and writes this data.
        capabilities: What this endpoint can do, as stable dotted strings
            (e.g. ``"market.returns"``, ``"documents.search"``). Used for
            capability-based lookup; DataSpace never interprets their
            meaning.
        description: Short human-readable note on what the endpoint holds.
            Must not carry paths, DSNs or credentials.
    """

    name: str
    owner: str
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""


@runtime_checkable
class Source(Protocol):
    """A registrable data endpoint owned by one repository.

    The protocol is intentionally minimal — five members, no I/O contract
    beyond :meth:`health`. Reading, publishing and searching are *not* here:
    they are per-domain APIs that live on the concrete adapter and are
    reached through :meth:`DataSpace.source`, so DataSpace never becomes a
    pass-through for domain calls it cannot type.
    """

    @property
    def name(self) -> str:
        """Stable logical identifier, unique within a DataSpace."""
        ...

    @property
    def owner(self) -> str:
        """The repository that owns and writes this data."""
        ...

    @property
    def capabilities(self) -> tuple[str, ...]:
        """Stable dotted capability strings this endpoint provides."""
        ...

    def describe(self) -> SourceInfo:
        """Return this Source's self-description.

        The implementation is responsible for keeping the free-text
        ``description`` free of paths, DSNs and credentials — see
        :class:`SourceInfo`.
        """
        ...

    def health(self) -> Health:
        """Check that this endpoint is actually reachable right now.

        Implementations must perform a real check (open the file, run a
        trivial query, ping the API) rather than testing whether an
        environment variable happens to be set. Failures are reported as
        ``Health(ready=False, detail=...)``, not raised: an aggregate
        health report needs every source's outcome, not the first
        exception.
        """
        ...


__all__ = ["Health", "Source", "SourceInfo"]
