"""``DataSpace``: an explicit collection of already-configured Sources.

The one capability this layer adds over calling each repository's API
directly: a typed composition root that registers the sources a workflow
needs and verifies their readiness **together**, before the workflow starts
writing anything. Today that responsibility is scattered across environment
variables, per-repo resolvers and ``data_source`` dicts with special keys —
every job reconstructs it, and reconstructing it wrong has already caused
real bugs.

What this is not, deliberately: not a database, not a resolver, not a
scheduler, not an execution engine, not a function registry. It holds
Sources someone else constructed and routes lookups to them. Reading and
publishing happen on the concrete adapter, reached via :meth:`DataSpace.source`.

Errors are fail-fast and explicit — a duplicate name, an unknown name or an
unmet readiness gate raises rather than warning, because each one means the
composition root is wrong and continuing would write to the wrong place or
silently skip a source.
"""

from __future__ import annotations

# ``DataSpace.list()`` is part of the frozen public API, and a method by that
# name shadows the builtin inside the class body — so annotations below say
# ``builtins.list[...]`` explicitly rather than resolving to the method.
import builtins

from lazydataspace.errors import DuplicateSourceError, SourceNotReadyError, UnknownSourceError
from lazydataspace.source import Health, Source, SourceInfo


class DataSpace:
    """An explicit, ordered collection of configured :class:`Source` objects.

    Construction is the composition root: the caller builds each adapter
    (with its own paths and credentials) and hands the finished object over.
    DataSpace never constructs a Source, never resolves a path and never
    reads an environment variable.

    Example:
        >>> space = DataSpace(market_source, crawler_source)
        >>> space.require_ready()          # raises unless every source is reachable
        >>> returns = space.source("market").returns(["SPY", "TLT"])

    Args:
        *sources: Already-configured Sources to register, in order.

    Raises:
        DuplicateSourceError: Two sources share a ``name``.
    """

    def __init__(self, *sources: Source) -> None:
        self._sources: dict[str, Source] = {}
        for source in sources:
            self.add(source)

    def add(self, source: Source) -> None:
        """Register one already-configured Source.

        Args:
            source: The Source to register. Its ``name`` must be unique
                within this DataSpace.

        Raises:
            DuplicateSourceError: A Source with the same name is already
                registered. Silently replacing it would make the winner
                depend on registration order — two adapters pointing at
                different databases under one name is a composition-root
                bug, not something to resolve by last-write-wins.
        """
        name = source.name
        if name in self._sources:
            raise DuplicateSourceError(
                f"Source {name!r} is already registered (owner: {self._sources[name].owner}). "
                f"Each logical name must map to exactly one Source."
            )
        self._sources[name] = source

    def source(self, name: str) -> Source:
        """Return the registered Source with this name.

        The returned object is the concrete adapter, not a wrapper — call
        its own domain API on it (``returns()``, ``search_text()``, ...).

        Args:
            name: The logical name the Source was registered under.

        Returns:
            The registered Source.

        Raises:
            UnknownSourceError: No Source is registered under this name.
                The message lists the registered names, since the usual
                cause is a typo or a source the composition root forgot.
        """
        try:
            return self._sources[name]
        except KeyError:
            raise UnknownSourceError(
                f"Unknown source {name!r}. Registered: {sorted(self._sources) or '(none)'}"
            ) from None

    def __getitem__(self, name: str) -> Source:
        """Alias for :meth:`source` — ``space["market"]``."""
        return self.source(name)

    def __contains__(self, name: object) -> bool:
        """Whether a Source is registered under this name."""
        return name in self._sources

    def __len__(self) -> int:
        """How many Sources are registered."""
        return len(self._sources)

    def list(self) -> builtins.list[str]:
        """Return the registered source names, in registration order."""
        return builtins.list(self._sources)

    def describe(self) -> builtins.list[SourceInfo]:
        """Return every Source's non-sensitive self-description.

        Safe to log or display: :class:`~lazydataspace.source.SourceInfo`
        carries no paths, DSNs or credentials.
        """
        return [source.describe() for source in self._sources.values()]

    def for_capability(self, capability: str) -> builtins.list[Source]:
        """Return the Sources declaring this capability, in registration order.

        Returns an empty list when none match — an absent capability is a
        legitimate answer to "who can do this?", unlike an unknown *name*,
        which is a lookup error.

        Args:
            capability: A dotted capability string, e.g. ``"documents.search"``.
        """
        return [s for s in self._sources.values() if capability in s.capabilities]

    @staticmethod
    def _check(source: Source) -> Health:
        """Run one Source's health check, turning any misbehaviour into ``ready=False``.

        The single place a Source's ``health()`` is invoked, so the guarantee
        "a broken adapter is reported, never propagated" holds for every
        caller — :meth:`health` and :meth:`require_ready` alike.

        Two ways an adapter can misbehave, both contained here:

        - it raises. Only the exception *type* reaches the report: driver and
          connection errors routinely carry paths, DSNs and credentials in
          their message, and this report is logged today and may be shown to
          an agent later.
        - it returns something that is not a :class:`Health` (``None`` from a
          forgotten ``return``, say). Letting that through would raise
          ``AttributeError`` out of the readiness gate, contradicting the
          guarantee this method exists to provide.
        """
        try:
            result = source.health()
        except Exception as exc:  # reported as unready, never propagated
            return Health(
                ready=False,
                detail=f"health() raised {type(exc).__name__} (message withheld: it may contain credentials)",
            )
        if not isinstance(result, Health):
            return Health(
                ready=False,
                detail=f"health() returned {type(result).__name__}, expected Health",
            )
        return result

    def health(self) -> dict[str, Health]:
        """Check every registered Source and return all outcomes.

        Never raises on an unhealthy source: the point is to see the whole
        picture at once, so one broken adapter cannot hide the state of the
        others. See :meth:`_check` for how adapter misbehaviour is contained.

        Returns:
            One :class:`~lazydataspace.source.Health` per source, keyed by name,
            in registration order.
        """
        return {name: self._check(source) for name, source in self._sources.items()}

    def require_ready(self, *names: str) -> None:
        """Assert that the named Sources (or all of them) are reachable.

        The readiness gate a scheduled job calls before its first write.
        Checks every named source and reports *all* failures together —
        fixing one deployment problem at a time, one run at a time, is the
        failure mode this exists to avoid.

        Only the named Sources are contacted. A job that needs two of five
        registered sources should not fail, wait on, or even touch the other
        three.

        Args:
            *names: Source names to check. Omit to check every registered
                source.

        Raises:
            UnknownSourceError: A named Source is not registered. Raised
                before any check runs, so a typo cannot silently gate on
                nothing.
            SourceNotReadyError: At least one checked Source is not ready.
                The message names every failing source and its detail.
        """
        targets = names or tuple(self._sources)
        for name in targets:
            if name not in self._sources:
                raise UnknownSourceError(
                    f"Unknown source {name!r}. Registered: {sorted(self._sources) or '(none)'}"
                )

        checked = [(name, self._check(self._sources[name])) for name in targets]
        failures = [(name, health) for name, health in checked if not health.ready]
        if failures:
            lines = "\n".join(f"  - {name}: {health.detail}" for name, health in failures)
            raise SourceNotReadyError(f"{len(failures)} of {len(targets)} source(s) not ready:\n{lines}")


__all__ = ["DataSpace"]
