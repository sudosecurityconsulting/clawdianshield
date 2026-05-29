# Terminus Task Knowledge Base

> **Last updated:** 2026-05-28  
> **Owner:** sudopwnr (Kevin)  
> **Project ID:** `bfe79c33-8ab0-4061-9849-08d3207c9927` (Terminus-2nd-Edition)

---

## ⚠️ READ BEFORE TOUCHING ANY TERMINUS TASK ⚠️

This document is the single source of truth for building, debugging, and submitting
Terminus (Snorkel Terminal Bench) tasks. Every agent working on Terminus tasks MUST
read this file first. Failure to follow these rules will result in wasted evaluation
cycles and `NEEDS_REVISION` rejections.

---

## 1. Platform Architecture

Terminus tasks are evaluated by the **Harbor** execution framework on the Snorkel
backend. Understanding Harbor's flow is critical — every failure we've hit traces back
to a mismatch between what we uploaded and what Harbor expects.

### Harbor Evaluation Flow

```
1. BUILD:    Docker builds `environment/Dockerfile`
2. MOUNT:    Harbor mounts three directories into the running container:
               /solution/  ← contents of solution/ (READ-ONLY)
               /tests/     ← contents of tests/    (READ-ONLY)
               /logs/      ← writable output dir
3. ORACLE:   Harbor runs `bash /solution/solve.sh` (the oracle agent)
4. VERIFIER: Harbor runs `bash /tests/test.sh`   (the test verifier)
5. REWARD:   Harbor reads /logs/verifier/reward.txt
               "1" = oracle passed → proceed to model evaluation
               "0" = oracle failed → NEEDS_REVISION
               missing = crash → NEEDS_REVISION (Build FAILED)
```

### Critical Mount Path Rules

| What Harbor Expects | Actual Path in Container | Notes |
|---|---|---|
| Oracle solution | `/solution/` | **READ-ONLY** mount. Cannot chmod files here. |
| Test suite | `/tests/` | **READ-ONLY** mount. Cannot chmod files here. |
| Verifier logs | `/logs/verifier/` | **WRITABLE**. Must create `mkdir -p /logs/verifier` |
| App working dir | `/app/` | This is `WORKDIR` from the Dockerfile |

