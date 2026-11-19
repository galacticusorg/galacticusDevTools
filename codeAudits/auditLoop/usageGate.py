#!/usr/bin/env python3
"""Decide whether an unattended audit run may start, or go on to another
iteration, without using up the weekly plan allowance before it resets.

    usageGate.py status
    usageGate.py preflight [--min-headroom 10] [--require-reset-within-hours 14]
    usageGate.py mark  --session ID [--label TEXT]
    usageGate.py check --session ID
    usageGate.py wait-five-hour

Reads the usage file written by statuslineUsage.py (`$AUDIT_USAGE_FILE`,
default `~/.cache/claude-usage/usage.json`).

The weekly ceiling falls as the reset approaches, since unused allowance is
lost at the reset and the reserve only has to cover what the user might
still want to do before then:

    ceiling(t) = 100 - max(reserve_min, reserve_max * min(1, hours_to_reset / reserve_horizon))

With the defaults (5, 20, 12 h) that is 80% twelve or more hours out, rising
linearly to 95% three hours before the reset, and 95% from then on.

`check` stops before the next iteration would cross the ceiling: it forecasts
the next iteration's cost as `cost_safety` times the largest of the last three
iteration costs, measured between `mark` calls (or `default_cost` until two
marks exist). Exit codes, used by the launcher and the skill:

    0  go / continue
    3  stop: the ceiling, the deadline, or the reset is too close
    4  stop: no usable usage data (missing, stale, or without a weekly window)
    10 wait: the five-hour window is nearly used up; `wait-five-hour` sleeps until it resets

Every decision is printed as one JSON object on stdout.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auditCommon as common  # noqa: E402

EXIT_GO, EXIT_STOP, EXIT_NO_DATA, EXIT_WAIT = 0, 3, 4, 10


def usage_file():
    return os.environ.get("AUDIT_USAGE_FILE") or os.path.expanduser("~/.cache/claude-usage/usage.json")


def emit(decision, code):
    print(json.dumps(decision, sort_keys=True))
    sys.exit(code)


def read_usage(arguments, now):
    """Return (usage, problem). usage has seven_used, seven_reset, five_used, five_reset, age_s."""
    try:
        with open(usage_file()) as stream:
            payload = json.load(stream)
    except (OSError, ValueError) as error:
        return None, "no usage data ({}: {})".format(usage_file(), error)
    age = now - float(payload.get("written", 0))
    if age > arguments.max_age_minutes * 60:
        return None, "usage data is stale ({:.0f} min old; is statuslineUsage.py the statusLine?)".format(age / 60)
    limits = payload.get("rate_limits") or {}
    seven = limits.get("seven_day") or {}
    five = limits.get("five_hour") or {}
    if seven.get("used_percentage") is None or seven.get("resets_at") is None:
        return None, "usage data has no seven_day window"
    usage = {"seven_used": float(seven["used_percentage"]), "seven_reset": float(seven["resets_at"]),
             "five_used": None, "five_reset": None, "age_s": round(age)}
    if five.get("used_percentage") is not None and five.get("resets_at") is not None:
        usage["five_used"] = float(five["used_percentage"])
        usage["five_reset"] = float(five["resets_at"])
    return usage, None


def ceiling(arguments, hours_to_reset):
    reserve = max(arguments.reserve_min,
                  arguments.reserve_max * min(1.0, max(0.0, hours_to_reset) / arguments.reserve_horizon_hours))
    return 100.0 - reserve


def marks_path(session):
    root = common.state_dir()
    os.makedirs(os.path.join(root, "runs"), exist_ok=True)
    return os.path.join(root, "runs", "{}-usage.jsonl".format(session))


def read_marks(session):
    marks = []
    try:
        with open(marks_path(session)) as stream:
            for line in stream:
                try:
                    marks.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return marks


def forecast(arguments, marks):
    """(weekly cost, five-hour cost, duration in s) of the next iteration."""
    weekly, hourly, durations = [], [], []
    for previous, current in zip(marks, marks[1:]):
        if current.get("label") == "start":
            continue  # a new segment: the gap may include a wait, so it is not an iteration
        # Same window if the reported reset times agree to within an hour (they may jitter).
        if abs(current["seven_reset"] - previous["seven_reset"]) < 3600:
            weekly.append(max(0.0, current["seven_used"] - previous["seven_used"]))
        if current.get("five_used") is not None and previous.get("five_used") is not None \
                and abs(current["five_reset"] - previous["five_reset"]) < 1800:
            hourly.append(max(0.0, current["five_used"] - previous["five_used"]))
        durations.append(max(0.0, current["t"] - previous["t"]))
    weekly_cost = max(weekly[-3:]) if weekly else arguments.default_cost
    # The five-hour allowance is smaller than the weekly one, so an iteration always takes at least as
    # large a share of it; with no history, assume four times as large.
    hourly_cost = max(max(hourly[-3:]), weekly_cost) if hourly else 4.0 * weekly_cost
    duration = max(durations[-3:]) if durations else arguments.default_duration_minutes * 60
    return (arguments.cost_safety * weekly_cost, arguments.cost_safety * hourly_cost, duration)


def deadline(arguments):
    value = arguments.deadline or os.environ.get("AUDIT_DEADLINE")
    return float(value) if value else None


def base_decision(usage, now, arguments):
    hours = (usage["seven_reset"] - now) / 3600.0
    return {"seven_used": usage["seven_used"], "hours_to_weekly_reset": round(hours, 2),
            "ceiling": round(ceiling(arguments, hours), 2), "five_used": usage["five_used"],
            "data_age_s": usage["age_s"]}


def command_status(arguments):
    now = time.time()
    usage, problem = read_usage(arguments, now)
    if problem:
        emit({"action": "stop", "reason": problem}, EXIT_NO_DATA)
    decision = base_decision(usage, now, arguments)
    decision["action"] = "status"
    emit(decision, EXIT_GO)


def command_preflight(arguments):
    now = time.time()
    usage, problem = read_usage(arguments, now)
    if problem:
        emit({"action": "stop", "reason": problem}, EXIT_NO_DATA)
    decision = base_decision(usage, now, arguments)
    hours = decision["hours_to_weekly_reset"]
    limit = deadline(arguments)
    if arguments.require_reset_within_hours is not None and hours > arguments.require_reset_within_hours:
        decision.update(action="stop", reason="the weekly reset is {:.1f} h away, more than the {} h this run "
                        "is scheduled for: has the reset day moved?".format(hours, arguments.require_reset_within_hours))
        emit(decision, EXIT_STOP)
    if hours < arguments.min_hours_to_reset:
        decision.update(action="stop", reason="the weekly reset is less than {} h away".format(arguments.min_hours_to_reset))
        emit(decision, EXIT_STOP)
    if limit is not None and limit - now < arguments.default_duration_minutes * 60:
        decision.update(action="stop", reason="too close to the deadline")
        emit(decision, EXIT_STOP)
    headroom = decision["ceiling"] - usage["seven_used"]
    decision["headroom"] = round(headroom, 2)
    if headroom < arguments.min_headroom:
        decision.update(action="stop", reason="headroom {:.1f}% below the {}% minimum".format(headroom, arguments.min_headroom))
        emit(decision, EXIT_STOP)
    decision["action"] = "go"
    emit(decision, EXIT_GO)


def command_mark(arguments):
    now = time.time()
    usage, problem = read_usage(arguments, now)
    if problem:
        emit({"action": "stop", "reason": problem}, EXIT_NO_DATA)
    mark = {"t": now, "label": arguments.label, "seven_used": usage["seven_used"], "seven_reset": usage["seven_reset"],
            "five_used": usage["five_used"], "five_reset": usage["five_reset"]}
    common.append_line(marks_path(arguments.session), json.dumps(mark, sort_keys=True))
    emit({"action": "marked", **mark}, EXIT_GO)


def command_check(arguments):
    now = time.time()
    usage, problem = read_usage(arguments, now)
    if problem:
        emit({"action": "stop", "reason": problem}, EXIT_NO_DATA)
    decision = base_decision(usage, now, arguments)
    weekly_cost, hourly_cost, duration = forecast(arguments, read_marks(arguments.session))
    decision.update(forecast_weekly=round(weekly_cost, 2), forecast_five_hour=round(hourly_cost, 2),
                    forecast_minutes=round(duration / 60, 1))
    limit = deadline(arguments)
    if limit is not None and now + duration > limit:
        decision.update(action="stop", reason="the next iteration would run past the deadline")
        emit(decision, EXIT_STOP)
    if now + duration > usage["seven_reset"]:
        decision.update(action="stop", reason="the next iteration would run past the weekly reset")
        emit(decision, EXIT_STOP)
    if usage["seven_used"] + weekly_cost >= decision["ceiling"]:
        decision.update(action="stop", reason="the next iteration would cross the weekly ceiling")
        emit(decision, EXIT_STOP)
    if usage["five_used"] is not None and usage["five_used"] + hourly_cost >= arguments.five_hour_ceiling:
        resume = usage["five_reset"] + arguments.wait_margin_seconds
        if (limit is not None and resume + duration > limit) or resume + duration > usage["seven_reset"]:
            decision.update(action="stop", reason="the five-hour window resets too late to fit another iteration")
            emit(decision, EXIT_STOP)
        decision.update(action="wait", wait_until=round(resume),
                        reason="the five-hour window is nearly used up: wait for its reset")
        emit(decision, EXIT_WAIT)
    decision["action"] = "continue"
    emit(decision, EXIT_GO)


def command_wait_five_hour(arguments):
    """Sleep until the five-hour window resets (run it as a background command)."""
    now = time.time()
    usage, problem = read_usage(arguments, now)
    if problem or usage["five_reset"] is None:
        emit({"action": "stop", "reason": problem or "no five_hour window"}, EXIT_NO_DATA)
    target = usage["five_reset"] + arguments.wait_margin_seconds
    seconds = max(0.0, min(target - now, arguments.max_wait_hours * 3600))
    time.sleep(seconds)
    emit({"action": "waited", "seconds": round(seconds)}, EXIT_GO)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-age-minutes", type=float, default=15.0, help="reject older usage data")
    parser.add_argument("--reserve-min", type=float, default=5.0)
    parser.add_argument("--reserve-max", type=float, default=20.0)
    parser.add_argument("--reserve-horizon-hours", type=float, default=12.0)
    parser.add_argument("--five-hour-ceiling", type=float, default=90.0)
    parser.add_argument("--default-cost", type=float, default=3.0, help="weekly %% per iteration before any is measured")
    parser.add_argument("--default-duration-minutes", type=float, default=60.0)
    parser.add_argument("--cost-safety", type=float, default=1.25)
    parser.add_argument("--wait-margin-seconds", type=float, default=120.0)
    parser.add_argument("--deadline", help="Unix time after which no iteration may run (default $AUDIT_DEADLINE)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status").set_defaults(function=command_status)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--min-headroom", type=float, default=10.0)
    preflight.add_argument("--require-reset-within-hours", type=float)
    preflight.add_argument("--min-hours-to-reset", type=float, default=1.0)
    preflight.set_defaults(function=command_preflight)
    mark = commands.add_parser("mark")
    mark.add_argument("--session", required=True)
    mark.add_argument("--label")
    mark.set_defaults(function=command_mark)
    check = commands.add_parser("check")
    check.add_argument("--session", required=True)
    check.set_defaults(function=command_check)
    wait = commands.add_parser("wait-five-hour")
    wait.add_argument("--max-wait-hours", type=float, default=5.5)
    wait.set_defaults(function=command_wait_five_hour)
    arguments = parser.parse_args(argv)
    arguments.function(arguments)


if __name__ == "__main__":
    main()
