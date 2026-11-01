"""Tests for the audit-loop tools. Run with `python3 -m pytest codeAudits/auditLoop/tests`.

They build a tiny fake Galacticus repository and state directory in a
temporary directory, so they need git but no Galacticus checkout.
"""
import json
import os
import subprocess
import sys
import textwrap
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
sys.path.insert(0, TOOLS)
import auditCommon as common  # noqa: E402
import auditState  # noqa: E402
import prioritize  # noqa: E402


def run(tool, *arguments, env=None, check=True):
    environment = dict(os.environ)
    environment.update(env or {})
    result = subprocess.run([sys.executable, os.path.join(TOOLS, tool)] + list(arguments), env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if check and result.returncode != 0:
        raise AssertionError("{} {} exited {}:\n{}\n{}".format(tool, arguments, result.returncode, result.stdout,
                                                             result.stderr))
    return result


def git(repo, *arguments):
    subprocess.run(["git", "-C", repo] + list(arguments), check=True, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                                    GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as stream:
        stream.write(textwrap.dedent(text))


@pytest.fixture
def state(tmp_path, monkeypatch):
    root = str(tmp_path / "state")
    monkeypatch.setenv("AUDIT_STATE_DIR", root)
    common.ensure_layout(root)
    return root


@pytest.fixture
def repo(tmp_path):
    """A fake Galacticus checkout: one functionClass with three implementations,
    a component, a helper module, and reference/validate parameter files."""
    path = str(tmp_path / "galacticus")
    write(os.path.join(path, "source/cooling/_class.F90"), """\
        !![
        <functionClass>
         <name>coolingRate</name>
         <default>whiteFrenk1991</default>
        </functionClass>
        !!]
        """)
    write(os.path.join(path, "source/cooling/white_frenk.F90"), """\
        !![
        <coolingRate name="coolingRateWhiteFrenk1991">
        </coolingRate>
        !!]
        module Cooling_White_Frenk
          use Numerical_Helper
        end module Cooling_White_Frenk
        """)
    write(os.path.join(path, "source/cooling/cole2000.F90"), """\
        !![
        <coolingRate name="coolingRateCole2000">
        </coolingRate>
        !!]
        """)
    write(os.path.join(path, "source/cooling/multiplier.F90"), """\
        !![
        <coolingRate name="coolingRateMultiplier">
        </coolingRate>
        !!]
        module Cooling_Multiplier
          use, intrinsic :: ISO_C_Binding
          use :: Numerical_Helper
        end module Cooling_Multiplier
        """)
    write(os.path.join(path, "source/numerical/helper.F90"), """\
        module Numerical_Helper
        end module Numerical_Helper
        """)
    write(os.path.join(path, "source/unused/orphan.F90"), "module Orphan\nend module Orphan\n")
    write(os.path.join(path, "source/objects/nodes/components/disk/standard/_class.F90"), """\
        !![
        <component>
         <class>disk</class>
         <name>standard</name>
         <isDefault>true</isDefault>
        </component>
        !!]
        """)
    write(os.path.join(path, "source/objects/nodes/components/disk/simple/_class.F90"), """\
        !![
        <component>
         <class>disk</class>
         <name>simple</name>
        </component>
        !!]
        """)
    write(os.path.join(path, "parameters/reference/evolution.xml"), """\
        <parameters>
          <coolingRate value="multiplier">
            <coolingRate value="cole2000"/>
          </coolingRate>
        </parameters>
        """)
    write(os.path.join(path, "testSuite/parameters/validate_model.xml"), """\
        <parameters xmlns:xi="http://www.w3.org/2001/XInclude">
          <xi:include href="../../parameters/reference/evolution.xml" xpointer="xpointer(parameters/*)"/>
          <componentDisk value="simple"/>
        </parameters>
        """)
    git(path, "init", "-q", "-b", "master")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "initial")
    return path


# ------------------------------------------------------------------ front matter

def test_front_matter_round_trip():
    fields = {"id": "F-0001", "title": "A: tricky [title]", "files": ["a.F90:1", "b.F90"], "review_rounds": 2,
              "affects_reference_models": True, "pr": None, "questions_for_andrew": "true",
              "diff_lines": {"source": 3, "tests": 4}}
    text = common.format_front_matter(fields, "\nbody\n")
    parsed, body = common.parse_front_matter(text)
    assert parsed == fields
    assert body == "\nbody\n"


def test_front_matter_rejects_garbage():
    with pytest.raises(ValueError):
        common.parse_front_matter("no front matter")
    with pytest.raises(ValueError):
        common.parse_front_matter("---\nthis is not a key value line\n---\n")


# ------------------------------------------------------------------ findings

def test_finding_lifecycle(state):
    result = run("auditState.py", "finding", "new", "--title", "Wrong exponent", "--severity", "high",
                 "--category", "physics", "--file", "source/a.F90:12", "--complexity", "S")
    identifier = result.stdout.strip()
    assert identifier == "F-0001"
    second = run("auditState.py", "finding", "new", "--title", "Other", "--severity", "low", "--category", "docs",
                 "--file", "source/a.F90:99")
    assert second.stdout.strip() == "F-0002"
    assert "F-0001 also concerns" in second.stderr
    run("auditState.py", "finding", "set", identifier, "status=fix-staged", "branch=audit/F-0001-exponent",
        'diff_lines={"source": 7, "tests": 20}', "--note", "built and tested")
    fields, body = common.load_finding(state, identifier)
    assert fields["status"] == "fix-staged"
    assert fields["diff_lines"] == {"source": 7, "tests": 20}
    assert "status: \"verified\" -> \"fix-staged\"" in body
    assert "note: built and tested" in body
    bad = run("auditState.py", "finding", "set", identifier, "status=done", check=False)
    assert bad.returncode == 2
    assert common.load_finding(state, identifier)[0]["status"] == "fix-staged"


def test_conflicted_copies_are_reported(state):
    run("auditState.py", "finding", "new", "--title", "x", "--severity", "low", "--category", "docs", "--file", "a")
    open(os.path.join(state, "findings", "F-0001 (abenson's conflicted copy 2026-11-07).md"), "w").write("x")
    findings, problems = common.list_findings(state)
    assert len(findings) == 1
    assert any("conflicted copy" in problem for problem in problems)


def test_review_order_easiest_first_and_parents_first():
    findings = [
        {"id": "F-0003", "complexity": "S", "diff_lines": {"source": 5, "tests": 0}, "depends_on": ["F-0002"]},
        {"id": "F-0002", "complexity": "M", "diff_lines": {"source": 50, "tests": 0}},
        {"id": "F-0001", "complexity": "S", "diff_lines": {"source": 10, "tests": 0}},
        {"id": "F-0004", "complexity": "S", "diff_lines": {"source": 1, "tests": 0}},
    ]
    order = [fields["id"] for fields in auditState.review_order(findings)]
    assert order == ["F-0004", "F-0001", "F-0002", "F-0003"]


def test_backlog_and_index(state):
    for number in range(3):
        identifier = run("auditState.py", "finding", "new", "--title", "t{}".format(number), "--severity", "high",
                         "--category", "crash", "--file", "f{}.F90".format(number)).stdout.strip()
        run("auditState.py", "finding", "set", identifier, "status=ready-for-review", "complexity=S")
    assert run("auditState.py", "backlog").stdout.strip() == "3"
    assert run("auditState.py", "backlog", "--max", "3", check=False).returncode == 1
    assert run("auditState.py", "backlog", "--max", "4").returncode == 0
    run("auditState.py", "index")
    index = open(os.path.join(state, "INDEX.md")).read()
    assert "3 ready-for-review" in index
    assert "[F-0001](findings/F-0001.md)" in index


# ------------------------------------------------------------------ claims

def test_claims(state):
    assert run("auditState.py", "claim", "source/a.F90", "--session", "s1").returncode == 0
    refused = run("auditState.py", "claim", "source/a.F90", "--session", "s2", check=False)
    assert refused.returncode == 1 and "held by s1" in refused.stdout
    assert run("auditState.py", "claim", "source/a.F90", "--session", "s1").returncode == 0  # renew own claim
    run("auditState.py", "release", "source/a.F90", "--session", "s1")
    assert run("auditState.py", "claim", "source/a.F90", "--session", "s2", "--lease-hours", "-1").returncode == 0
    assert run("auditState.py", "claim", "source/a.F90", "--session", "s3").returncode == 0  # expired: taken over
    assert common.active_claims(state)["source/a.F90"]["session"] == "s3"


# ------------------------------------------------------------------ coverage and ranking

def ranking(repo, *extra):
    rows = json.loads(run("prioritize.py", "--repo", repo, "--top", "100", "--json", *extra).stdout)
    return {row["path"]: row for row in rows}


def test_reference_use(repo, state):
    rows = ranking(repo)
    assert rows["source/cooling/multiplier.F90"]["R"] == 1.0        # named by a reference model
    assert rows["source/cooling/cole2000.F90"]["R"] == 1.0          # nested in it
    assert rows["source/cooling/_class.F90"]["R"] == 1.0            # its class
    assert rows["source/cooling/white_frenk.F90"]["R"] == 0.5       # class default
    assert rows["source/numerical/helper.F90"]["R"] == 0.3          # used by a direct file
    assert rows["source/objects/nodes/components/disk/simple/_class.F90"]["R"] == 1.0   # via validate_ XInclude
    assert rows["source/objects/nodes/components/disk/standard/_class.F90"]["R"] == 0.5  # default component
    assert rows["source/unused/orphan.F90"]["R"] == 0.0


def test_coverage_staleness_change_and_cooldown(repo, state):
    run("auditState.py", "coverage", "add", "--repo", repo, "--session", "s1", "--lens", "bugs",
        "source/cooling/cole2000.F90", "source/cooling/multiplier.F90")
    old = (common.now_utc() - common.datetime.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    run("auditState.py", "coverage", "add", "--repo", repo, "--session", "s1", "--lens", "bugs", "--date", old,
        "source/numerical/helper.F90")
    run("auditState.py", "coverage", "add", "--repo", repo, "--session", "s1", "--lens", "physics",
        "source/unused/orphan.F90")
    with open(os.path.join(repo, "source/cooling/multiplier.F90"), "a") as stream:
        stream.write("! changed\n")
    git(repo, "commit", "-q", "-am", "change multiplier")
    rows = ranking(repo)
    assert "source/cooling/cole2000.F90" not in rows                    # reviewed just now, unchanged
    assert rows["source/cooling/multiplier.F90"]["changed_since_review"]
    assert rows["source/cooling/multiplier.F90"]["C"] == 1.0
    assert rows["source/numerical/helper.F90"]["S"] == pytest.approx(0.5, abs=0.01)
    assert rows["source/unused/orphan.F90"]["S"] == 1.0                 # reviewed under another lens only
    assert "source/unused/orphan.F90" not in ranking(repo, "--lens", "physics")


def test_claimed_files_are_skipped_for_other_sessions(repo, state):
    run("auditState.py", "claim", "source/cooling/cole2000.F90", "--session", "other")
    assert "source/cooling/cole2000.F90" not in ranking(repo, "--session", "me")
    assert "source/cooling/cole2000.F90" in ranking(repo, "--session", "other")


def test_bulk_commits_do_not_count_as_churn(repo, state):
    rows = ranking(repo, "--bulk-files", "3")       # the initial commit touches 8 files: ignored
    assert all(row["C"] == 0.0 for row in rows.values())
    rows = ranking(repo)
    assert rows["source/cooling/cole2000.F90"]["C"] > 0.0


def test_backfill_is_a_skim(repo, state):
    run("auditState.py", "coverage", "backfill", "--repo", repo, "--commit", "HEAD", "--date",
        common.iso_now(), "--session", "backfill")
    rows = ranking(repo)
    # A skim today counts as 120 days old: still listed, staleness 120/180.
    assert rows["source/cooling/cole2000.F90"]["S"] == pytest.approx(120 / 180, abs=0.01)


# ------------------------------------------------------------------ sync

def test_sync_diff_size_and_merge(repo, state):
    git(repo, "checkout", "-q", "-b", "audit/F-0001-fix")
    with open(os.path.join(repo, "source/cooling/cole2000.F90"), "a") as stream:
        stream.write("! fix 1\n! fix 2\n")
    write(os.path.join(repo, "testSuite/test-fix.py"), "print('SUCCESS: x')\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fix")
    git(repo, "checkout", "-q", "master")
    identifier = run("auditState.py", "finding", "new", "--title", "x", "--severity", "high", "--category", "crash",
                     "--file", "source/cooling/cole2000.F90").stdout.strip()
    run("auditState.py", "finding", "set", identifier, "status=ready-for-review", "branch=audit/F-0001-fix")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge", "audit/F-0001-fix")
    result = run("auditState.py", "sync", "--repo", repo, "--base", "master")
    assert "no recorded base" in result.stdout          # can not tell merged from empty: left alone
    git(repo, "reset", "-q", "--hard", "HEAD~1")
    base = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], stdout=subprocess.PIPE,
                          universal_newlines=True).stdout.strip()
    run("auditState.py", "finding", "set", identifier, "base=" + base[:10])
    run("auditState.py", "sync", "--repo", repo, "--base", "master")
    fields, _ = common.load_finding(state, identifier)
    assert fields["diff_lines"] == {"source": 2, "tests": 1}
    assert fields["status"] == "ready-for-review"
    git(repo, "merge", "-q", "--no-ff", "-m", "merge", "audit/F-0001-fix")
    run("auditState.py", "sync", "--repo", repo, "--base", "master")
    assert common.load_finding(state, identifier)[0]["status"] == "merged"


