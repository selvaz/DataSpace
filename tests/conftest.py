"""Fake Sources for the core test suite.

The frozen scope for v0.1 is explicit that the core is tested against fakes
only — no real adapter, no database, no filesystem. These fakes exercise the
protocol's contract, including the ways an adapter can misbehave (raising
from ``health()``, reporting itself unready).

``FakeSource`` is handed to tests through the ``make_source`` fixture rather
than imported from this module: several sibling repositories in this
ecosystem also have a top-level ``tests`` package, and importing
``tests.conftest`` resolves to whichever one happens to be on ``sys.path``
first.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from lazydataspace.source import Health, SourceInfo


class FakeSource:
    """A minimal in-memory Source satisfying the protocol structurally.

    Args:
        name: Logical name.
        owner: Owning repository.
        capabilities: Declared capability strings.
        ready: What ``health()`` reports.
        detail: Health detail; defaults to a reason when ``ready`` is False.
        raises: When set, ``health()`` raises this instead of returning.
    """

    def __init__(
        self,
        name: str = "fake",
        owner: str = "test-repo",
        capabilities: tuple[str, ...] = (),
        *,
        ready: bool = True,
        detail: str = "",
        raises: Exception | None = None,
    ) -> None:
        self._name = name
        self._owner = owner
        self._capabilities = capabilities
        self._ready = ready
        self._detail = detail or ("" if ready else "fake source configured as unready")
        self._raises = raises
        self.health_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def capabilities(self) -> tuple[str, ...]:
        return self._capabilities

    def describe(self) -> SourceInfo:
        return SourceInfo(
            name=self._name,
            owner=self._owner,
            capabilities=self._capabilities,
            description=f"fake source {self._name}",
        )

    def health(self) -> Health:
        self.health_calls += 1
        if self._raises is not None:
            raise self._raises
        return Health(ready=self._ready, detail=self._detail)

    def domain_call(self) -> str:
        """Stands in for an adapter's own API (``returns()``, ``search_text()``, ...)."""
        return f"domain result from {self._name}"


@pytest.fixture
def make_source() -> Callable[..., FakeSource]:
    """Factory for :class:`FakeSource` — the way tests build fakes."""
    return FakeSource


@pytest.fixture
def market() -> FakeSource:
    return FakeSource("market", "market-data-hub", ("market.returns",))


@pytest.fixture
def crawler() -> FakeSource:
    return FakeSource("crawler", "lazycrawler", ("documents.search", "artifacts"))
