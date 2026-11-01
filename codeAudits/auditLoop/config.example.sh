# Configuration for runAudit.sh: copy to ~/.config/galacticus-audit/config.sh and edit.
# Sourced by bash, so plain VAR=value lines.

# The Galacticus checkout that holds the local audit branches (never pushed).
# Use a checkout dedicated to the audit, with working git hooks (see machines.md).
AUDIT_REPO=/scratch/abenson/galacticus_audit

# Scratch space: worktrees (one per branch), build logs, run logs, done files.
AUDIT_WORKDIR=/scratch/abenson/auditwork

# Shared state (findings, coverage, claims, INDEX.md), synced by Dropbox.
AUDIT_STATE_DIR=$HOME/Dropbox/AI/audit

# tmux: an interactive session in a private tmux server. headless: claude -p. Use tmux unless
# the statusLine (the only source of usage data) runs in -p mode; on obshpc it does not
# (checked 2026-11-01). See ReadMe.md, "Checking that usage data reaches the gate".
AUDIT_MODE=tmux

# Hard stop: AUDIT_STOP_AT today (local time), or AUDIT_HOURS after the start, whichever is first.
# The weekly reset is 20:00 on Saturday; stop an hour before it.
AUDIT_STOP_AT=19:00
AUDIT_HOURS=12

# Usage gate. Do not start unless the weekly reset is within 14 h (catches a moved reset
# day) and at least 10% of the allowance is free below the ceiling.
AUDIT_PREFLIGHT_ARGS="--min-headroom 10 --require-reset-within-hours 14"
# Options for every usageGate.py call (the reserve curve, the five-hour ceiling, the forecast
# safety factor; see usageGate.py --help). Empty means the defaults: a ceiling of 80% until
# 12 h before the reset, rising to 95% at 3 h before it.
AUDIT_GATE_ARGS=""

# Claude Code. The run is unattended, so permission prompts cannot be answered: choose a mode
# that lets it build, run tests and commit without prompting, e.g. auto mode, or a --settings
# file with an allowlist. Add --model here to pin a model.
AUDIT_CLAUDE=claude
AUDIT_CLAUDE_ARGS="--permission-mode auto"

# Loop settings, passed to the skill.
AUDIT_BACKLOG_MAX=25            # ready-for-review findings at which fix staging pauses
AUDIT_JOBS=24                   # make -j (about 24 in a 128 GB job; see machines.md)
AUDIT_LENSES=bugs,threading,units,physics

# A python3 with lxml for the commit hooks (the obshpc conda python3 lacks it since 2026-10-31).
AUDIT_PYTHON=/usr/bin/python3
