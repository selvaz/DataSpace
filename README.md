# DataSpace

**A typed composition root for cross-repository data sources.** Two
primitives, no runtime dependencies, no magic.

```python
from lazydataspace import DataSpace

space = DataSpace(market_source, crawler_source, stats_source)
space.require_ready()                              # before the first write
returns = space.source("market").returns(["SPY", "TLT"])
```

## What problem this solves

A workflow that spans several repositories has to answer one question before
it writes anything: *are all the data sources I need actually reachable
right now?* Today that answer is scattered across environment variables,
per-repository resolvers and config dicts with special keys — every job
reconstructs it, and reconstructing it wrong has already caused real bugs
(a report resolving figures against a different database than the one that
produced them; a crawler cache silently redirected by a shared config key).

DataSpace is the one place that composition happens, typed and checked
together.

## What this is not

Deliberately **not**: a database, a path resolver, a scheduler, an execution
engine, a function registry, an ORM, or a cross-database query layer. It
holds `Source` objects someone else constructed and routes lookups to them.

Every repository keeps its own canonical resolver — DataSpace does not
replace them, it composes over them. The core imports nothing from the
ecosystem, and a test enforces that.

## The two primitives

### `Source`

A `typing.Protocol`, checked structurally: no base class to inherit, no
decorator to apply. An adapter satisfies it by having the right members.

| Member | Purpose |
|---|---|
| `name` | Stable logical identifier, unique within a DataSpace |
| `owner` | The repository that owns and writes this data |
| `capabilities` | Dotted strings, e.g. `"market.returns"`, `"documents.search"` |
| `describe()` | Non-sensitive self-description (`SourceInfo`) |
| `health()` | A **real** reachability check |

`health()` must actually reach the endpoint. "The environment variable is
set" is not readiness — conflating the two is what `Health` exists to
prevent. Failures are returned as `Health(ready=False, detail=...)`, never
raised, so an aggregate report shows every source's state rather than
stopping at the first exception.

An adapter that misbehaves is contained rather than trusted: if `health()`
raises, only the **exception type** reaches the report — driver and
connection errors routinely carry DSNs and credentials in their message, and
this report is logged. If it returns something that isn't a `Health`, that
too becomes `ready=False` instead of an `AttributeError` escaping the gate.

`SourceInfo` has no *field* for a path, DSN or credential, so there is
nowhere to put one even by accident. That is a guarantee about the shape,
not the contents: `description` is free text, and keeping secrets out of it
is the adapter's obligation.

### `DataSpace`

| Method | Purpose |
|---|---|
| `add(source)` | Register one already-configured Source |
| `source(name)` / `space[name]` | Get the concrete adapter back |
| `list()` | Registered names, in registration order |
| `describe()` | Every Source's `SourceInfo` |
| `for_capability(cap)` | Sources declaring a capability |
| `health()` | Check everything, report all outcomes |
| `require_ready(*names)` | Readiness gate — raises unless reachable; contacts **only** the named sources |

Reading and publishing are *not* on `DataSpace`. They are per-domain APIs on
the concrete adapter, reached through `source()` — so this layer never
becomes a pass-through for calls it cannot type.

## Errors are fail-fast

| Error | Means |
|---|---|
| `DuplicateSourceError` | Two Sources under one name — a composition-root bug; last-write-wins would make the winner depend on registration order |
| `UnknownSourceError` | Requested name is not registered; the message lists what is |
| `SourceNotReadyError` | A readiness gate failed; the message names **every** failing source, not just the first |

All inherit `DataSpaceError`.

## Install

```bash
pip install -e ".[test]"
```

Requires Python 3.11+. No runtime dependencies.

## Develop

```bash
pytest tests/ -q
```

```bash
mypy src/lazydataspace --strict
```

```bash
ruff check src tests
```

## Status

v0.1.0 — the core only. Adapters for the owning repositories
(market-data-hub, LazyCrawler, LazyStats, LazyPortfolio) land next, each in
the repository that owns its data.

`DataRef`, federated search and `read()`/`publish()` routing are
intentionally deferred until a real workflow needs them.
