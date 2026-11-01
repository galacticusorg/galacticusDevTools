#!/bin/bash -l
# Launch one unattended Galacticus audit run (normally from scrontab; see
# scrontab.example and ReadMe.md).
#
#   runAudit.sh [config-file]
#
# The config file (default ~/.config/galacticus-audit/config.sh; template in
# config.example.sh) sets the AUDIT_* variables used below. The run:
#   1. works out a hard deadline (AUDIT_STOP_AT today, or AUDIT_HOURS from now, whichever is first);
#   2. fetches origin in AUDIT_REPO;
#   3. checks the weekly usage with usageGate.py preflight, and does not start if it says no;
#   4. runs Claude Code with the galacticus-audit skill, either headless (-p) or, if the
#      statusLine (and so the usage data) does not update in -p mode, interactively in a
#      private tmux server, until the skill writes its done file or the deadline passes;
#   5. syncs branch/PR state into the findings and regenerates INDEX.md.
# Builds and models run inside this job's own allocation (the obshpc rule: no sbatch).

set -u
config="${1:-$HOME/.config/galacticus-audit/config.sh}"
if [ ! -f "$config" ]; then
    echo "runAudit: no config file $config (copy config.example.sh there)" >&2
    exit 2
fi
# shellcheck source=/dev/null
source "$config"

tools="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${AUDIT_REPO:?set AUDIT_REPO in $config}"
: "${AUDIT_WORKDIR:?set AUDIT_WORKDIR in $config}"
: "${AUDIT_STATE_DIR:=$HOME/Dropbox/AI/audit}"
: "${AUDIT_MODE:=headless}"
: "${AUDIT_HOURS:=12}"
: "${AUDIT_STOP_AT:=}"
: "${AUDIT_CLAUDE:=claude}"
: "${AUDIT_CLAUDE_ARGS:=--permission-mode auto}"
: "${AUDIT_BACKLOG_MAX:=25}"
: "${AUDIT_JOBS:=24}"
: "${AUDIT_LENSES:=bugs,threading,units,physics}"
: "${AUDIT_PREFLIGHT_ARGS:=--min-headroom 10 --require-reset-within-hours 14}"
: "${AUDIT_PYTHON:=python3}"
: "${AUDIT_GATE_ARGS:=}"
export AUDIT_STATE_DIR AUDIT_REPO AUDIT_WORKDIR AUDIT_BACKLOG_MAX AUDIT_JOBS AUDIT_LENSES AUDIT_GATE_ARGS AUDIT_PYTHON
export AUDIT_TOOLS="$tools"

session="audit-$(date +%Y%m%d-%H%M)-${SLURM_JOB_ID:-$$}"
mkdir -p "$AUDIT_WORKDIR/runs" "$AUDIT_STATE_DIR/runs"
log="$AUDIT_WORKDIR/runs/$session.log"
export AUDIT_SESSION="$session"
exec > >(tee -a "$log") 2>&1

say() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

now=$(date +%s)
deadline=$(( now + AUDIT_HOURS * 3600 ))
if [ -n "$AUDIT_STOP_AT" ]; then
    stop_at=$(date -d "today $AUDIT_STOP_AT" +%s)
    [ "$stop_at" -lt "$deadline" ] && deadline=$stop_at
fi
export AUDIT_DEADLINE=$deadline
say "session $session on $(hostname), deadline $(date -d "@$deadline" '+%a %H:%M'), mode $AUDIT_MODE"
if [ "$deadline" -le $(( now + 1800 )) ]; then
    say "less than 30 minutes before the deadline: not starting"
    exit 0
fi

git -C "$AUDIT_REPO" fetch --quiet origin || { say "git fetch failed: not starting"; exit 1; }

