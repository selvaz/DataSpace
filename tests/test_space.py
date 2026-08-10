"""DataSpace core: registration, lookup, description, health, readiness gate."""

from __future__ import annotations

import ast
import pathlib

import pytest

import dataspace
from dataspace import (
    DataSpace,
    DataSpaceError,
    DuplicateSourceError,
    Health,
    Source,
    SourceInfo,
    SourceNotReadyError,
    UnknownSourceError,
)


class TestRegistration:
    def test_constructor_registers_in_order(self, market, crawler):
        space = DataSpace(market, crawler)
        assert space.list() == ["market", "crawler"]
        assert len(space) == 2

    def test_add_registers_incrementally(self, market, crawler):
        space = DataSpace()
        assert space.list() == []
        space.add(market)
        space.add(crawler)
        assert space.list() == ["market", "crawler"]

    def test_duplicate_name_raises_and_names_the_incumbent_owner(self, market, make_source):
        space = DataSpace(market)
        with pytest.raises(DuplicateSourceError) as exc:
            space.add(make_source("market", owner="some-other-repo"))
        assert "market" in str(exc.value)
        assert "market-data-hub" in str(exc.value), "the message must name the already-registered owner"

    def test_duplicate_does_not_replace_the_incumbent(self, market, make_source):
        """Last-write-wins would make the winner depend on registration order."""
        space = DataSpace(market)
        with pytest.raises(DuplicateSourceError):
            space.add(make_source("market", owner="some-other-repo"))
        assert space.source("market") is market

    def test_duplicate_in_constructor_raises(self, market, make_source):
        with pytest.raises(DuplicateSourceError):
            DataSpace(market, make_source("market"))


class TestLookup:
    def test_source_returns_the_concrete_adapter(self, market):
        space = DataSpace(market)
        assert space.source("market") is market
        assert space.source("market").domain_call() == "domain result from market"

    def test_getitem_is_an_alias(self, market):
        space = DataSpace(market)
        assert space["market"] is market

    def test_unknown_name_raises_and_lists_registered(self, market, crawler):
        space = DataSpace(market, crawler)
        with pytest.raises(UnknownSourceError) as exc:
            space.source("stats")
        assert "stats" in str(exc.value)
        assert "market" in str(exc.value) and "crawler" in str(exc.value)

    def test_unknown_name_on_empty_space_says_none(self):
        with pytest.raises(UnknownSourceError) as exc:
            DataSpace().source("market")
        assert "(none)" in str(exc.value)

    def test_contains(self, market):
        space = DataSpace(market)
        assert "market" in space
        assert "absent" not in space


class TestDescribe:
    def test_describe_returns_one_info_per_source(self, market, crawler):
        space = DataSpace(market, crawler)
        infos = space.describe()
        assert [i.name for i in infos] == ["market", "crawler"]
        assert all(isinstance(i, SourceInfo) for i in infos)

    def test_describe_carries_owner_and_capabilities(self, crawler):
        (info,) = DataSpace(crawler).describe()
        assert info.owner == "lazycrawler"
        assert info.capabilities == ("documents.search", "artifacts")

    def test_source_info_has_no_field_for_a_path_or_credential(self, market):
        """A structural guarantee about the *fields* only.

        Keeping the free-text ``description`` free of secrets is the
        adapter's obligation; this type cannot enforce it.
        """
        (info,) = DataSpace(market).describe()
        assert set(vars(info)) == {"name", "owner", "capabilities", "description"}


class TestCapabilities:
    def test_for_capability_matches(self, market, crawler):
        space = DataSpace(market, crawler)
        assert space.for_capability("documents.search") == [crawler]
        assert space.for_capability("market.returns") == [market]

    def test_for_capability_returns_all_matches_in_order(self, make_source):
        a = make_source("a", capabilities=("artifacts",))
        b = make_source("b", capabilities=("artifacts",))
        assert DataSpace(a, b).for_capability("artifacts") == [a, b]

    def test_absent_capability_returns_empty_not_raises(self, market):
        """An absent capability is a legitimate answer, unlike an unknown name."""
        assert DataSpace(market).for_capability("nobody.provides.this") == []