# ------------------------------------------------------------------ usage gate

def write_usage(path, seven_used, seven_hours, five_used=10.0, five_hours=3.0, age=0.0):
    now = time.time()
    payload = {"written": now - age, "rate_limits": {
        "seven_day": {"used_percentage": seven_used, "resets_at": now + seven_hours * 3600},
        "five_hour": {"used_percentage": five_used, "resets_at": now + five_hours * 3600}}}
    with open(path, "w") as stream:
        json.dump(payload, stream)


def gate(usage, *arguments):
    result = run("usageGate.py", *arguments, env={"AUDIT_USAGE_FILE": usage}, check=False)
    return result.returncode, json.loads(result.stdout)


def test_ceiling_curve():
    class Arguments:
        reserve_min, reserve_max, reserve_horizon_hours = 5.0, 20.0, 12.0
    import usageGate
    assert usageGate.ceiling(Arguments, 24) == 80.0
    assert usageGate.ceiling(Arguments, 6) == 90.0
    assert usageGate.ceiling(Arguments, 1) == 95.0


def test_preflight(tmp_path, state):
    usage = str(tmp_path / "usage.json")
    write_usage(usage, 50, 12)
    code, decision = gate(usage, "preflight", "--require-reset-within-hours", "14")
    assert code == 0 and decision["action"] == "go" and decision["ceiling"] == 80.0
    write_usage(usage, 75, 12)
    assert gate(usage, "preflight")[0] == 3                                    # headroom 5 < 10
    write_usage(usage, 10, 40)
    assert gate(usage, "preflight", "--require-reset-within-hours", "14")[0] == 3  # reset day moved
    write_usage(usage, 10, 12, age=3600)
    assert gate(usage, "preflight")[0] == 4                                    # stale
    os.unlink(usage)
    assert gate(usage, "preflight")[0] == 4                                    # missing