> [!CAUTION]
> **`/solution/` and `/tests/` are READ-ONLY mounts.** You cannot `chmod +x` files on
> them. If you need to execute scripts from these mounts, either:
> - Use `bash /solution/solve.sh` (bash interprets the file, doesn't need +x)
> - Copy to a writable location first: `cp /solution/solve.sh /tmp/ && chmod +x /tmp/solve.sh`

---

## 2. Task Directory Structure

Every task MUST follow this exact layout:

```
<task-name>/
├── environment/
│   ├── Dockerfile          # Builds the base image (dependencies, seed data)
│   ├── package.json        # Pinned dependencies (exact versions, no ^/~)
│   ├── package-lock.json   # Lockfile for npm ci
│   └── seed.js             # Data seeding script (runs at build time, then deleted)
├── solution/
│   ├── solve.sh            # Oracle entry point — Harbor runs this
│   └── cli.js              # Oracle implementation
├── tests/
│   ├── test.sh             # Verifier entry point — Harbor runs this
│   ├── test_outputs.test.js  # Jest test suite (for jest-based tasks)
│   └── seed.js             # OPTIONAL: runtime seeding (if data is generated at test time)
├── instruction.md          # Task description shown to AI models
└── metadata.json           # Task metadata (optional)
```

---

## 3. Common Failure Modes (Lessons Learned)

### 3.1 `No tests found` — Jest Root Configuration

**Symptom:** `No tests found, exiting with code 1`  
**Cause:** Jest runs from `/app` (the `WORKDIR`). Test files mounted at `/tests/` are
outside Jest's default root directories, so `testMatch` and `testRegex` never find them.

**Fix:** In `test.sh`, copy the tests INTO `/app` before running Jest:
```bash
cp -r /tests /app/tests
npx jest /app/tests/test_outputs.test.js --verbose --runInBand
```

### 3.2 `MODULE_NOT_FOUND` — seed.js Uses Relative Paths

**Symptom:** `Error: Cannot find module '/app/environment/seed.js'`  
**Cause:** `seed.js` used `path.join(__dirname, 'data', 'file.jsonl')` which resolves
relative to where seed.js lives. When seed.js is in `/tests/`, it writes to `/tests/data/`
instead of `/app/data/`.

**Fix:** Use absolute output paths in seed.js:
```javascript
// WRONG:
const OUTPUT_FILE = path.join(__dirname, 'data', 'auth_logs.jsonl');

// RIGHT:
const OUTPUT_FILE = '/app/data/auth_logs.jsonl';
```

### 3.3 `RewardFileNotFoundError` — test.sh Crashes Before Writing reward.txt

**Symptom:** `harbor.verifier.verifier.RewardFileNotFoundError: No reward file found`  
**Cause:** `set -e` in test.sh causes the script to exit immediately when a command
fails (e.g., Jest returns exit code 1). The script never reaches the line that writes
`reward.txt`.

**Fix:** Use `set +e` before running the test command, capture `$?` immediately:
```bash
set +e
npx jest ... > /logs/verifier/test_output.log 2>&1

if [ $? -eq 0 ]; then
    echo 1 > /logs/verifier/reward.txt
else
    echo 0 > /logs/verifier/reward.txt
fi
```

### 3.4 `FileNotFoundError: solve.sh` — Missing Oracle Entry Point

**Symptom:** `FileNotFoundError: /root/harbor_tasks/tbench-task/solution/solve.sh`  
**Cause:** The `solution/` directory didn't contain a `solve.sh`. Harbor requires this
file to exist as the oracle entry point.

**Fix:** Always create `solution/solve.sh` that copies the oracle into the working
directory and runs it:
```bash
#!/bin/bash
set -euo pipefail
cp /solution/cli.js /app/cli.js
node /app/cli.js
```

### 3.5 `chmod: Read-only file system` — Trying to chmod on RO mount

**Symptom:** `chmod: changing permissions of '/solution/solve.sh': Read-only file system`  
**Cause:** Harbor mounts `/solution` and `/tests` as read-only volumes.

**Fix:** Use `bash /solution/solve.sh` instead of `chmod +x && ./solve.sh`. Or copy
to `/tmp` first.

---

## 4. Quality Checks (Automated Static Analysis)

Before AutoEval runs, Snorkel performs automated quality checks. All must pass:

| Check | What It Validates |
|---|---|
| `behavior_in_task_description` | instruction.md describes ALL behaviors the tests verify |
| `behavior_in_tests` | Tests cover ALL behaviors described in instruction.md |
| `informative_test_structure` | Tests have descriptive names and clear grouping |
| `anti_cheating_measures` | Agent can't trivially bypass tests (no hardcoded answers in image) |
| `structured_data_schema` | If tests check JSON output, instruction.md documents the exact schema |
| `pinned_dependencies` | Base image pinned by digest, exact dependency versions, lockfile present |
| `typos` | No typos in filenames, paths, column names across all files |
| `tests_or_solution_in_image` | Dockerfile never COPYs tests/ or solution/ into the image |
| `hardcoded_solution` | Oracle derives answers computationally, not via hardcoded values |
| `file_reference_mentioned` | instruction.md names all input/output file paths |

> [!TIP]
> The quality checker is extremely literal. If your tests check a field like
> `processed_at`, the instruction.md MUST mention that field by name and describe
> when/how it should be set. Implicit requirements get flagged.

---

## 5. Dockerfile Best Practices

```dockerfile
# Pin the base image by digest
FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0

WORKDIR /app

# Install system deps if needed
RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install Node deps with exact versions
COPY package.json package-lock.json ./
RUN npm ci

# Seed data at build time, then remove the seed script
COPY seed.js ./
RUN node seed.js && rm seed.js
```

**Rules:**
- Never COPY `tests/` or `solution/` into the image
- Always use `npm ci` (not `npm install`)
- Pin exact versions in package.json (no `^` or `~`)
- Delete seed.js after running it (anti-cheat)

---

## 6. Local Testing (Docker Simulation)

**Always test locally before submitting.** This saves 10-30 minutes per evaluation cycle.

### Build the task image:
```bash
cd ~/<task-name>/environment
docker build -t <task-name>-env .
```

### Simulate the full Harbor flow:
```bash
docker run --rm \
  -v /home/sudopwnr/<task-name>/solution:/solution:ro \
  -v /home/sudopwnr/<task-name>/tests:/tests:ro \
  <task-name>-env \
  bash -c "mkdir -p /logs/verifier && \
           bash /solution/solve.sh && \
           echo ORACLE_DONE && \
           bash /tests/test.sh && \
           echo VERIFIER_DONE && \
           cat /logs/verifier/reward.txt"
```

**Expected output:** `ORACLE_DONE`, `VERIFIER_DONE`, `1`

If reward is `0` or the run crashes, debug locally before submitting.

---

## 7. STB CLI Reference

### List projects
```bash
stb projects list
```

### Submit a new task
```bash
stb submissions create ~/<task-folder> -p <project-id> -t 45
```

### Update an existing submission (after NEEDS_REVISION)
```bash
stb submissions update ~/<task-folder> -s <submission-id> -t 45
```

### Check submission status
```bash
stb submissions list --project-id <project-id>
```

### Get detailed feedback
```bash
stb submissions feedback <submission-id>
```

Feedback is written to `/tmp/feedback_<submission-id>_<timestamp>/`. Key files:
- `notes.txt` — quality check results + revision notes
- `agent_logs/jobs/.../verifier/test_output.log` — Jest output
- `agent_logs/jobs/.../verifier/reward.txt` — reward value
- `agent_logs/jobs/.../verifier/test-stdout.txt` — test.sh stdout
- `agent_logs/jobs/.../exception.txt` — Python traceback (if Harbor crashed)

---

## 8. Assignment States

| State | Meaning |
|---|---|
| `OFFERED` | Assignment created, no task uploaded yet |
| `EVALUATION_PENDING` | Task uploaded and queued for model evaluation |
| `NEEDS_REVISION` | AutoEval failed — check feedback for details |
| `ACCEPTED` | Task passed all checks and model evaluations |

---

## 9. Active Task Registry

### Task 1: TOTP Replay Audit (`totp-replay-audit`)
- **Location:** `~/totp-replay-audit/`
- **Submission ID:** `42f1a6ed-f97c-40ec-9a0b-13d50f2d6cce`
- **Type:** Jest-based (11 tests)
- **Domain:** RFC 6238 TOTP validation with replay detection, drift handling, SQLite
- **Local test result:** ✅ 11/11 tests pass, reward=1
- **Status:** EVALUATION_PENDING (as of 2026-05-28 ~20:00 UTC)

### Task 2: Auth Anomaly Detection (`task2`)
- **Location:** `~/task2/`
- **Submission ID:** `6cab4d62-aece-4ebb-8d55-68b63ec2c54b`
- **Type:** cmp-based (compare oracle output vs agent output)
- **Domain:** JSONL auth log analysis, brute-force detection with IP correlation
- **Local test result:** ✅ cmp match, reward=1
- **Status:** EVALUATION_PENDING (as of 2026-05-28 ~20:00 UTC)

### Task 3: IDOR Audit (`task3`)
- **Location:** `~/task3/`
- **Submission ID:** Not yet submitted (E006 concurrency limit)
- **Type:** cmp-based (compare oracle output vs agent output)
- **Domain:** API log analysis, IDOR detection via JWT user ID vs endpoint user ID
- **Local test result:** ✅ cmp match, reward=1
- **Status:** Awaiting submission slot

---

## 10. Revision History

| Date | Task | Issue | Root Cause | Fix |
|---|---|---|---|---|
| 05/27 | milestone_template | NEEDS_REVISION | Placeholder task, not real | N/A |
| 05/28 | totp-replay-audit | Build FAILED | Missing `solve.sh` | Created `solution/solve.sh` |
| 05/28 | task2 | Build FAILED | Missing `solve.sh` | Created `solution/solve.sh` |
| 05/28 | totp-replay-audit | Build FAILED | Jest: "No tests found" | Specified test path in jest cmd |
| 05/28 | task2 | Build FAILED | seed.js wrote to `/tests/data/` | Changed OUTPUT_FILE to absolute `/app/data/` |
| 05/28 | totp-replay-audit | Build FAILED | Jest still can't find tests at `/tests/` | Copy `/tests` → `/app/tests` before running jest |
| 05/28 | task2 | Build FAILED | seed.js still using `__dirname` | Fixed to absolute `/app/data/auth_logs.jsonl` |

---

## 11. Concurrency Limits

The Snorkel API enforces concurrency limits per project. Error `E006` means you've hit
the assignment limit. You cannot create new submissions until existing ones complete
evaluation or are cancelled. Currently limited to ~2 active evaluations at a time.

---

## 12. Rules for Agents

1. **Read this file before starting any Terminus work.**
2. **Always test locally with Docker before submitting.** No exceptions.
3. **Never reference ClawdianShield code when working on Terminus tasks.**
4. **Each task is isolated.** Task A's code never references Task B.
5. **Do not rotate API keys or delete accounts.**
6. **Do not pad responses or explain basics to Kevin.**
7. **If a submission comes back NEEDS_REVISION, fetch feedback first, then diagnose.**
8. **The most common failures are path issues, not logic issues.** Check mount paths.