class TestHealth:
    def test_reports_every_source(self, market, crawler):
        report = DataSpace(market, crawler).health()
        assert set(report) == {"market", "crawler"}
        assert all(h.ready for h in report.values())

    def test_reports_unready_without_raising(self, make_source):
        space = DataSpace(make_source("broken", ready=False, detail="db file missing"))
        report = space.health()
        assert report["broken"].ready is False
        assert report["broken"].detail == "db file missing"

    def test_a_raising_source_is_reported_not_propagated(self, market, make_source):
        """One broken adapter must not hide the state of the others."""
        space = DataSpace(market, make_source("explodes", raises=RuntimeError("connection refused")))
        report = space.health()
        assert report["market"].ready is True
        assert report["explodes"].ready is False
        assert "RuntimeError" in report["explodes"].detail

    def test_exception_message_is_withheld_from_the_report(self, make_source):
        """Driver errors routinely carry DSNs and credentials; this report is logged."""
        secret = "postgres://admin:hunter2@10.0.0.5/prod"
        space = DataSpace(make_source("leaky", raises=RuntimeError(f"cannot connect to {secret}")))
        report = space.health()
        assert report["leaky"].ready is False
        assert "RuntimeError" in report["leaky"].detail, "the exception type is still useful"
        assert secret not in report["leaky"].detail
        assert "hunter2" not in report["leaky"].detail

    def test_exception_message_is_withheld_from_the_readiness_gate_too(self, make_source):
        secret = "hunter2"
        space = DataSpace(make_source("leaky", raises=RuntimeError(f"auth failed for {secret}")))
        with pytest.raises(SourceNotReadyError) as exc:
            space.require_ready()
        assert secret not in str(exc.value)

    def test_a_non_health_return_is_reported_as_unready(self, make_source):
        """A forgotten ``return`` must not raise AttributeError out of the gate."""
        broken = make_source("broken")
        broken.health = lambda: None  # type: ignore[method-assign]
        report = DataSpace(broken).health()
        assert report["broken"].ready is False
        assert "NoneType" in report["broken"].detail
        assert "expected Health" in report["broken"].detail

    def test_a_non_health_return_fails_the_gate_as_not_ready(self, make_source):
        broken = make_source("broken")
        broken.health = lambda: "ok"  # type: ignore[method-assign]
        with pytest.raises(SourceNotReadyError) as exc:
            DataSpace(broken).require_ready()
        assert "str" in str(exc.value)

    def test_health_always_returns_health_values(self, market, make_source):
        space = DataSpace(market, make_source("raises", raises=ValueError("x")))
        assert all(isinstance(h, Health) for h in space.health().values())

    def test_empty_space_reports_empty(self):
        assert DataSpace().health() == {}


