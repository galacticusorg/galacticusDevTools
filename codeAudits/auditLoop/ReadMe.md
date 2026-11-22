# Audit loop

Tools for a recurring, unattended audit of Galacticus. Each audit run works through the
source a file group at a time, in priority order. Every confirmed finding is recorded in a
shared state directory. A small fix is staged on a local branch with a discriminating test,
and an in-session reviewer agent reviews it. The fix then waits in a queue for a human
review. A usage gate stops the run before it uses up the weekly plan allowance.

| File | What it does |
|---|---|
| `skill/SKILL.md` | The `galacticus-audit` Claude Code skill: the loop itself (target, audit, verify, record, fix, review, coverage) |
| `auditState.py` | Findings, coverage records, claims, the review backlog, branch/PR sync, and the generated `INDEX.md` |
| `auditDashboard.py` | Renders the state directory as one self-contained, read-only HTML page (review queue, findings, runs, coverage) |
| `prioritize.py` | Ranks source files by reference-model use, recent change, time since review, and bug density |
| `importPlan.py` | One-off: imports the items of the 2026-10-21 audit `PLAN.md` as findings |
| `usageGate.py` | Pre-flight and per-iteration checks against the weekly and five-hour usage windows |
| `statuslineUsage.py` | A Claude Code `statusLine` command that saves the usage data the gate reads |
| `runAudit.sh` | The launcher (run from `scrontab`): deadline, pre-flight, one or more Claude Code sessions, sync |
| `config.example.sh`, `scrontab.example` | Templates for the launcher's configuration and the weekly schedule |
| `tests/` | `python3 -m pytest codeAudits/auditLoop/tests` (needs git, not a Galacticus checkout) |

The scripts need only the Python standard library (3.9 or later) and git. `gh` is optional,
for `auditState.py sync --gh`.

## Setting up

1. **Status line.** Make `statuslineUsage.py` the status line in `~/.claude/settings.json`:
   ```json
   "statusLine": {"type": "command", "command": "/path/to/galacticusDevTools/codeAudits/auditLoop/statuslineUsage.py"}
   ```
   If you already have a status line, put its command in `AUDIT_STATUSLINE_NEXT` (in the
   `env` block of the same file). It receives the same input, and its output is shown
   instead. Usage is per account, so every session on the machine keeps
   `~/.cache/claude-usage/usage.json` fresh.
2. **Skill.** Link the skill where Claude Code finds it:
   `ln -s /path/to/galacticusDevTools/codeAudits/auditLoop/skill ~/.claude/skills/galacticus-audit`.
3. **Checkout.** Make a Galacticus checkout for the audit (`AUDIT_REPO`) with working git
   hooks, and a scratch directory (`AUDIT_WORKDIR`). The skill keeps a single persistent
   worktree in `$AUDIT_WORKDIR/wt/audit`, so builds stay incremental from one run to the
   next. Audit branches (`audit/F-NNNN-…`) stay local to this checkout.
4. **State.** Run `auditState.py init`, which creates `~/Dropbox/AI/audit/` (or
   `$AUDIT_STATE_DIR`). On a machine with no Dropbox client (obshpc, Caltech HPC), that
   folder is local until something syncs it. Set `AUDIT_STATE_SYNC` in the config (the
   template reuses `claude_memory_sync.sh` with the audit folder), and run the same command
   by hand after using `auditState.py` or `importPlan.py` outside a run. To credit the 2026-10-21 overnight sweep as a skim:
   ```bash
   ./auditState.py coverage backfill --repo $AUDIT_REPO --commit 350ee94947 \
       --date 2026-10-21 --session backfill-2026-10-21 --lens bugs --depth skim
   ```
   Then import the existing plan (see *Importing PLAN.md* below).
5. **Config.** Copy `config.example.sh` to `~/.config/galacticus-audit/config.sh` and edit it,
   in particular `AUDIT_CLAUDE_ARGS`. The run is unattended, so it needs a permission mode
   that won't stop at prompts.
6. **Schedule.** Install `scrontab.example` with `scrontab -e`.

### Checking that usage data reaches the gate

The `rate_limits` data is documented for the status line only. Whether the status line runs
in headless (`claude -p`) mode is not documented, so check it once on the machine:

```bash
rm -f ~/.cache/claude-usage/usage.json
claude -p "say hi"
./usageGate.py status
```

