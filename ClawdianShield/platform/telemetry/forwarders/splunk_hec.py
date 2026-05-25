"""
telemetry/forwarders/splunk_hec.py

Ships NormalizedEvent records to a Splunk HTTP Event Collector (HEC) endpoint.

Env vars are read lazily inside send() so python-dotenv's load_dotenv() can
be called before or after this module is imported without silently disabling
the forwarder. If either var is absent, send() returns False and the caller
continues writing local JSONL — no crash, no exception.

Designed for HTTP HEC (SPLUNK_HEC_SSL=false on the Splunk container).
If you switch to HTTPS, add verify=False and suppress urllib3 warnings.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import requests

from core.models.event_schema import NormalizedEvent

logger = logging.getLogger(__name__)


def send(event: NormalizedEvent) -> bool:
    """
    POST a single NormalizedEvent to Splunk HEC.

    Returns True on a 200 acknowledgement, False on any error (missing config,
    network failure, HEC rejection). Callers must treat False as non-fatal.
    """
    hec_url = os.getenv("SPLUNK_HEC_URL", "").rstrip("/")
    hec_token = os.getenv("SPLUNK_HEC_TOKEN", "")

    if not hec_url or not hec_token:
        return False

    payload = {
        "time": _iso_to_epoch(event.timestamp),
        "host": event.host,
        "source": event.collector,
        "sourcetype": "_json",
        "index": "main",
        "event": event.model_dump(),
    }

    try:
        resp = requests.post(
            f"{hec_url}/services/collector/event",
            headers={
                "Authorization": f"Splunk {hec_token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=5,
        )
        if resp.status_code != 200:
            logger.warning("HEC rejected event: %s %s", resp.status_code, resp.text[:200])
            return False
        return True
    except requests.RequestException as exc:
        logger.warning("HEC send failed: %s", exc)
        return False


def _iso_to_epoch(ts: str) -> float:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return datetime.now(timezone.utc).timestamp()