# shellcheck disable=SC2086
gate() { "$AUDIT_PYTHON" "$tools/usageGate.py" $AUDIT_GATE_ARGS "$@"; }
usage_written() { "$AUDIT_PYTHON" -c 'import json,os,sys; p=os.environ.get("AUDIT_USAGE_FILE") or os.path.expanduser("~/.cache/claude-usage/usage.json")
try: print(int(json.load(open(p))["written"]))
except Exception: print(0)'; }

# Pre-flight. The usage file only updates after an API response in a session whose
# statusLine is statuslineUsage.py, so in headless mode make one tiny call first.
if [ "$AUDIT_MODE" = headless ]; then
    before=$(usage_written)
    # shellcheck disable=SC2086
    "$AUDIT_CLAUDE" -p "Reply with the single word OK." --max-turns 1 $AUDIT_CLAUDE_ARGS > /dev/null 2>&1
    after=$(usage_written)
    if [ "$after" -le "$before" ]; then
        say "the usage file did not update in -p mode (the statusLine probably does not run there):"
        say "set AUDIT_MODE=tmux in $config. Not starting."
        exit 0
    fi
fi
# In tmux mode, use a reading another session left if it is fresh; the skill repeats
# the pre-flight as its first step in any case.
# shellcheck disable=SC2086
decision=$(gate preflight $AUDIT_PREFLIGHT_ARGS); status=$?
say "preflight: $decision"
# Start only on "go"; in tmux mode also on "no fresh data" (4), which the skill re-checks.
if [ "$status" -ne 0 ] && { [ "$status" -ne 4 ] || [ "$AUDIT_MODE" = headless ]; }; then
    say "not starting (preflight exit status $status)"
    exit 0
fi

grace=900
max_segments=20

# Run one Claude Code session ("segment"). It ends by writing its done file:
#   finished <summary> | stopped <reason> | restart | wait-until <unix time>
run_segment() {
    local segment=$1 done_file=$2
    local prompt="Use the galacticus-audit skill to run an unattended audit loop (run mode). \
Session id: $session (segment $segment; if earlier segments exist, resume from the state on disk). \
Deadline (Unix time): $deadline. Done file: $done_file. State directory: $AUDIT_STATE_DIR. \
Galacticus checkout: $AUDIT_REPO. Work directory: $AUDIT_WORKDIR. Tools: $tools. \
Lenses: $AUDIT_LENSES. Backlog cap: $AUDIT_BACKLOG_MAX. Build parallelism: -j$AUDIT_JOBS."
    local name="$session.seg$segment"
    export AUDIT_DONE_FILE="$done_file"
    case "$AUDIT_MODE" in
        headless)
            # shellcheck disable=SC2086
            timeout --signal=INT --kill-after=120 $(( deadline - $(date +%s) + grace )) \
                "$AUDIT_CLAUDE" -p "$prompt" $AUDIT_CLAUDE_ARGS > "$AUDIT_WORKDIR/runs/$name.claude.txt" 2>&1
            say "segment $segment: claude exited with status $?"
            if grep -qiE "hit your (weekly|session) limit" "$AUDIT_WORKDIR/runs/$name.claude.txt"; then
                say "segment $segment hit a plan usage limit: the gate's forecast was too low" \
                    "(raise --cost-safety in AUDIT_GATE_ARGS?)"
            fi
            ;;
        tmux)
            # tmux session names can not contain '.' or ':'.
            local socket="galacticus-audit" command tmux_name="${name//[.:]/-}"
            # Pass the per-segment settings on the command line: a tmux server that is already
            # running would otherwise hand the session its own, older, environment.
            command="env AUDIT_DONE_FILE=$(printf '%q' "$done_file") AUDIT_DEADLINE=$deadline"
            command="$command AUDIT_SESSION=$(printf '%q' "$session")"
            command="$command $(printf '%q' "$AUDIT_CLAUDE") $AUDIT_CLAUDE_ARGS $(printf '%q' "$prompt")"
            env -u TMUX -u TMUX_PANE tmux -L "$socket" new-session -d -s "$tmux_name" -x 250 -y 50 "$command"
            say "segment $segment: started tmux session (attach: tmux -L $socket attach -t $tmux_name)"
            while env -u TMUX tmux -L "$socket" has-session -t "$tmux_name" 2>/dev/null; do
                if [ -e "$done_file" ]; then
                    sleep 30   # let the last turn finish writing
                    break
                fi
                if [ "$(date +%s)" -gt $(( deadline + grace )) ]; then
                    say "segment $segment: deadline passed without a done file: interrupting"
                    env -u TMUX tmux -L "$socket" send-keys -t "$tmux_name" Escape
                    sleep 60
                    break
                fi
                sleep 60
            done
            env -u TMUX tmux -L "$socket" capture-pane -p -S -3000 -t "$tmux_name" \
                > "$AUDIT_WORKDIR/runs/$name.screen.txt" 2>/dev/null
            env -u TMUX tmux -L "$socket" kill-session -t "$tmux_name" 2>/dev/null
            ;;
        *)
            say "unknown AUDIT_MODE=$AUDIT_MODE"
            exit 2
            ;;
    esac
}

outcome="no segment ran"
for segment in $(seq 1 $max_segments); do
    done_file="$AUDIT_WORKDIR/runs/$session.seg$segment.done"
    run_segment "$segment" "$done_file"
    if [ ! -e "$done_file" ]; then
        outcome="segment $segment ended without a done file (killed, crashed, or hit a limit)"
        break
    fi
    outcome=$(head -n 1 "$done_file")
    say "segment $segment: $outcome"
    case "$outcome" in
        restart*)
            ;;
        wait-until*)
            resume=$(echo "$outcome" | awk '$2 ~ /^[0-9]+(\.[0-9]*)?$/ {print int($2)}')
            if [ -z "$resume" ]; then
                outcome="stopped: malformed done file ($outcome)"
                break
            fi
            if [ "$resume" -ge $(( deadline - 1800 )) ]; then
                outcome="stopped: the five-hour window resets too close to the deadline"
                break
            fi
            say "sleeping until $(date -d "@$resume" '+%H:%M') for the five-hour window to reset"
            sleep $(( resume - $(date +%s) > 0 ? resume - $(date +%s) : 0 ))
            ;;
        *)
            break
            ;;
    esac
    if [ "$(date +%s)" -ge $(( deadline - 1800 )) ]; then
        outcome="stopped: less than 30 minutes before the deadline"
        break
    fi
done

"$AUDIT_PYTHON" "$tools/auditState.py" sync --repo "$AUDIT_REPO" || say "sync failed"
"$AUDIT_PYTHON" "$tools/auditState.py" index > /dev/null || say "index failed"
gate status || true
say "run over: $outcome"
cp "$log" "$AUDIT_STATE_DIR/runs/$session.launcher.log" 2>/dev/null || true
exit 0
