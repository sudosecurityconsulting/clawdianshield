"""
dashboard/server.py

ClawdianShield SOC/IR live dashboard. FastAPI + WebSocket. Tails JSONL
evidence files produced by the host-side observers (file_observer,
log_observer) and surfaces every NormalizedEvent to a Kibana-styled
analyst console in real time. Also reads reports/<run_id>_exec_log.json
for scenario run summaries and coverage gaps.

Usage:
    python -m dashboard.server
    python -m dashboard.server --host 0.0.0.0 --port 8088
    python -m dashboard.server --evidence-dir evidence --reports-dir reports

The server is read-only — it never mutates evidence or executes scenarios.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles


# MITRE ATT&CK mapping per scenario behavior — surfaced in the dashboard so
# analysts can see which techniques the active scenario is exercising.
ATTACK_MAP: dict[str, list[dict[str, str]]] = {
    "auth_anomalies": [
        {"id": "T1110", "name": "Brute Force"},
        {"id": "T1078", "name": "Valid Accounts"},
    ],
    "remote_execution_artifacts": [
        {"id": "T1059", "name": "Command and Scripting Interpreter"},
        {"id": "T1105", "name": "Ingress Tool Transfer"},
    ],
    "file_tamper": [
        {"id": "T1565", "name": "Data Manipulation"},
        {"id": "T1485", "name": "Data Destruction"},
    ],
    "staging": [
        {"id": "T1074", "name": "Data Staged"},
        {"id": "T1560", "name": "Archive Collected Data"},
    ],
    "persistence_path_changes": [
        {"id": "T1053", "name": "Scheduled Task/Job"},
        {"id": "T1037", "name": "Boot or Logon Initialization Scripts"},
    ],
    "anti_forensics": [
        {"id": "T1070", "name": "Indicator Removal"},
        {"id": "T1485", "name": "Data Destruction"},
    ],
    "cleanup": [
        {"id": "T1070.004", "name": "File Deletion"},
    ],
}


SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class EvidenceTailer:
    """
    Polls every *.jsonl file in the evidence directory for new lines and
    publishes parsed NormalizedEvent dicts into an asyncio queue. Polling is
    used (rather than inotify) so it works uniformly on Windows host volumes.
    """

    def __init__(self, evidence_dir: Path, poll_interval: float = 0.5) -> None:
        self.evidence_dir = evidence_dir
        self.poll_interval = poll_interval
        self._offsets: dict[Path, int] = {}
        self._inodes: dict[Path, int] = {}
        self._buffer: deque[dict[str, Any]] = deque(maxlen=2000)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._task: asyncio.Task | None = None

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._buffer)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    async def start(self) -> None:
        # Prime offsets at end of existing files so first poll only emits net-new
        # events. The initial buffer is filled by reading the tail of each file
        # so reload-after-launch still shows context.
        self._prime_buffer()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _prime_buffer(self) -> None:
        if not self.evidence_dir.exists():
            return
        for p in sorted(self.evidence_dir.glob("*.jsonl")):
            try:
                stat = p.stat()
                self._inodes[p] = stat.st_ino
                # Read up to last 500 lines into buffer to seed the dashboard.
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in lines[-500:]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        self._buffer.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                self._offsets[p] = stat.st_size
            except FileNotFoundError:
                continue

    async def _run(self) -> None:
        while True:
            try:
                self._poll_once()
            except Exception as exc:  # noqa: BLE001 — surface but never crash loop
                print(f"[tailer] poll error: {exc}", flush=True)
            await asyncio.sleep(self.poll_interval)

    def _poll_once(self) -> None:
        if not self.evidence_dir.exists():
            return
        for p in sorted(self.evidence_dir.glob("*.jsonl")):
            try:
                stat = p.stat()
            except FileNotFoundError:
                continue
            prior_inode = self._inodes.get(p)
            prior_offset = self._offsets.get(p, 0)
            # Rotation / truncate
            if prior_inode is not None and (
                stat.st_ino != prior_inode or stat.st_size < prior_offset
            ):
                prior_offset = 0
            self._inodes[p] = stat.st_ino
            if stat.st_size <= prior_offset:
                continue
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                f.seek(prior_offset)
                for line in f:
                    if not line.endswith("\n"):
                        break
                    prior_offset += len(line.encode("utf-8"))
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self._buffer.append(evt)
                    self._fanout(evt)
            self._offsets[p] = prior_offset

    def _fanout(self, evt: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(evt)
            except asyncio.QueueFull:
                # Drop oldest for slow consumer to keep liveness.
                try:
                    q.get_nowait()
                    q.put_nowait(evt)
                except Exception:
                    pass


def _load_runs(reports_dir: Path) -> list[dict[str, Any]]:
    if not reports_dir.exists():
        return []
    runs: list[dict[str, Any]] = []
    for p in sorted(reports_dir.glob("*_exec_log.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        runs.append(data)
    return runs


def _aggregate(events: list[dict[str, Any]], runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    by_host: dict[str, int] = defaultdict(int)
    by_collector: dict[str, int] = defaultdict(int)
    by_minute: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    paths: dict[str, int] = defaultdict(int)
    auth_users: dict[str, int] = defaultdict(int)

    for evt in events:
        sev = evt.get("severity", "info")
        etype = evt.get("event_type", "unknown")
        host = evt.get("host", "unknown")
        collector = evt.get("collector", "unknown")
        ts = evt.get("timestamp", "")
        bucket = ts[:16] if len(ts) >= 16 else ts  # YYYY-MM-DDTHH:MM
        by_severity[sev] += 1
        by_type[etype] += 1
        by_host[host] += 1
        by_collector[collector] += 1
        if bucket:
            by_minute[bucket][sev] += 1

        details = evt.get("details", {}) or {}
        if "path" in details:
            paths[details["path"]] += 1
        if "account" in details:
            auth_users[details["account"]] += 1

    timeseries = [
        {"bucket": k, **{sev: v.get(sev, 0) for sev in SEVERITY_RANK}}
        for k, v in sorted(by_minute.items())
    ]

    top_paths = sorted(paths.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_users = sorted(auth_users.items(), key=lambda kv: kv[1], reverse=True)[:10]

    latest_run = runs[0] if runs else None
    coverage_gaps: list[str] = latest_run.get("coverage_gaps", []) if latest_run else []
    behaviors_planned: list[str] = (
        latest_run.get("behaviors_planned", []) if latest_run else []
    )
    attack_techniques: list[dict[str, str]] = []
    for b in behaviors_planned:
        for t in ATTACK_MAP.get(b, []):
            if t not in attack_techniques:
                attack_techniques.append({**t, "behavior": b})

    return {
        "totals": {
            "events": len(events),
            "runs": len(runs),
            "hosts": len(by_host),
            "critical": by_severity.get("critical", 0),
            "high": by_severity.get("high", 0),
            "medium": by_severity.get("medium", 0),
            "low": by_severity.get("low", 0),
            "info": by_severity.get("info", 0),
        },
        "by_severity": by_severity,
        "by_type": by_type,
        "by_host": by_host,
        "by_collector": by_collector,
        "timeseries": timeseries,
        "top_paths": [{"path": p, "count": c} for p, c in top_paths],
        "top_users": [{"account": u, "count": c} for u, c in top_users],
        "latest_run": latest_run,
        "coverage_gaps": coverage_gaps,
        "attack_techniques": attack_techniques,
    }


def build_app(evidence_dir: Path, reports_dir: Path) -> FastAPI:
    app = FastAPI(title="ClawdianShield SOC Console", version="3.1.0")
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    tailer = EvidenceTailer(evidence_dir)

    @app.on_event("startup")
    async def _startup() -> None:
        await tailer.start()

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await tailer.stop()

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "evidence_dir": str(evidence_dir.resolve()),
            "reports_dir": str(reports_dir.resolve()),
            "buffered_events": len(tailer.snapshot()),
            "uptime_started": int(time.time()),
        }

    @app.get("/api/events")
    async def events(limit: int = 500) -> JSONResponse:
        snap = tailer.snapshot()
        return JSONResponse(snap[-limit:])

    @app.get("/api/runs")
    async def runs() -> JSONResponse:
        return JSONResponse(_load_runs(reports_dir))

    @app.get("/api/stats")
    async def stats() -> JSONResponse:
        snap = tailer.snapshot()
        runs_data = _load_runs(reports_dir)
        return JSONResponse(_aggregate(snap, runs_data))

    @app.get("/api/attack-map")
    async def attack_map() -> JSONResponse:
        return JSONResponse(ATTACK_MAP)

    def _resolve_run(run_id: str) -> dict[str, Any]:
        for r in _load_runs(reports_dir):
            if r.get("run_id") == run_id:
                return r
        raise HTTPException(status_code=404, detail=f"run not found: {run_id}")

    def _events_for_run(run_id: str) -> list[dict[str, Any]]:
        return [e for e in tailer.snapshot() if e.get("run_id") == run_id]

    def _techniques_for_run(run: dict[str, Any]) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        for b in run.get("behaviors_planned", []):
            for t in ATTACK_MAP.get(b, []):
                rec = {**t, "behavior": b}
                if rec not in out:
                    out.append(rec)
        return out

    def _brief_cache_path(run_id: str) -> Path:
        return reports_dir / f"{run_id}_brief.json"

    @app.get("/api/runs/{run_id}/brief")
    async def get_brief(run_id: str) -> JSONResponse:
        cache = _brief_cache_path(run_id)
        if not cache.exists():
            raise HTTPException(status_code=404, detail="no cached brief; POST to generate")
        return JSONResponse(json.loads(cache.read_text(encoding="utf-8")))

    @app.post("/api/runs/{run_id}/brief")
    async def generate_brief(
        run_id: str,
        model: str | None = None,
        regenerate: bool = False,
    ) -> JSONResponse:
        cache = _brief_cache_path(run_id)
        if cache.exists() and not regenerate:
            payload = json.loads(cache.read_text(encoding="utf-8"))
            payload["from_cache"] = True
            return JSONResponse(payload)

        run = _resolve_run(run_id)
        events = _events_for_run(run_id)
        if not events:
            # fall back to whole buffer if the run's events are no longer in
            # the rolling window (post-restart) — better than empty context
            events = tailer.snapshot()
        attack = _techniques_for_run(run)

        try:
            from claudianShield.intelligence.gemini_client import (
                GeminiNotConfigured,
                generate_brief as _gen,
            )
        except ImportError as exc:  # SDK not installed
            raise HTTPException(
                status_code=500,
                detail=f"google-genai SDK not installed: {exc}",
            )

        try:
            payload = await asyncio.to_thread(_gen, run, events, attack, model)
        except GeminiNotConfigured as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:  # noqa: BLE001 — surface SDK errors to the UI
            raise HTTPException(status_code=502, detail=f"gemini call failed: {exc}")

        cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        payload["from_cache"] = False
        return JSONResponse(payload)

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        await websocket.accept()
        q = tailer.subscribe()
        try:
            # Send a hello with a snapshot so the client paints immediately.
            await websocket.send_json({
                "kind": "hello",
                "snapshot": tailer.snapshot()[-200:],
            })
            while True:
                evt = await q.get()
                await websocket.send_json({"kind": "event", "event": evt})
        except WebSocketDisconnect:
            pass
        finally:
            tailer.unsubscribe(q)

    return app


def main() -> None:
    p = argparse.ArgumentParser(description="ClawdianShield SOC dashboard")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8088)
    p.add_argument("--evidence-dir", default="evidence")
    p.add_argument("--reports-dir", default="reports")
    args = p.parse_args()

    import uvicorn

    app = build_app(Path(args.evidence_dir), Path(args.reports_dir))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


app = build_app(Path("evidence"), Path("reports"))


if __name__ == "__main__":
    main()