def test_check_forecast_wait_and_stop(tmp_path, state):
    usage = str(tmp_path / "usage.json")
    write_usage(usage, 40, 10)
    assert gate(usage, "mark", "--session", "s", "--label", "start")[0] == 0
    code, decision = gate(usage, "check", "--session", "s")
    assert code == 0 and decision["forecast_weekly"] == pytest.approx(3.75)  # default 3 * 1.25
    # One iteration cost 10 points: the forecast is now 12.5, which would cross 100 - 20*10/12 = 83.3.
    marks = os.path.join(state, "runs", "s-usage.jsonl")
    with open(marks) as stream:
        first = json.loads(stream.readline())
    later = dict(first, t=first["t"] + 600, seven_used=50.0, label="F-0001")
    with open(marks, "a") as stream:
        stream.write(json.dumps(later) + "\n")
    write_usage(usage, 72, 10)
    code, decision = gate(usage, "check", "--session", "s")
    assert code == 3 and "weekly ceiling" in decision["reason"]
    # Plenty of weekly room, but the five-hour window is nearly full (85% + at least the weekly
    # forecast of 12.5% > 90%): wait for its reset.
    write_usage(usage, 20, 10, five_used=85, five_hours=1)
    code, decision = gate(usage, "check", "--session", "s")
    assert code == 10 and decision["action"] == "wait"
    # ... unless the five-hour reset is too close to the deadline.
    code, decision = gate(usage, "--deadline", str(time.time() + 3600), "check", "--session", "s")
    assert code == 3