class TestRequireReady:
    def test_passes_when_all_ready(self, market, crawler):
        DataSpace(market, crawler).require_ready()  # must not raise

    def test_raises_when_any_source_unready(self, market, make_source):
        space = DataSpace(market, make_source("broken", ready=False, detail="db file missing"))
        with pytest.raises(SourceNotReadyError) as exc:
            space.require_ready()
        assert "broken" in str(exc.value)
        assert "db file missing" in str(exc.value)

    def test_reports_all_failures_together(self, make_source):
        space = DataSpace(
            make_source("a", ready=False, detail="reason a"),
            make_source("b", ready=False, detail="reason b"),
            make_source("c"),
        )
        with pytest.raises(SourceNotReadyError) as exc:
            space.require_ready()
        message = str(exc.value)
        assert "reason a" in message and "reason b" in message
        assert "2 of 3" in message

    def test_can_gate_on_a_subset(self, market, make_source):
        space = DataSpace(market, make_source("unused", ready=False, detail="not needed here"))
        space.require_ready("market")  # must not raise

    def test_subset_gate_does_not_contact_unrequested_sources(self, market, make_source):
        """A job needing 1 of 3 sources must not touch — or wait on — the other 2."""
        unused = make_source("unused")
        space = DataSpace(market, unused)
        space.require_ready("market")
        assert market.health_calls == 1
        assert unused.health_calls == 0

    def test_subset_gate_still_fails_on_its_own_targets(self, market, make_source):
        space = DataSpace(market, make_source("needed", ready=False, detail="down"))
        with pytest.raises(SourceNotReadyError):
            space.require_ready("needed")

    def test_unknown_name_raises_before_any_health_check(self, market):
        """A typo in the gate must not silently check nothing."""
        space = DataSpace(market)
        with pytest.raises(UnknownSourceError):
            space.require_ready("market", "typo")
        assert market.health_calls == 0

    def test_empty_space_passes(self):
        DataSpace().require_ready()  # nothing registered, nothing to fail


class TestProtocolAndTypes:
    def test_fake_satisfies_the_protocol_structurally(self, market):
        assert isinstance(market, Source), "no base class or decorator should be required"

    def test_health_false_requires_a_detail(self):
        """A failing health report that says nothing is useless downstream."""
        with pytest.raises(ValueError):
            Health(ready=False)

    def test_health_true_needs_no_detail(self):
        assert Health(ready=True).detail == ""

    def test_all_errors_share_one_base(self):
        for error in (DuplicateSourceError, UnknownSourceError, SourceNotReadyError):
            assert issubclass(error, DataSpaceError)


#: Ecosystem packages the core must never import. Its whole premise is that
#: adapters live in the repositories that own the data.
FORBIDDEN_ROOTS = frozenset(
    {
        "lazytools",
        "lazystats",
        "lazyportfolio",
        "lazycrawler",
        "market_data_hub",
        "lazyfin",
        "lazypulse",
        "lazybridge",
    }
)


def forbidden_imports(source: str, forbidden: frozenset[str] = FORBIDDEN_ROOTS) -> list[str]:
    """Return the forbidden module roots imported by ``source``.

    Parses rather than greps: ``from lazytools import x`` is an import that
    a substring search for ``"import lazytools"`` does not see.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name.split(".")[0] for a in node.names if a.name.split(".")[0] in forbidden]
        elif isinstance(node, ast.ImportFrom) and node.module:  # module is None for `from . import x`
            root = node.module.split(".")[0]
            if root in forbidden:
                found.append(root)
    return found


class TestNoDomainCoupling:
    def test_package_imports_nothing_from_the_ecosystem(self):
        """The core must stay domain-agnostic: no adapter imports, ever."""
        package_dir = pathlib.Path(dataspace.__file__).parent
        offenders = {
            module.name: hits
            for module in sorted(package_dir.glob("*.py"))
            if (hits := forbidden_imports(module.read_text(encoding="utf-8")))
        }
        assert not offenders, f"core must stay domain-agnostic, found: {offenders}"

    def test_the_check_catches_plain_imports(self):
        assert forbidden_imports("import lazytools") == ["lazytools"]
        assert forbidden_imports("import lazystats.regimes.core") == ["lazystats"]

    def test_the_check_catches_from_imports(self):
        """The form the previous substring-based check silently missed."""
        assert forbidden_imports("from lazytools import registry") == ["lazytools"]
        assert forbidden_imports("from lazycrawler.db import CrawlerDB") == ["lazycrawler"]

    def test_the_check_ignores_allowed_imports(self):
        assert forbidden_imports("import builtins\nfrom dataclasses import dataclass") == []

    def test_the_check_ignores_relative_imports(self):
        assert forbidden_imports("from . import errors") == []
