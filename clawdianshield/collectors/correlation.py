"""
collectors/correlation.py

Cross-host correlation primitives. Builds source -> target host adjacency from
the source_host field of NormalizedEvent.details.

Used by the scoring pass to verify that multi-host scenarios produced events
linking the expected hosts.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

from shared.models import NormalizedEvent


def build_host_graph(events: List[NormalizedEvent]) -> Dict[str, List[str]]:
    """
    Build source -> target host edges from cross-host event details.
    Returns adjacency dict: {source_host: [target_host, ...]}
    """
    graph: Dict[str, List[str]] = defaultdict(list)
    for e in events:
        src = e.details.get("source_host")
        if src and src != e.host and e.host not in graph[src]:
            graph[src].append(e.host)
    return dict(graph)


def cross_host_pairs(events: List[NormalizedEvent]) -> List[tuple[str, str]]:
    graph = build_host_graph(events)
    return [(src, tgt) for src, targets in graph.items() for tgt in targets]


_AUTH_TYPES = {"auth_failure", "auth_success"}
_FILE_TYPES = {"file_create", "file_modify", "file_delete", "file_rename"}


def correlate_auth_and_file(
    events: List[NormalizedEvent],
    window_seconds: float = 5.0,
) -> List[Tuple[NormalizedEvent, NormalizedEvent]]:
    """
    Return (auth_event, file_event) tuples where:
      - auth_event.event_type in {"auth_failure", "auth_success"}
      - file_event.event_type in {"file_create", "file_modify",
                                   "file_delete", "file_rename"}
      - auth_event.host == file_event.host
      - 0 <= (file_event.timestamp - auth_event.timestamp) <= window_seconds
    Output sorted by file_event.timestamp ascending. Each file event is paired
    with at most one auth event — the most recent qualifying auth event before
    it on the same host.
    """
    auth_events = [e for e in events if e.event_type in _AUTH_TYPES]
    file_events = [e for e in events if e.event_type in _FILE_TYPES]

    pairs: List[Tuple[NormalizedEvent, NormalizedEvent]] = []
    for fe in file_events:
        fe_ts = datetime.fromisoformat(fe.timestamp)
        best_auth: NormalizedEvent | None = None
        best_auth_ts: datetime | None = None
        for ae in auth_events:
            if ae.host != fe.host:
                continue
            ae_ts = datetime.fromisoformat(ae.timestamp)
            delta = (fe_ts - ae_ts).total_seconds()
            if 0 <= delta <= window_seconds:
                if best_auth is None or ae_ts > best_auth_ts:
                    best_auth = ae
                    best_auth_ts = ae_ts
        if best_auth is not None:
            pairs.append((best_auth, fe))

    pairs.sort(key=lambda p: datetime.fromisoformat(p[1].timestamp))
    return pairs