def test_segment_start_marks_are_not_iterations(tmp_path, state):
    import usageGate

    class Arguments:
        default_cost, cost_safety, default_duration_minutes = 3.0, 1.0, 60.0
    marks = [{"t": 0, "label": "start", "seven_used": 10, "seven_reset": 1e9, "five_used": 5, "five_reset": 1},
             {"t": 600, "label": "F-1", "seven_used": 12, "seven_reset": 1e9, "five_used": 9, "five_reset": 1},
             {"t": 20000, "label": "start", "seven_used": 13, "seven_reset": 1e9, "five_used": 0, "five_reset": 2}]
    weekly, hourly, duration = usageGate.forecast(Arguments, marks)
    assert (weekly, hourly, duration) == (2, 4, 600)
    # The five-hour forecast is never below the weekly one.
    marks[1]["five_used"] = 5
    assert usageGate.forecast(Arguments, marks)[1] == 2


def test_statusline_records_usage(tmp_path):
    usage = str(tmp_path / "cache" / "usage.json")
    payload = {"session_id": "abc", "rate_limits": {"seven_day": {"used_percentage": 42.0, "resets_at": 1},
                                                    "five_hour": {"used_percentage": 7.0, "resets_at": 2}}}
    environment = dict(os.environ, AUDIT_USAGE_FILE=usage)
    environment.pop("AUDIT_STATUSLINE_NEXT", None)
    result = subprocess.run([sys.executable, os.path.join(TOOLS, "statuslineUsage.py")], input=json.dumps(payload),
                            env=environment, stdout=subprocess.PIPE, universal_newlines=True, check=True)
    assert result.stdout.strip() == "7d 42% · 5h 7%"
    assert json.load(open(usage))["rate_limits"]["seven_day"]["used_percentage"] == 42.0
    # A payload without rate_limits keeps the previous reading.
    subprocess.run([sys.executable, os.path.join(TOOLS, "statuslineUsage.py")], input=json.dumps({"model": {}}),
                   env=environment, stdout=subprocess.PIPE, universal_newlines=True, check=True)
    assert json.load(open(usage))["session_id"] == "abc"


