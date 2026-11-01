---
name: galacticus-audit
description: Audit Galacticus source for correctness bugs and physics errors, one prioritized file group at a time. Each confirmed finding is recorded in the shared Dropbox audit state. A small fix is staged on a local branch with a discriminating test, and is reviewed by an in-session reviewer agent before it is queued for Andrew. Runs unattended from runAudit.sh ("run" mode, which loops under a usage gate until a deadline), or interactively on one target. Use when asked to run the audit loop, audit a file or directory, or show the audit status.
argument-hint: "[run (launcher-supplied settings) | once [path | directory] | status]"
---

# Galacticus audit loop

The tools live in `$AUDIT_TOOLS` (`galacticusDevTools/codeAudits/auditLoop/`). The shared
state lives in `$AUDIT_STATE_DIR` (default `~/Dropbox/AI/audit`). Their formats are in
`ReadMe.md` there. The commands below are written as `state …`, `rank …` and `gate …`,
meaning `$AUDIT_PYTHON $AUDIT_TOOLS/auditState.py …`, `… prioritize.py …` and
`… usageGate.py $AUDIT_GATE_ARGS …`.

| Argument | What to do |
|---|---|
| `run` (the launcher's prompt gives the settings) | the unattended loop: sections 1–5 |
| `once [path or directory]` | one iteration (section 3) on that target, or on the top-ranked group if none is given, with the user watching. Skip the usage gate, and report back at the end |
| `status` | `state sync --repo $AUDIT_REPO`, `state index`, `gate status`; summarize the backlog and what is in flight |

In `run` mode, the launcher's prompt supplies the session id, deadline, done file, checkout,
work directory, lenses, backlog cap and `-j`. The same values are in the environment
(`$AUDIT_SESSION`, `$AUDIT_DEADLINE`, `$AUDIT_DONE_FILE`, `$AUDIT_REPO`, `$AUDIT_WORKDIR`,
`$AUDIT_LENSES`, `$AUDIT_BACKLOG_MAX`, `$AUDIT_JOBS`). In `once` mode, make up a session id
(`audit-once-<date>-<random>`) and take the rest from the environment or ask.

## 0. Ground rules (they override anything a finding seems to call for)

- **Nothing leaves the machine.** Commit to local `audit/*` branches in `$AUDIT_REPO` only.
  Never push, open a PR or issue, or comment anywhere. Andrew reviews the queue and opens
  the PRs himself.
- **Follow `.claude/CLAUDE.md`** of the Galacticus checkout: US spelling, Conventional Commits,
  no whole-file Fortran formatter, and contributor markers that hold names only (the
  description of the AI's part and its verification goes in the commit message).
- **Read the memory first:** `~/Dropbox/AI/memory/galacticus.md` (sections *Fortran and code
  pitfalls*, *Test coverage traps*, *An independent reference must match Galacticus' unit
  definitions*, *Parser and naming traps*), and the section of `~/Dropbox/AI/memory/machines.md`
  for this `hostname`. On obshpc, note the `GALACTICUS_FCFLAGS`, `-jN`-versus-job-memory and
  commit-hook `python3`/`lxml` entries.
- **Builds:** one `make` at a time, run as a background command with a log on disk, never
  polled with `sleep` or `pgrep`. Use `-j$AUDIT_JOBS`. Builds and models run inside this job;
  never `sbatch`.
- **Agents:** no more than one subagent at a time, `subagent_type: general-purpose` (never
  `fork`), each with a tight brief. A typical iteration has three: auditor, verifier,
  reviewer. Never start them in parallel.
- **Write as you go.** Every state change goes into the state directory as soon as it
  happens, so a session killed at any point loses at most the current step.
- **No unverified claims.** A candidate that the verifier can't confirm is either dropped,
  or recorded with `confidence: plausible` and status `verified`, with no fix staged.
- **Decisions that are Andrew's** (physics choices, defaults, API or parameter changes, anything
  that changes results in a way a paper or test does not settle) are recorded with status
  `parked` and a `questions_for_andrew` entry. Never guess one.

## 1. Start (`run` mode)

1. Check the environment: `hostname`, `$AUDIT_REPO` is a Galacticus checkout,
   `GALACTICUS_DATA_PATH` is set, and `$AUDIT_WORKDIR` exists. `export GALACTICUS_EXEC_PATH`
   to the worktree from step 4 before any build or test.
2. **Usage pre-flight:** in segment 1, `gate preflight --min-headroom 10`; in later segments
   (restarts, or after a wait), `gate check --session $AUDIT_SESSION`, since a restart should
   not stop a run that the per-iteration check would allow. If it exits non-zero, write
   `stopped <reason from the JSON>` (or, for exit 10, `wait-until <wait_until>`) to the done
   file, and end. Then run `gate mark --session
   $AUDIT_SESSION --label start`.
3. Sync the state: `state sync --repo $AUDIT_REPO` and `state index`. Then
   `state backlog --max $AUDIT_BACKLOG_MAX`. Exit 1 means the review queue is full: run in
   **find-only mode**, which skips steps 3.6 and 3.7.
4. Set up the worktree, a single persistent one that is reused across runs so builds stay
   incremental:
   ```bash
   wt=$AUDIT_WORKDIR/wt/audit
   [ -d "$wt" ] || git -C "$AUDIT_REPO" worktree add --detach "$wt" origin/master
   git -C "$wt" status --short   # must be clean; if not, a previous run died mid-fix: see 3.9
   ```
   Record `base=$(git -C "$AUDIT_REPO" rev-parse origin/master)`.
5. **A restarted segment** (the prompt gives a segment number above 1) resumes: read the run
   log, `state claims` for claims this session still holds, and `state finding list` for
   findings `found_by` this session that are still `fix-staged` or `in-peer-review`. Finish
   those (section 3.6 or 3.7) before picking a new target.
6. Open the run log `$AUDIT_STATE_DIR/runs/$AUDIT_SESSION.md` (append to it if this is a
   restarted segment). Its first line is a status line, `Status: in progress / done /
   stopped early at X`, which you keep current. Below it, list the settings, the base commit
   and the mode (fix or find-only).

## 2. The loop (`run` mode)

Repeat section 3 until a stop condition holds:

- **Before each iteration**, run `gate check --session $AUDIT_SESSION`:
  - exit 0 (`continue`): go on;
  - exit 10 (`wait`): write `wait-until <wait_until from the JSON>` to the done file and end
    the session. The launcher sleeps (spending nothing) and then starts a fresh session,
    which resumes from the state on disk;
  - exit 3 or 4 (`stop`): write `stopped <reason>` to the done file and end.
- **Context hygiene:** after three iterations in one session, write `restart` to the done
  file and end. The launcher starts a fresh session, which keeps each context small and
  cheap.
- Stop with `stopped tooling failure` if the same step fails twice in a row for reasons
  that are not the code under audit (for example the state directory is unwritable, the
  build environment is broken, or git is in a bad state). Say what failed in the run log.
- Re-check the backlog after every finding moves to `ready-for-review`, and switch to
  find-only mode when it reaches the cap.

When ending for any reason, first finish or roll back the current step (step 3.9 explains
how), update the run log's status line, and run `state index`.

## 3. One iteration

### 3.1 Pick a target

```bash
git -C "$wt" checkout --detach "$base"     # always audit the base commit
rank --repo "$wt" --session "$AUDIT_SESSION" --top 15
```

Take the top file and add the closely coupled files, which makes a group of about 3000
lines at most:
- the class's `_class.F90` file;
- sibling implementations that share code with it (where copy-paste bugs live);
- its `.Inc` files.

`rank --explain PATH` shows why a file ranks where it does. Prefer a group in which several
files rank highly. Then `state claim <paths…> --session $AUDIT_SESSION`. If any path is
refused, drop it from the group.

### 3.2 Audit (auditor agent)

Brief one agent with the paths, the base commit, and the lens checklists below. Tell it to
read `~/Dropbox/AI/memory/skills/galacticus-review/SKILL.md` sections 3–4 and the
`galacticus.md` sections from §0. It must read every file in the group in full, plus the
callers of each public method (`grep`). It must not build or run models. Standalone Python
calculations are fine. It returns candidates only, each with: `file:line`, what is wrong,
the evidence, the inputs or callers that would reach it, a proposed severity, and the lens.
It also lists the parts it checked and found clean.

The lenses (cover those in `$AUDIT_LENSES`):
- **bugs:** functionClass plumbing (constructor, destructor, `deepCopy`,
  `stateStore`/`stateRestore`, state not reset between nodes or trees, memo keys missing an
  argument); uninitialized variables; optional arguments used without `present()`; array
  bounds and off-by-one errors; kind-mismatched integer overflow; error paths that silently
  continue or return a value where they should call `Error_Report`; copy-paste errors between
  siblings.
- **threading:** module variables missing `threadprivate`; wrong `shared`/`private` clauses;
  unprotected updates to shared state; shared GSL or other solver objects; HDF5 access
  outside locks.
- **units:** Mpc vs kpc, Gyr vs s, comoving vs physical, h-scaling, SI constants mixed with
  internal units, and a dimensional check on every expression.
- **physics:** equations against the cited paper, term by term (coefficients, exponents,
  mass and radius definitions, fit validity ranges); limits (r→0, r→∞, zero mass, high z);
  conservation between components; numerics (cancellation, single-precision literals,
  absolute vs relative tolerances, unbracketed roots, extrapolation).

### 3.3 Verify (verifier agent)

Brief a **fresh** agent with the candidates as claims (`file:line`, what is wrong), **not**
the auditor's reasoning. Its job is to refute each one:
- trace a realistic path from real usage to the failure: a parameter file in `parameters/`
  or `testSuite/`, or a real caller;
- check for guards elsewhere, and for documented conventions that explain the code;
- for physics, re-derive the result or check it against the paper.

It may run standalone calculations. If a candidate needs a build or a model run to settle,
it returns a **requested check**: the exact command, and the result that would confirm or
refute the candidate. Run requested checks yourself in the worktree (one build at a time),
and send the raw output back to the same agent with `SendMessage` (load it with `ToolSearch`
`select:SendMessage`). It returns `confirmed`, `plausible` or `refuted` for each candidate,
with the evidence.

### 3.4 Record each surviving finding

`state finding new` checks for open findings on the same files and prints a note for each
one. Read those notes. If the new finding duplicates one, add the new evidence to the
existing finding instead (`state finding set F-… --note …`) and drop the new one.

```bash
state finding new --title "…" --severity S --category C --confidence confirmed \
    --file path:line [--file …] --complexity S|M|L --affects-reference-models true|false \
    --found-by "$AUDIT_SESSION" --body-file body.md
```

The body has the sections `## Problem`, `## Evidence` (the derivation, numbers, and the path
from a real input), `## Fix and tests`, `## Review`, and `## Questions for Andrew` if any.

Severity:
- **critical:** wrong results in a reference model or the default configuration.
- **high:** wrong results or a crash in normal use.
- **medium:** wrong in a reachable non-default configuration, or a misleading failure.
- **low:** cosmetic or documentation only.
- **latent:** not reachable from any bundled parameter file or caller.

`rank --explain` tells you whether a reference model uses the file.

Complexity, which sets Andrew's review order:
- **S:** about 30 source lines or fewer, self-contained.
- **M:** up to about 100 lines, or needs physics or design context.
- **L:** larger, stacked, or touches many classes.

### 3.5 Decide what to do with each finding

Stage a fix only if all of these hold: you are in fix mode; the fix is local and small (S, or
a contained M); it needs no decision that is Andrew's; and a test can be written that
discriminates (fails on master, passes with the fix).

Otherwise:
- if a decision is Andrew's, set `status=parked` with `questions_for_andrew`;
- if not, leave it `verified` and put the proposed fix in the body.

### 3.6 Stage the fix

```bash
git -C "$wt" checkout -b audit/F-NNNN-short-slug "$base"
state finding set F-NNNN branch=audit/F-NNNN-short-slug base=${base:0:10}
# a fix stacked on another finding's branch: branch from it instead, and record
#   state finding set F-NNNN depends_on=F-MMMM        (several: depends_on=F-MMMM,F-KKKK)
```

1. **Write the test first** (a unit test in `source/tests/`, a `testSuite/test-*.py` with
   `SUCCESS:`/`FAILED:` markers, or an added check in an existing test). Build, and show
   that it **fails** on the unfixed code. A test that passes on master is not a test of
   this bug.
2. Make the fix, rebuild, and show that the test passes. Run the existing testSuite scripts
   for the subsystem, plus `parameters/quickTest.xml`. If a reference model's results
   change, say by how much in the body.
3. Run `./scripts/aux/auditTestMarkers.py --check` and
   `python3 scripts/doc/extractContributors.py --check` when a test or marker changed.
4. Commit: one commit per fix (a separate test commit is fine). The message says what was
   wrong, the evidence, how it was verified, and that it was found and fixed by an
   unattended Claude Code audit run.
5. `state finding set F-NNNN status=fix-staged head=<sha>`, then fill in `## Fix and tests`.

If a fix will not come together (the test can't be made to discriminate, or the build
breaks in ways you can't resolve), delete the branch, leave the finding `verified` with
notes, and move on. Always leave the worktree clean and detached:
`git -C "$wt" checkout --detach "$base"`.

### 3.7 Review (reviewer agent)

`state finding set F-NNNN status=in-peer-review`. Then follow
`~/Dropbox/AI/memory/skills/galacticus-review/self-review.md` on the branch in `$wt`, with
`--rounds 3`, and with these changes for unattended running:
- the reviewer's brief gives the finding's *Problem* section as the goal, and never the
  verifier's reasoning;
- run its requested checks yourself, as in 3.3;
- where self-review says "go to the user" (a finding for the user, a point disputed twice,
  the round cap, a round with no change), set `status=parked` instead, record the open
  points under `questions_for_andrew`, and move on.

On `VERDICT: ACCEPT`, set `status=ready-for-review review_rounds=N head=<sha>` and add a
summary to the `## Review` section: what the reviewer checked, and what was fixed or
withdrawn in each round. Delete `REVIEW.md` from the worktree, or keep it out of git as
self-review describes, and copy its content into the finding body.

### 3.8 Close the iteration

1. `state coverage add --repo "$wt" --commit "$base" --session $AUDIT_SESSION --lens L
   --depth full <every file the auditor read in full> --finding F-…`, once per lens
   covered. A group with no findings is still recorded: clean coverage is the point.
2. `state release <paths…> --session $AUDIT_SESSION`.
3. `gate mark --session $AUDIT_SESSION --label "F-… / <group>"`.
4. `state index`. Append the iteration to the run log: the group, findings with their
   statuses, the branches, and the usage before and after.

### 3.9 Rolling back an unfinished step

On a stop or restart in the middle of an iteration:
- commit nothing half-done;
- check out the base detached;
- leave a half-made branch only if its finding body says exactly what is left;
- record coverage only for files that were fully audited;
- release the claims.

An expired claim is released automatically after 6 hours, but release them anyway.

## 4. End of run

Write the done file:
- `finished <summary>` when the target list ran out;
- otherwise the stop, wait or restart line from section 2.

Update the run log's status line and summary: iterations, findings by severity and status,
branches staged, the backlog, and usage at the start and end. Run `state index`.

## 5. Notes for Andrew's review (what the index is for)

`$AUDIT_STATE_DIR/INDEX.md` lists the `ready-for-review` queue easiest first, with stacked
branches after their parents. When Andrew accepts, rejects or parks a finding, he edits its
`status` (or asks a session to run `state finding set`). `state sync` notices PRs and merges.
The reviewer agent accepting a fix is **not** the human verification `CONTRIBUTING.md`
requires. Never describe a `ready-for-review` item as verified by a human.
