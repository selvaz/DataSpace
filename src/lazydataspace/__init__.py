"""DataSpace — a typed composition root for cross-repository data sources.

Two primitives, no magic:

- :class:`~lazydataspace.source.Source` — the protocol an owning repository
  implements to make one of its data endpoints registrable;
- :class:`~lazydataspace.space.DataSpace` — an explicit collection of
  already-configured Sources, with aggregate readiness checking.

```python
from lazydataspace import DataSpace

space = DataSpace(market_source, crawler_source, stats_source)
space.require_ready()                       # before the first write
returns = space.source("market").returns(["SPY", "TLT"])
```

Adapters live in the repositories that own the data; DataSpace imports none
of them. It does not open databases, resolve paths, read environment
variables, execute functions or schedule anything — every repository keeps
its own canonical resolver, and this layer only composes what the caller
built.
"""

from __future__ import annotations

from lazydataspace.errors import (
    DataSpaceError,
    DuplicateSourceError,
    SourceNotReadyError,
    UnknownSourceError,
)
from lazydataspace.source import Health, Source, SourceInfo
from lazydataspace.space import DataSpace

__version__ = "0.1.0"

__all__ = [
    # primitives
    "DataSpace",
    "Source",
    "SourceInfo",
    "Health",
    # errors
    "DataSpaceError",
    "DuplicateSourceError",
    "UnknownSourceError",
    "SourceNotReadyError",
]