# ------------------------------------------------------------------ regressions from review

def test_empty_branch_is_not_merged(repo, state):
    base = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], stdout=subprocess.PIPE,
                          universal_newlines=True).stdout.strip()
    git(repo, "branch", "audit/F-0001-abandoned")
    identifier = run("auditState.py", "finding", "new", "--title", "x", "--severity", "high", "--category", "crash",
                     "--file", "a").stdout.strip()
    run("auditState.py", "finding", "set", identifier, "branch=audit/F-0001-abandoned", "base=" + base[:10])
    run("auditState.py", "sync", "--repo", repo, "--base", "master")
    assert common.load_finding(state, identifier)[0]["status"] == "verified"


def test_conflicting_branch_is_reported(repo, state):
    git(repo, "checkout", "-q", "-b", "audit/F-0001-conflict")
    write(os.path.join(repo, "source/unused/orphan.F90"), "branch\n")
    git(repo, "commit", "-q", "-am", "branch side")
    git(repo, "checkout", "-q", "master")
    write(os.path.join(repo, "source/unused/orphan.F90"), "master\n")
    git(repo, "commit", "-q", "-am", "master side")
    assert auditState.merges_cleanly(repo, "master", "audit/F-0001-conflict") is False
    assert auditState.merges_cleanly(repo, "master", "master") is True


