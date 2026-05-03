"""
intelligence/gemini_client.py

Gemini-backed incident brief generator. Takes a run's exec_log, the events
the observers captured during it, and the MITRE ATT&CK techniques the
scenario exercises, then asks Gemini to produce a SOC-grade markdown brief.

The model defaults to gemini-2.5-flash (overridable via the GEMINI_MODEL env
var or per-request argument). Briefs are written to
reports/<run_id>_brief.json so re-clicks don't re-bill.

Reads GEMINI_API_KEY (or GOOGLE_API_KEY as fallback) from claudianShield/.env.
Uses the google-genai SDK (google.genai), not the deprecated google-generativeai.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# load .env once at module import so the FastAPI process picks up keys
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    load_dotenv()  # also try cwd
except Exception:
    pass


DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
MAX_EVENTS_IN_PROMPT = 30
MAX_STEPS_IN_PROMPT = 25

_FINISH_REASONS = {
    0: "UNSPECIFIED",
    1: "STOP",
    2: "MAX_TOKENS",
    3: "SAFETY",
    4: "RECITATION",
    5: "LANGUAGE",
    6: "OTHER",
    7: "BLOCKLIST",
    8: "PROHIBITED_CONTENT",
    9: "SPII",
    10: "MALFORMED_FUNCTION_CALL",
}


class GeminiNotConfigured(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise GeminiNotConfigured(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) is not set. "
            "Add it to claudianShield/.env"
        )
    return key


def _trim_event(evt: dict[str, Any]) -> dict[str, Any]:
    details = evt.get("details", {}) or {}
    if isinstance(details, dict):
        # Drop very long fields like full sha256 hashes from the prompt context.
        details = {
            k: (v[:32] + "…" if isinstance(v, str) and len(v) > 64 else v)
            for k, v in details.items()
        }
    return {
        "ts": evt.get("timestamp"),
        "host": evt.get("host"),
        "type": evt.get("event_type"),
        "sev": evt.get("severity"),
        "collector": evt.get("collector"),
        "details": details,
    }


def build_prompt(
    run: dict[str, Any],
    events: list[dict[str, Any]],
    attack: list[dict[str, str]],
) -> str:
    steps = (run.get("steps") or [])[-MAX_STEPS_IN_PROMPT:]
    trimmed_events = [_trim_event(e) for e in events[-MAX_EVENTS_IN_PROMPT:]]
    coverage = run.get("telemetry_coverage") or {}

    return f"""You are a senior SOC analyst writing an incident brief for the
ClawdianShield deterministic adversary-emulation pipeline. The "run" below is
a synthetic but realistic intrusion replayed against a lab victim container.
Produce a markdown brief — terse, technical, executive-readable.

## RUN METADATA
```json
{json.dumps({
    "run_id": run.get("run_id"),
    "scenario_id": run.get("scenario_id"),
    "scenario_name": run.get("scenario_name"),
    "container": run.get("container"),
    "started_at": run.get("started_at"),
    "completed_at": run.get("completed_at"),
    "status": run.get("status"),
    "behaviors_planned": run.get("behaviors_planned", []),
    "step_count": len(run.get("steps") or []),
    "step_failures": len(run.get("step_failures") or []),
    "coverage_gaps": run.get("coverage_gaps", []),
}, indent=2)}
```

## EXECUTION STEPS (last {len(steps)} of {len(run.get("steps") or [])})
```json
{json.dumps([
    {
        "behavior": s.get("behavior"),
        "step_id": s.get("step_id"),
        "status": s.get("status"),
        "command": (s.get("command") or "")[:240],
        "elapsed_s": s.get("elapsed_s"),
    }
    for s in steps
], indent=2)}
```

## TELEMETRY COVERAGE
```json
{json.dumps(coverage, indent=2)}
```

## MITRE ATT&CK TECHNIQUES MAPPED
```json
{json.dumps(attack, indent=2)}
```

## OBSERVED EVENTS (last {len(trimmed_events)} from the live evidence stream)
```json
{json.dumps(trimmed_events, indent=2)}
```

## OUTPUT FORMAT
Return only markdown, no preamble. Use these exact sections:

# Incident Brief — <scenario_name>

## Executive Summary
2-3 sentences. Plain English. Lead with the impact.

## Attack Chain Narrative
Walk through the adversary's stages in order, citing specific behaviors and
ATT&CK technique IDs (T-numbers). Reference observed paths, accounts, and
file events directly from the data above. No speculation beyond what the
events support.

## Telemetry Assessment
What the sensors caught. Call out coverage gaps explicitly with the ATT&CK
techniques that would slip through them.

## Recommended Detections
Bulleted list. Each item: detection name, what it watches, which ATT&CK
techniques it covers, severity.

## Risk Rating
Single line: `**RISK: <CRITICAL|HIGH|MEDIUM|LOW>** — <one-sentence rationale>`

Be specific. Cite paths, accounts, technique IDs from the data. Do not
invent indicators that aren't in the events. Do not include disclaimers.
"""


def generate_brief(
    run: dict[str, Any],
    events: list[dict[str, Any]],
    attack: list[dict[str, str]],
    model: str | None = None,
) -> dict[str, Any]:
    """Synchronously call Gemini and return the brief payload."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=_api_key())
    model_name = model or DEFAULT_MODEL
    prompt = build_prompt(run, events, attack)

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=4096,
        ),
    )

    # Pull text out of all parts of the first candidate. response.text raises
    # if any part lacks a text field (e.g. function call), so iterate manually.
    text_parts: list[str] = []
    finish_reason: str = "UNKNOWN"
    candidates = getattr(response, "candidates", None) or []
    if candidates:
        cand = candidates[0]
        fr = getattr(cand, "finish_reason", None)
        finish_reason = str(fr.name) if hasattr(fr, "name") else _FINISH_REASONS.get(int(fr or 0), str(fr))
        for part in getattr(cand.content, "parts", []) or []:
            t = getattr(part, "text", None)
            if t:
                text_parts.append(t)
    text = "".join(text_parts).strip()

    usage = getattr(response, "usage_metadata", None)
    return {
        "run_id": run.get("run_id"),
        "model": model_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brief_markdown": text,
        "finish_reason": finish_reason,
        "prompt_chars": len(prompt),
        "response_chars": len(text),
        "prompt_tokens": getattr(usage, "prompt_token_count", None) if usage else None,
        "completion_tokens": getattr(usage, "candidates_token_count", None) if usage else None,
        "thoughts_tokens": getattr(usage, "thoughts_token_count", None) if usage else None,
    }
