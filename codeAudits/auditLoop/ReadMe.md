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
| `prioritize.py` | Ranks source files by reference-model use, recent change, time since review, and bug density |
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
   `$AUDIT_STATE_DIR`). To credit the 2026-10-21 overnight sweep as a skim:
   ```bash
   ./auditState.py coverage backfill --repo $AUDIT_REPO --commit <commit it audited> \
       --date 2026-10-21 --session backfill-2026-10-21 --lens bugs --depth skim
   ```
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

- If `status` prints the usage, keep `AUDIT_MODE=headless`.
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

In tmux mode, nothing can answer a dialog. Before the first scheduled run, start `claude`
interactively once in `$AUDIT_REPO` and in `$AUDIT_WORKDIR/wt/audit`, and accept the
folder-trust prompt. Then check that the permission mode in `AUDIT_CLAUDE_ARGS` starts
without asking anything. If a session does stall at a prompt, the launcher interrupts it at
the deadline.

The launcher checks this itself in headless mode. If the probe call leaves the usage file
unchanged, it does not start.

## How a run proceeds

`runAudit.sh` works in this order:
1. It sets a deadline: `AUDIT_STOP_AT` (19:00 by default, an hour before the Saturday 20:00
   reset) or `AUDIT_HOURS` from now, whichever comes first.
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

To change a status, edit the file or run
`auditState.py finding set F-0123 status=accepted --note "…"`. The `set` command checks the
value, and records the change under `## History`.

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

Files claimed by another session are left out, and so are files fully reviewed in the last
30 days and unchanged since. All weights and scales are options.