def test_set_keeps_strings_and_lists(state):
    identifier = run("auditState.py", "finding", "new", "--title", "x", "--severity", "low", "--category", "docs",
                     "--file", "a").stdout.strip()
    run("auditState.py", "finding", "set", identifier, "base=1234567890", "head=0012345678", "depends_on=F-0002",
        "pr=1730")
    fields, _ = common.load_finding(state, identifier)
    assert fields["base"] == "1234567890" and fields["head"] == "0012345678"
    assert fields["depends_on"] == ["F-0002"]
    assert fields["pr"] == 1730
    run("auditState.py", "finding", "set", identifier, "depends_on=F-0002,F-0003")
    assert common.load_finding(state, identifier)[0]["depends_on"] == ["F-0002", "F-0003"]


def test_corrupt_claim_does_not_block(state):
    path = common.claim_path(state, "source/a.F90")
    open(path, "w").write("{not json")
    assert run("auditState.py", "claim", "source/a.F90", "--session", "s1").returncode == 0
    open(path, "w").write("{not json")
    run("auditState.py", "release", "source/a.F90", "--session", "s1")
    assert not os.path.exists(path)


def test_single_file_components_and_includes(repo, state):
    write(os.path.join(repo, "source/objects/nodes/components/satellite/orbiting.F90"), """\
        !![
        <component>
         <class>satellite</class>
         <name>orbiting</name>
         <functions>objects.nodes.components.satellite.orbiting.bound_functions.inc</functions>
        </component>
        !!]
        include 'objects/nodes/components/satellite/shared.inc'
        """)
    write(os.path.join(repo, "source/objects/nodes/components/satellite/merge_time.F90"), """\
        !![
        <component>
         <class>satellite</class>
         <name>mergeTime</name>
        </component>
        !!]
        """)
    write(os.path.join(repo, "source/objects/nodes/components/satellite/shared.Inc"), "! shared\n")
    write(os.path.join(repo, "source/objects.nodes.components.satellite.orbiting.bound_functions.Inc"), "! b\n")
    write(os.path.join(repo, "testSuite/parameters/validate_satellites.xml"),
          "<parameters><componentSatellite value=\"orbiting\"/></parameters>\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "satellites")
    rows = ranking(repo)
    assert rows["source/objects/nodes/components/satellite/orbiting.F90"]["R"] == 1.0
    assert rows["source/objects/nodes/components/satellite/merge_time.F90"]["R"] == 0.0
    assert rows["source/objects/nodes/components/satellite/shared.Inc"]["R"] == 1.0
    assert rows["source/objects.nodes.components.satellite.orbiting.bound_functions.Inc"]["R"] == 1.0


def test_statusline_ignores_readings_without_a_weekly_window(tmp_path):
    usage = "usage.json"   # relative: written in the working directory
    environment = dict(os.environ, AUDIT_USAGE_FILE=usage)
    environment.pop("AUDIT_STATUSLINE_NEXT", None)
    good = {"rate_limits": {"seven_day": {"used_percentage": 1.0, "resets_at": 1}}}
    partial = {"rate_limits": {"five_hour": {"used_percentage": 2.0, "resets_at": 2}}}
    for payload in (good, partial):
        subprocess.run([sys.executable, os.path.join(TOOLS, "statuslineUsage.py")], input=json.dumps(payload),
                       env=environment, cwd=str(tmp_path), stdout=subprocess.PIPE, universal_newlines=True,
                       check=True)
    assert "seven_day" in json.load(open(str(tmp_path / usage)))["rate_limits"]


def test_statusline_debug_saves_raw_input(tmp_path):
    usage = str(tmp_path / "cache" / "usage.json")
    environment = dict(os.environ, AUDIT_USAGE_FILE=usage, AUDIT_STATUSLINE_DEBUG="1")
    environment.pop("AUDIT_STATUSLINE_NEXT", None)
    subprocess.run([sys.executable, os.path.join(TOOLS, "statuslineUsage.py")], input='{"model": {}}',
                   env=environment, stdout=subprocess.PIPE, universal_newlines=True, check=True)
    saved = json.load(open(str(tmp_path / "cache" / "last-input.json")))
    assert saved["stdin"] == '{"model": {}}'
    assert not os.path.exists(usage)
