# 09 — Orchestration (Jobs & Resumability)

**Milestone:** M1 · **Depends on:** [01](01-domain-model.md) · **Serves:** all long-running work

Runs 3,000–10,000-photo pipelines that survive crashes, unplugged drives, and app restarts.

---

## 1. The requirement that drives the design

At 10,000 photos and ~1 s/photo across 6 workers, analysis is **20–30 minutes**. In that
window, on a laptop with an external drive:

- the drive gets unplugged,
- the lid closes and the machine sleeps,
- a corrupt RAW kills a helper subprocess,
- the user quits the app.

"Restart from scratch" is not acceptable at that duration — it means the feature is unusable
in practice. **Per-photo checkpointing is therefore structural, not an optimization**, which
is why `job_item` exists in the schema (§01) rather than tracking progress in memory.

---

## 2. Job model

```
job        (kind, state, total, completed)          ← one per pipeline stage
  └ job_item (photo_id, state, attempts, error)     ← the checkpoint granularity
```

Stages, each a job kind: `scan` → `analyze` → `group` → `select` → `export`.

**Idempotent by construction.** Resuming = "select all `job_item` where state ≠ done". No
separate resume path, no bespoke recovery logic — the normal path *is* the recovery path.
Bespoke recovery code only runs during failures, i.e. exactly when it can't be tested well.

State transitions:

```
pending ──► running ──► done
               │
               ├──► failed     (attempts exhausted; error recorded)
               └──► cancelled  (user stopped)
```

Only `analyze` is per-photo parallel and expensive. `group` and `select` are whole-shoot
operations, cheap (seconds, §05.6) and simply re-run rather than checkpointed.

---

## 3. Worker pool

```
Python asyncio coordinator
  └─ N subprocesses of shootr-analyze  (N = min(6, performance_cores))
       └─ each: batch of 32–64 photos, JSONL to stdout, flushed per photo
```

- **Per-photo flush** (§03.4) means a batch killed at photo 40 of 64 still banks 40 results.
- Results stream back and commit in **transactions of ~50 items** — per-item commits would
  make SQLite fsync the bottleneck; per-batch-only risks losing a whole batch.
- N is bounded by **GPU** contention, not CPU (§03.6). Tunable, measured in the benchmark.

**Backpressure:** the coordinator keeps at most 2N batches in flight. Without it, queueing
all 10,000 paths up front holds every result in memory before the first commit.

---

## 4. Failure handling

| Failure | Detection | Response |
|---|---|---|
| Corrupt RAW | helper emits per-photo `error` | mark item `failed`, continue batch |
| Helper crash/hang | process exit / timeout (30 s per photo) | requeue the batch's unfinished items, `attempts++` |
| **Volume offline** | path check before each batch | **pause whole job**, don't fail items |
| Machine sleep | wall-clock gap detected on wake | verify volume, resume |
| App quit | job left `running` | on startup, reset stale `running` → `pending` |
| Disk full (our DB) | SQLite error | pause job, surface clearly |
| Repeated item failure | `attempts >= 3` | `failed` permanently; excluded from retries |

**Volume-offline gets special handling and must not be conflated with failure.** If a drive
unplugs at photo 4,000, the remaining 6,000 are *not* bad photos — they're temporarily
unreachable. Marking them `failed` would mean they're skipped on reconnect (`attempts`
exhausted), silently leaving 60% of the shoot unanalyzed. So: pause the job, leave items
`pending`, resume on reconnect.

**Stale-`running` reset on startup** is what makes app-quit recovery work: items claimed by
a worker that no longer exists are indistinguishable from in-progress ones without it.

---

## 5. Progress reporting

`job.completed` / `job.total` updated per commit batch. Streamed to clients over SSE (§10):

```jsonc
{ "job_id": 12, "kind": "analyze", "state": "running",
  "completed": 4210, "total": 10000,
  "rate_per_sec": 5.8, "eta_sec": 998,
  "failed": 3, "current": "IMG_4821.CR3" }
```

ETA from a rolling 60-second rate, not a cumulative average — cumulative rates lag badly
after a pause and produce visibly wrong estimates.

Failed-item count is always visible. A run that silently skipped 300 corrupt files while
reporting success would misrepresent coverage of the shoot.

---

## 6. Cancellation

User cancel → mark job `cancelled`, stop dispatching, let in-flight batches finish (they're
seconds). Completed work is **kept** — `analysis` rows are valid regardless of whether the
job that produced them finished, since they're immutable per `engine_version` (§01
invariant 3). Re-running later picks up exactly where it stopped.

---

## 7. Concurrency and locking

Single writer: the FastAPI process owns all writes (README rule 6). WAL mode lets clients
read during long analysis runs, which is what keeps the UI responsive mid-job.

One job per `(shoot, kind)` at a time — enforced by a uniqueness check on job creation.
Two concurrent `analyze` jobs on one shoot would double-decode and race on `analysis` rows.
Different shoots may run concurrently, though they share the worker pool.

---

## 8. Open questions

- **Sleep/wake behavior** with an external drive: does macOS remount at the same path? Volume
  UUID (§02) should handle it, but needs testing on real hardware.
- **Optimal batch size and N** — benchmark-dependent (§03.7).
- **Priority queue**: should the photos the user is currently viewing analyze first? Good UX
  for a partially-analyzed shoot, but complicates the flat job_item model. Deferred to post-M1.