- If `status` prints the usage, `AUDIT_MODE=headless` will work. On obshpc it does not
  (checked 2026-11-01: interactive sessions get `rate_limits`, but `-p` never runs the status
  line), so the config template defaults to tmux.
- If it reports no usage data, set `AUDIT_MODE=tmux`: the launcher then runs each session
  interactively in a private tmux server (`tmux -L galacticus-audit`), where the status line
  certainly runs, and ends it when the skill writes its done file.

If no usage data appears, find out which link is missing:

1. **The script itself:**
   `echo '{"rate_limits":{"seven_day":{"used_percentage":1,"resets_at":2}}}' | ./statuslineUsage.py`
   should print `7d 1%` and write the usage file. If it doesn't, check that the file is
   executable and that its `python3` runs it.
2. **Whether Claude Code calls it:** add `"AUDIT_STATUSLINE_DEBUG": "1"` to the `env` block of
   `~/.claude/settings.json`, then start `claude` *interactively* and send one message.
   - `~/.cache/claude-usage/last-input.json` appears: the status line runs. Look for
     `rate_limits` in the saved `stdin`.
   - It never appears: the status line is not running at all (check the `statusLine` entry,
     and whether a project or managed settings file overrides it).
3. **What it is given:** if the input has no `rate_limits`, check `claude --version` (the
   field is recent) and `claude auth status`. The field is sent only for claude.ai
   subscription logins, not API keys, and only after the first response.
4. **Interactive works but `-p` doesn't:** use `AUDIT_MODE=tmux`.

In tmux mode, nothing can answer a dialog. The launcher always starts Claude Code in
`$AUDIT_REPO`, whatever directory it was started from (`scrontab` starts it in `$HOME`).
Before the first scheduled run, start `claude` interactively once in `$AUDIT_REPO`, and once
in `$AUDIT_WORKDIR/wt/audit`, and accept the folder-trust prompt both times. Then check that the permission mode in `AUDIT_CLAUDE_ARGS` starts
without asking anything. If a session does stall at a prompt, the launcher interrupts it at
the deadline.

The launcher checks this itself in headless mode. If the probe call leaves the usage file
unchanged, it does not start.

## How a run proceeds

`runAudit.sh` works in this order:
1. It sets a deadline: `AUDIT_STOP_AT` (18:00 by default: an hour before the Saturday reset at
   19:00 PST, two before 20:00 PDT) or `AUDIT_HOURS` from now, whichever comes first.
2. It fetches origin.
3. It runs `usageGate.py preflight`, and does not start unless the weekly reset is within
   14 hours and at least 10% is free below the ceiling.
4. It runs Claude Code sessions ("segments") with the skill in `run` mode.

Each segment ends by writing a done file whose first line is one of:

| Done file | Launcher does |
|---|---|
| `restart` | starts a fresh session (the skill does this every three iterations, to keep contexts small) |
| `wait-until <unix time>` | sleeps, spending nothing, until the five-hour window resets, then starts a fresh session |
| `stopped <reason>` / `finished <summary>` | ends the run |

At the end it runs `auditState.py sync` and `index`. Logs go to `$AUDIT_WORKDIR/runs/`. The
launcher's log and each session's run log (`runs/<session>.md`) are copied to the state
directory.

### The usage gate

Before every iteration the skill runs `usageGate.py check`. It stops when the coming
iteration would cross the weekly ceiling:

    ceiling(t) = 100 − max(5, 20 × min(1, hours_to_reset / 12))      (percent)

That is 80% until 12 hours before the reset, rising linearly to 95% at 3 hours before it. The
reserve only has to cover what you might want to do yourself before the reset, since
anything unused is lost at the reset.

The forecast cost of an iteration is 1.25 × the largest of the last three measured
iterations (from `usageGate.py mark` at each iteration boundary), or 3% until two marks
exist. The gate also checks:
- the deadline;
- the weekly reset;
- the five-hour window: near its 90% ceiling, the gate asks for a wait until it resets.

Every parameter can be changed with `AUDIT_GATE_ARGS` (see `usageGate.py --help`). Missing,
stale (over 15 minutes old) or incomplete usage data always means stop.

## State directory

```
findings/F-NNNN.md        one finding per file
coverage/<session>.jsonl  append-only review records, one file per session
claims/<hash>.json        locks on file groups being audited (6-hour lease)
runs/                     run logs, usage marks, launcher logs
INDEX.md                  generated: the review queue (do not edit)
```

