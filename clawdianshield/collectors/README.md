# Telemetry Collectors

Collectors capture host-level telemetry events for detection engineering.

## Output Schema

Each collector emits JSONL to `evidence/` with this structure:

```json
{
  "ts": "<iso8601>",
  "collector": "<fim|proc|net>",
  "host": "<hostname>",
  "event": {}
}
```

## Collectors

| Module | Description | Status |
|---|---|---|
| `fim.py` | File integrity monitoring via stat snapshots | planned |
| `proc.py` | Process creation events | planned |
| `net.py` | Network connection events | planned |

## Running

```bash
python collectors/fim.py --watch /etc --output evidence/fim.jsonl
```
