"""DataSpace core: registration, lookup, description, health, readiness gate."""

from __future__ import annotations

import pytest

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

    def test_describe_exposes_no_path_or_secret_fields(self, market):
        """SourceInfo's whole point: safe to log or show an operator."""
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
        assert "connection refused" in report["explodes"].detail

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


class TestNoDomainCoupling:
    def test_package_imports_nothing_from_the_ecosystem(self):
        """The core must stay domain-agnostic: no adapter imports, ever."""
        import pathlib

        import dataspace

        package_dir = pathlib.Path(dataspace.__file__).parent
        forbidden = ("lazytools", "lazystats", "lazyportfolio", "lazycrawler", "market_data_hub", "lazyfin")
        for module in package_dir.glob("*.py"):
            text = module.read_text(encoding="utf-8")
            for name in forbidden:
                assert f"import {name}" not in text, f"{module.name} imports {name}"