**Findings** are Markdown with a front-matter block of `key: value` lines (a JSON value, or
a plain string), so they can be edited by hand:

```
---
id: F-0123
title: Kummer SIDM deceleration lacks M_DM/(M_DM+M★)
status: ready-for-review
severity: high
confidence: confirmed
complexity: S
category: physics
files: ["source/satellites/.../Kummer2018.F90:212"]
affects_reference_models: false
branch: audit/F-0123-kummer-dm-fraction
base: 433f96f860
head: c46016002a
depends_on: []
diff_lines: {"source": 9, "tests": 46}
review_rounds: 2
pr:
questions_for_andrew:
found_by: audit-20261107-0647-123456
created: 2026-11-07T09:12:44Z
updated: 2026-11-07T11:30:02Z
---

## Problem / ## Evidence / ## Fix and tests / ## Review / ## History
```

The fields:
- **Statuses:** `verified`, `fix-staged`, `in-peer-review`, `ready-for-review`, `accepted`,
  `pr-open`, `merged`, `parked`, `rejected`, `superseded`.
- **Severities:** `critical` (wrong results in a reference model or the default
  configuration), `high`, `medium`, `low`, `latent` (unreachable from any bundled parameter
  file or caller).
- **Complexity:** `S`, `M` or `L`. It sets the review order, together with `diff_lines`,
  which `sync` fills in.

A `verified` finding with `fix_pending: true` has a fix that a session decided to stage but
couldn't finish. The next session resumes it first (`finding list --fix-pending`), and clears
the flag once the fix is staged or abandoned.

To change a status, edit the file or run
`auditState.py finding set F-0123 status=accepted --note "…"`. The `set` command checks the
value, and records the change under `## History`.

A finding with a `pr` number is marked `merged` once `origin/master` has GitHub's
"Merge pull request #N" commit, whether or not its branch is in the checkout. That check needs
no `gh`; with `--gh`, `sync` also records the PR's changed files in `pr_files`.

`auditState.py sync --repo $AUDIT_REPO [--gh]` keeps a finding's branch head and diff size
current. It marks the finding `merged` once the branch is on `origin/master`; with `--gh`, it
also notes PR numbers and marks open PRs `pr-open`.

**Coverage records** hold one line per file, lens and review:

```json
{"path": "source/cooling/cooling_rate/White-Frenk.F90", "blob": "9f2c…", "commit": "0931377…",
 "lens": "bugs", "depth": "full", "date": "2026-11-07T10:02:11Z", "session": "…", "findings": ["F-0124"]}
```

`blob` is the file's git blob hash at review time, so `prioritize.py` can tell exactly
whether a file has changed since it was reviewed. The lenses are `bugs`, `threading`,
`units`, `physics` and `docs`. The depth is `full` or `skim`.

**Concurrency:** Each session writes only its own coverage and run files, and each finding
is its own file, so Dropbox conflicts are rare. `auditState.py index` lists any conflicted
copies it finds. Finding ids are allocated with an exclusive create, so they are unique on a
machine. Two machines creating findings at the same moment could still collide, and that
collision would show up as a conflicted copy.

## Dashboard

`auditDashboard.py --output DIR/index.html [--state DIR] [--repository OWNER/NAME]` writes the
state directory as one HTML page. It shows the review queue in the order `INDEX.md` uses, with the
parked findings and their questions; a searchable, sortable table of every finding (filter by
status, severity and category); each finding's front matter and rendered body (open one with
`#F-0123` in the URL); the active claims; the latest run logs; and the coverage by lens and session.
Files link to `master` on GitHub and PR numbers to their PRs. It only reads the state directory.

The data is embedded in the page, so it can be served as a plain file. Bodies are rendered in the
browser by marked and DOMPurify from cdnjs; offline, they are shown as plain text. To keep it
current, run it from cron and serve the output directory, e.g. with Tailscale:

```
30 * * * * /usr/bin/python3 .../auditLoop/auditDashboard.py --output ~/auditDashboard/index.html
sudo tailscale serve --bg --set-path /audit ~/auditDashboard
```

## Prioritization

`prioritize.py --repo <checkout> [--lens bugs] [--top 30] [--explain PATH]` scores each file:

    score = 3·R + 2·C + 1.5·S + 0.5·B

- **R, reference-model use.** It is 1 if a reference model selects an implementation defined
  in the file, or the file defines the class itself. It is 0.5 for class defaults and default
  components, and 0.3 for modules used by a directly used file. The reference models are
  everything under `parameters/reference/`, the `testSuite/parameters/validate_*` files, and
  every parameter file (or directory) named by a `testSuite/validate-*.py` script, with
  XIncludes followed. The mapping is static: it matches parameter values to the
  `<className name="…">` directives, so it misses implementations chosen in code. A
  gcov-based mapping from instrumented runs of the reference models would be exact.
- **C, change.** It is 1 if the file changed since its last review under the lens. Otherwise
  it is recent churn: changed lines in the last 180 days, decayed with a 90-day e-folding
  time, and ignoring bulk commits that touch more than 150 files.
- **S, staleness.** It is 1 if the file has never been reviewed under the lens, otherwise
  days since the review divided by 180, capped at 1. A skim counts as a review 120 days
  older than it was.
- **B, bug density.** It counts findings that name the file (and, at a quarter weight, its
  directory), saturating at 3.

Files that a fix in flight is changing are left out too. These are the `files` and `pr_files`
of findings whose status is `fix-staged`, `in-peer-review`, `ready-for-review`, `accepted` or
`pr-open`. Auditing them now would mostly
re-find what the PR fixes, and a new fix there would conflict with it. They come back once
`sync` marks the finding `merged`, and since they then differ from any earlier review, they
rank highly. `--include-pr-open` turns this off, and `--explain PATH` says which finding
holds a file back.

Files claimed by another session are left out, and so are files fully reviewed in the last
30 days and unchanged since. All weights and scales are options.

## Importing PLAN.md

`importPlan.py` turns the checkbox items of the 2026-10-21 audit plan
(`~/Dropbox/AI/memory/overnight-2026-10-21/PLAN.md`) into findings, so that there is one
tracker. Run it on obshpc, where the checkout has the full history and `gh` can list the
open PRs:

```bash
./importPlan.py ~/Dropbox/AI/memory/overnight-2026-10-21/PLAN.md --repo $AUDIT_REPO --gh \
    --preview /tmp/plan-import.md                      # look at the table first
./importPlan.py ~/Dropbox/AI/memory/overnight-2026-10-21/PLAN.md --repo $AUDIT_REPO --gh --write
./auditState.py sync --repo $AUDIT_REPO --gh && ./auditState.py index
```

Without `gh`, pass the open PRs as `--open-pr N` (repeated) and their changed files as
`--pr-files FILE.json` (`{"1806": ["source/…", …], …}`). The plan's own PR table already
marks its open rows.

How items map:

| PLAN.md | Finding |
|---|---|
| `[x]`, in an open PR (on the line, in the PR table, or from `gh`) | `pr-open`, with `pr`, `branch` and `pr_files` |
| `[x]`, otherwise | `merged` (noted when the line doesn't say "merged") |
| `[ ]` or `[~]` asking for Andrew's decision ("Andrew's call", "for Andrew", "waiting:") | `parked`, with the question |
| `[ ]` or `[~]`, otherwise | `verified` (`plausible` if *not run* or *not re-checked*) |
| `[-]` | `rejected` |
| Phase 3 items (audit tasks, not findings) | skipped |

Severity comes from the section the item is in (High, Medium, Minor, Documentation). The
category comes from the ID (P* items are physics, D-/PD- items docs) or is guessed from the
text, and every guess is noted in the finding's *Import notes*.

Files come from the backticked paths in the item's description, resolved against the
checkout (a generated `work/build/….p.F90` maps back to its source). For done items that
name no file, they come from the commits the line cites: a merge into master, or a plain
commit, but not a merge of master into a branch. Items left with no files are listed in the
preview, and their `files` can be added by hand.

After an importer fix, `--write --refresh` also rewrites the `title` and
`questions_for_andrew` of findings already imported. It records each change under
*History*, and leaves alone any field changed since the import with `finding set`. An edit
made directly in a finding file can't be detected, so check the preview first.

The import is idempotent: items already imported (matched by `plan_id`) are skipped. So
while `PLAN.md` stays in use, the import can be repeated to pick up new items. Once it has
been run, add a line at the top of `PLAN.md` saying that new items go in
`~/Dropbox/AI/audit/findings/` (with `auditState.py finding new`).

