#!/usr/bin/env python3
"""Manage the shared state of the Galacticus audit loop: findings, coverage,
claims, and the generated review index.

    auditState.py init
    auditState.py finding new --title T --severity S --category C --file F [--file F ...] [--body-file B]
    auditState.py finding set F-0123 status=fix-staged branch=audit/F-0123-x [--note "..."]
    auditState.py finding show F-0123
    auditState.py finding list [--status S ...] [--json]
    auditState.py claim PATH ... --session ID [--lease-hours 6]
    auditState.py release PATH ... --session ID
    auditState.py claims
    auditState.py coverage add --repo R --session ID --lens L --depth D PATH ... [--finding F-0123 ...]
    auditState.py coverage backfill --repo R --commit C --date D --session ID [--lens L] [--depth skim] [--prefix source/]
    auditState.py backlog [--max N]
    auditState.py sync --repo R [--base origin/master] [--gh]
    auditState.py index

The state directory is `$AUDIT_STATE_DIR`, or `~/Dropbox/AI/audit`; `--state`
overrides both. See ReadMe.md for the file formats.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auditCommon as common  # noqa: E402

# Fields always stored as strings, and fields always stored as lists (`key=a,b` or JSON).
STRING_FIELDS = {"title", "branch", "base", "head", "found_by", "questions_for_andrew"}
LIST_FIELDS = {"files", "depends_on"}

ENUMERATIONS = {
    "status": common.STATUSES,
    "severity": common.SEVERITIES,
    "confidence": common.CONFIDENCES,
    "complexity": common.COMPLEXITIES,
    "category": common.CATEGORIES,
}


def fail(message):
    print("auditState: " + message, file=sys.stderr)
    sys.exit(2)


def check_enumerations(fields):
    for key, allowed in ENUMERATIONS.items():
        if key in fields and fields[key] is not None and fields[key] not in allowed:
            fail("{}={!r} is not one of: {}".format(key, fields[key], ", ".join(allowed)))


def add_history(body, line):
    """Append a line to the finding's '## History' section (created at the end if missing)."""
    entry = "- {} {}".format(common.iso_now(), line)
    if "\n## History\n" in "\n" + body:
        return body.rstrip("\n") + "\n" + entry + "\n"
    return body.rstrip("\n") + "\n\n## History\n\n" + entry + "\n"


# ------------------------------------------------------------------ commands

def command_init(arguments):
    root = common.state_dir(arguments.state)
    common.ensure_layout(root)
    print(root)


def command_finding_new(arguments):
    root = common.state_dir(arguments.state)
    common.ensure_layout(root)
    if arguments.body_file == "-":
        body = sys.stdin.read()
    elif arguments.body_file:
        with open(arguments.body_file) as stream:
            body = stream.read()
    else:
        body = "## Problem\n\n## Evidence\n\n## Fix and tests\n\n## Review\n"
    fields = {
        "title": arguments.title,
        "status": arguments.status,
        "severity": arguments.severity,
        "confidence": arguments.confidence,
        "complexity": arguments.complexity,
        "category": arguments.category,
        "files": arguments.file,
        "affects_reference_models": arguments.affects_reference_models,
        "found_by": arguments.found_by,
        "review_rounds": 0,
    }
    fields = {key: value for key, value in fields.items() if value is not None}
    check_enumerations(fields)
    duplicates = possible_duplicates(root, arguments.file)
    identifier = common.create_finding_file(root, fields, "\n" + body.lstrip("\n"))
    fields, body = common.load_finding(root, identifier)
    common.save_finding(root, fields, add_history(body, "created (status: {})".format(fields["status"])))
    print(identifier)
    for other in duplicates:
        print("note: {} also concerns {} ({}: {})".format(other["id"], ", ".join(other["files"]),
                                                          other.get("status"), other.get("title")), file=sys.stderr)


def possible_duplicates(root, files):
    """Open findings that name any of the same files (ignoring line numbers)."""
    wanted = {entry.split(":")[0] for entry in files or []}
    findings, _ = common.list_findings(root)
    matches = []
    for fields, _ in findings:
        if fields.get("status") not in common.OPEN_STATUSES:
            continue
        theirs = {entry.split(":")[0] for entry in fields.get("files") or []}
        if wanted & theirs:
            matches.append(fields)
    return matches


def command_finding_set(arguments):
    root = common.state_dir(arguments.state)
    try:
        fields, body = common.load_finding(root, arguments.id)
    except OSError:
        fail("no such finding: " + arguments.id)
    changes = []
    for assignment in arguments.assignments:
        key, separator, raw = assignment.partition("=")
        if not separator or not key:
            fail("expected key=value, got " + repr(assignment))
        if key in ("id", "created", "updated"):
            fail("{} can not be set".format(key))
        if key in STRING_FIELDS and not raw.startswith('"'):
            value = raw if raw != "" else None   # never JSON: a SHA of digits must stay a string
        else:
            value = common._parse_value(raw)
        if key in LIST_FIELDS and value is not None and not isinstance(value, list):
            value = [entry for entry in str(value).split(",") if entry]
        old = fields.get(key)
        fields[key] = value
        if old != value:
            changes.append("{}: {} -> {}".format(key, json.dumps(old), json.dumps(value)))
    check_enumerations(fields)
    if arguments.note:
        changes.append("note: " + arguments.note)
    if not changes:
        return
    common.save_finding(root, fields, add_history(body, "; ".join(changes)))


def command_finding_show(arguments):
    root = common.state_dir(arguments.state)
    try:
        with open(common.finding_path(root, arguments.id)) as stream:
            sys.stdout.write(stream.read())
    except OSError:
        fail("no such finding: " + arguments.id)


def command_finding_list(arguments):
    root = common.state_dir(arguments.state)
    findings, problems = common.list_findings(root)
    selected = [fields for fields, _ in findings if not arguments.status or fields.get("status") in arguments.status]
    if arguments.json:
        print(json.dumps(selected, indent=1))
    else:
        for fields in selected:
            print("{id}  {status:<16} {severity:<8} {complexity}  {title}".format(
                id=fields.get("id"), status=str(fields.get("status")), severity=str(fields.get("severity")),
                complexity=fields.get("complexity") or "-", title=fields.get("title")))
    for problem in problems:
        print("warning: " + problem, file=sys.stderr)


def command_claim(arguments):
    root = common.state_dir(arguments.state)
    common.ensure_layout(root)
    now = common.now_utc()
    expires = now + common.datetime.timedelta(hours=arguments.lease_hours)
    refused = []
    for path in arguments.paths:
        existing = common.read_claim(root, path)
        if existing is None and os.path.exists(common.claim_path(root, path)):
            existing = {"corrupt": True}  # unreadable: treat as expired and overwrite
        if existing and not common.claim_expired(existing, now) and existing.get("session") != arguments.session:
            refused.append("{} (held by {} until {})".format(path, existing.get("session"), existing.get("expires")))
            continue
        claim = {"path": path, "session": arguments.session, "claimed": common.iso_now(),
                 "expires": expires.strftime("%Y-%m-%dT%H:%M:%SZ")}
        target = common.claim_path(root, path)
        if existing is None:
            # Exclusive create closes the race between two sessions on one machine.
            try:
                handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                refused.append("{} (claimed concurrently)".format(path))
                continue
            with os.fdopen(handle, "w") as stream:
                json.dump(claim, stream)
        else:
            common.atomic_write(target, json.dumps(claim))
    for line in refused:
        print("refused: " + line)
    sys.exit(1 if refused else 0)


def command_release(arguments):
    root = common.state_dir(arguments.state)
    for path in arguments.paths:
        existing = common.read_claim(root, path)
        if existing is None:
            if os.path.exists(common.claim_path(root, path)):
                os.unlink(common.claim_path(root, path))  # unreadable claim
            continue
        if existing.get("session") != arguments.session and not arguments.force:
            print("not released (held by {}): {}".format(existing.get("session"), path))
            continue
        os.unlink(common.claim_path(root, path))


def command_claims(arguments):
    root = common.state_dir(arguments.state)
    for path, claim in sorted(common.active_claims(root).items()):
        print("{}  {}  until {}".format(path, claim.get("session"), claim.get("expires")))


def command_coverage_add(arguments):
    root = common.state_dir(arguments.state)
    common.ensure_layout(root)
    if arguments.lens not in common.LENSES:
        fail("lens must be one of: " + ", ".join(common.LENSES))
    if arguments.depth not in common.DEPTHS:
        fail("depth must be one of: " + ", ".join(common.DEPTHS))
    commit = common.git(arguments.repo, "rev-parse", arguments.commit).stdout.strip()
    hashes = common.blob_hashes(arguments.repo, commit, arguments.paths)
    missing = [path for path in arguments.paths if path not in hashes]
    if missing:
        fail("not files at {}: {}".format(commit[:10], ", ".join(missing)))
    output = os.path.join(root, "coverage", arguments.session + ".jsonl")
    date = arguments.date or common.iso_now()
    for path in arguments.paths:
        record = {"path": path, "blob": hashes[path], "commit": commit[:12], "lens": arguments.lens,
                  "depth": arguments.depth, "date": date, "session": arguments.session,
                  "findings": arguments.finding or []}
        common.append_line(output, json.dumps(record, sort_keys=True))
    print("recorded {} file(s) in {}".format(len(arguments.paths), output))


def command_coverage_backfill(arguments):
    """Record every file under a prefix at a past commit as reviewed: used to
    give credit for an earlier sweep (normally as a skim)."""
    root = common.state_dir(arguments.state)
    common.ensure_layout(root)
    commit = common.git(arguments.repo, "rev-parse", arguments.commit).stdout.strip()
    hashes = common.blob_hashes(arguments.repo, commit)
    output = os.path.join(root, "coverage", arguments.session + ".jsonl")
    count = 0
    for path, blob in sorted(hashes.items()):
        if not path.startswith(arguments.prefix) or not path.endswith((".F90", ".Inc", ".py", ".c", ".cpp", ".h")):
            continue
        record = {"path": path, "blob": blob, "commit": commit[:12], "lens": arguments.lens,
                  "depth": arguments.depth, "date": arguments.date, "session": arguments.session,
                  "findings": [], "backfill": True}
        common.append_line(output, json.dumps(record, sort_keys=True))
        count += 1
    print("backfilled {} file(s) into {}".format(count, output))


def backlog_count(root):
    findings, _ = common.list_findings(root)
    return sum(1 for fields, _ in findings if fields.get("status") in common.BACKLOG_STATUSES)


def command_backlog(arguments):
    root = common.state_dir(arguments.state)
    count = backlog_count(root)
    print(count)
    if arguments.max is not None and count >= arguments.max:
        sys.exit(1)


# ------------------------------------------------------------------ sync

TEST_PREFIXES = ("testSuite/", "source/tests/")


def diff_lines(repo, base, head):
    """Changed lines (added + deleted) in source and test files between the merge-base and head."""
    merge_base = common.git(repo, "merge-base", base, head).stdout.strip()
    counts = {"source": 0, "tests": 0}
    for line in common.git(repo, "diff", "--numstat", merge_base, head).stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or parts[0] == "-":
            continue
        changed = int(parts[0]) + int(parts[1])
        counts["tests" if parts[2].startswith(TEST_PREFIXES) else "source"] += changed
    return counts


def merges_cleanly(repo, base, head):
    """True/False, or None if this git has no `merge-tree --write-tree` (git < 2.38)."""
    result = common.git(repo, "merge-tree", "--write-tree", base, head, check=False)
    if result.returncode in (0, 1) and "usage:" not in result.stderr:
        return result.returncode == 0
    return None


def is_merged(repo, base, head, fork=None):
    """True if the branch's commits are on `base`. A branch with no commits of its own (a fix
    abandoned before its first commit) is not merged: that needs the fork point (`fork`, the
    finding's recorded base commit) to tell apart from a merged branch."""
    if fork:
        resolved = common.git(repo, "rev-parse", "--verify", "--quiet", fork + "^{commit}", check=False)
        if resolved.returncode == 0:
            own = common.git(repo, "rev-list", "--count", resolved.stdout.strip() + ".." + head, check=False)
            if own.returncode == 0 and own.stdout.strip() == "0":
                return False
            if common.git(repo, "merge-base", "--is-ancestor", head, base, check=False).returncode == 0:
                return True
    cherry = common.git(repo, "cherry", base, head, check=False).stdout.split()
    return bool(cherry) and all(mark == "-" for mark in cherry[0::2])


def pull_request(branch, repository):
    if shutil.which("gh") is None:
        return None
    result = subprocess.run(["gh", "pr", "list", "--repo", repository, "--head", branch, "--state", "all",
                             "--json", "number,state", "--limit", "1"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode != 0:
        return None
    entries = json.loads(result.stdout or "[]")
    return entries[0] if entries else None


def command_sync(arguments):
    root = common.state_dir(arguments.state)
    findings, problems = common.list_findings(root)
    for problem in problems:
        print("warning: " + problem)
    for fields, body in findings:
        branch = fields.get("branch")
        if not branch or fields.get("status") in ("merged", "rejected", "superseded"):
            continue
        changes = []
        exists = common.git(arguments.repo, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch, check=False)
        if exists.returncode != 0:
            print("{}: branch {} not found in {}".format(fields["id"], branch, arguments.repo))
            continue
        head = exists.stdout.strip()[:10]
        if fields.get("head") != head:
            changes.append(("head", head))
        counts = diff_lines(arguments.repo, arguments.base, branch)
        if fields.get("diff_lines") != counts:
            changes.append(("diff_lines", counts))
        if not fields.get("base"):
            print("{}: no recorded base, so a merge can not be told from an empty branch: "
                  "set base=<fork commit>".format(fields["id"]))
        if is_merged(arguments.repo, arguments.base, branch, fields.get("base")):
            changes.append(("status", "merged"))
        else:
            clean = merges_cleanly(arguments.repo, arguments.base, branch)
            if clean is False:
                print("{}: {} no longer merges cleanly onto {}".format(fields["id"], branch, arguments.base))
            if arguments.gh:
                entry = pull_request(branch, arguments.repository)
                if entry:
                    if fields.get("pr") != entry["number"]:
                        changes.append(("pr", entry["number"]))
                    if entry["state"] == "MERGED":
                        changes.append(("status", "merged"))
                    elif entry["state"] == "OPEN" and fields.get("status") in ("ready-for-review", "accepted"):
                        changes.append(("status", "pr-open"))
        changes = [(key, value) for key, value in changes if fields.get(key) != value]
        if not changes:
            continue
        description = "; ".join("{}: {} -> {}".format(key, json.dumps(fields.get(key)), json.dumps(value))
                                for key, value in changes)
        for key, value in changes:
            fields[key] = value
        common.save_finding(root, fields, add_history(body, "sync: " + description))
        print("{}: {}".format(fields["id"], description))


# ------------------------------------------------------------------ index

SEVERITY_RANK = {name: rank for rank, name in enumerate(common.SEVERITIES)}
COMPLEXITY_RANK = {name: rank for rank, name in enumerate(common.COMPLEXITIES)}


def review_order(findings):
    """Easiest first (complexity, then source diff size, then test diff size),
    with any finding placed after the findings it depends on."""
    def key(fields):
        counts = fields.get("diff_lines") or {}
        return (COMPLEXITY_RANK.get(fields.get("complexity"), 9), counts.get("source", 10**6),
                counts.get("tests", 10**6), fields.get("id"))
    ordered = sorted(findings, key=key)
    identifiers = {fields["id"] for fields in ordered}
    placed = []
    done = set()
    pending = list(ordered)
    while pending:
        progressed = False
        for fields in list(pending):
            parents = [parent for parent in fields.get("depends_on") or [] if parent in identifiers]
            if all(parent in done for parent in parents):
                placed.append(fields)
                done.add(fields["id"])
                pending.remove(fields)
                progressed = True
                break
        if not progressed:  # a dependency cycle: emit the rest as they are
            placed.extend(pending)
            break
    return placed


def cell(value):
    if value is None or value == "":
        return "-"
    if isinstance(value, list):
        value = ", ".join(str(entry) for entry in value)
    if isinstance(value, dict):
        value = json.dumps(value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def size(fields):
    counts = fields.get("diff_lines")
    if not counts:
        return "-"
    return "{}/{}".format(counts.get("source", "?"), counts.get("tests", "?"))


def command_index(arguments):
    root = common.state_dir(arguments.state)
    findings, problems = common.list_findings(root)
    by_status = {}
    for fields, _ in findings:
        by_status.setdefault(fields.get("status"), []).append(fields)
    lines = ["# Audit index", "",
             "*Generated by `auditState.py index` at {}. Do not edit: edit the finding files.*".format(common.iso_now()),
             ""]
    counts = ", ".join("{} {}".format(len(by_status[status]), status) for status in common.STATUSES
                       if by_status.get(status))
    lines += ["**Totals:** " + (counts or "no findings"), ""]
    claims = common.active_claims(root)
    if claims:
        lines += ["**Being audited now:** " + ", ".join("`{}` ({})".format(path, claim.get("session"))
                                                       for path, claim in sorted(claims.items())), ""]
    if problems:
        lines += ["## Problems in the state directory", ""] + ["- " + problem for problem in problems] + [""]

    queue = review_order(by_status.get("ready-for-review", []))
    lines += ["## Ready for Andrew (review order: easiest first, stacked branches after their parents)", "",
              "| # | Finding | Severity | Size (src/tests) | Branch @ head | Depends on | Questions |",
              "|---|---|---|---|---|---|---|"]
    for number, fields in enumerate(queue, start=1):
        lines.append("| {} | [{}](findings/{}.md) {} | {} | {} | `{}` @ `{}` | {} | {} |".format(
            number, fields["id"], fields["id"], cell(fields.get("title")), cell(fields.get("severity")),
            size(fields), cell(fields.get("branch")), cell(fields.get("head")), cell(fields.get("depends_on")),
            cell(fields.get("questions_for_andrew"))))
    lines.append("")

    sections = [
        ("Parked: need Andrew's decision", ["parked"]),
        ("Accepted / PR open", ["accepted", "pr-open"]),
        ("In progress (staged or in peer review)", ["fix-staged", "in-peer-review"]),
        ("Verified, no fix staged", ["verified"]),
    ]
    for title, statuses in sections:
        selected = [fields for status in statuses for fields in by_status.get(status, [])]
        selected.sort(key=lambda fields: (SEVERITY_RANK.get(fields.get("severity"), 9), fields["id"]))
        lines += ["## " + title, "", "| Finding | Status | Severity | Files | Branch | PR | Questions |",
                  "|---|---|---|---|---|---|---|"]
        for fields in selected:
            lines.append("| [{}](findings/{}.md) {} | {} | {} | {} | {} | {} | {} |".format(
                fields["id"], fields["id"], cell(fields.get("title")), cell(fields.get("status")),
                cell(fields.get("severity")), cell(fields.get("files")), cell(fields.get("branch")),
                cell(fields.get("pr")), cell(fields.get("questions_for_andrew"))))
        lines.append("")

    closed = [fields for status in ("merged", "rejected", "superseded") for fields in by_status.get(status, [])]
    closed.sort(key=lambda fields: fields.get("updated", ""), reverse=True)
    lines += ["## Recently closed (latest 30)", ""]
    for fields in closed[:30]:
        lines.append("- [{}](findings/{}.md) {}: {}{}".format(
            fields["id"], fields["id"], fields.get("status"), fields.get("title"),
            " (PR #{})".format(fields["pr"]) if fields.get("pr") else ""))
    lines.append("")
    common.atomic_write(os.path.join(root, "INDEX.md"), "\n".join(lines))
    print(os.path.join(root, "INDEX.md"))


# ------------------------------------------------------------------ CLI

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state", help="state directory (default $AUDIT_STATE_DIR or ~/Dropbox/AI/audit)")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init").set_defaults(function=command_init)

    finding = commands.add_parser("finding").add_subparsers(dest="subcommand", required=True)
    new = finding.add_parser("new")
    new.add_argument("--title", required=True)
    new.add_argument("--severity", required=True, choices=common.SEVERITIES)
    new.add_argument("--category", required=True, choices=common.CATEGORIES)
    new.add_argument("--file", action="append", required=True, help="path[:line]; repeat for several")
    new.add_argument("--confidence", default="confirmed", choices=common.CONFIDENCES)
    new.add_argument("--complexity", choices=common.COMPLEXITIES)
    new.add_argument("--status", default="verified", choices=common.STATUSES)
    new.add_argument("--affects-reference-models", type=lambda text: text.lower() in ("1", "true", "yes"))
    new.add_argument("--found-by")
    new.add_argument("--body-file", help="Markdown body ('-' for stdin)")
    new.set_defaults(function=command_finding_new)
    update = finding.add_parser("set")
    update.add_argument("id")
    update.add_argument("assignments", nargs="*", metavar="key=value")
    update.add_argument("--note")
    update.set_defaults(function=command_finding_set)
    show = finding.add_parser("show")
    show.add_argument("id")
    show.set_defaults(function=command_finding_show)
    listing = finding.add_parser("list")
    listing.add_argument("--status", action="append", choices=common.STATUSES)
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(function=command_finding_list)

    claim = commands.add_parser("claim")
    claim.add_argument("paths", nargs="+")
    claim.add_argument("--session", required=True)
    claim.add_argument("--lease-hours", type=float, default=6.0)
    claim.set_defaults(function=command_claim)
    release = commands.add_parser("release")
    release.add_argument("paths", nargs="+")
    release.add_argument("--session", required=True)
    release.add_argument("--force", action="store_true")
    release.set_defaults(function=command_release)
    commands.add_parser("claims").set_defaults(function=command_claims)

    coverage = commands.add_parser("coverage").add_subparsers(dest="subcommand", required=True)
    add = coverage.add_parser("add")
    add.add_argument("paths", nargs="+", help="repository-relative paths")
    add.add_argument("--repo", required=True, help="Galacticus checkout (or worktree) the review read")
    add.add_argument("--commit", default="HEAD", help="commit the review read (default HEAD of --repo)")
    add.add_argument("--session", required=True)
    add.add_argument("--lens", required=True)
    add.add_argument("--depth", default="full")
    add.add_argument("--date")
    add.add_argument("--finding", action="append")
    add.set_defaults(function=command_coverage_add)
    backfill = coverage.add_parser("backfill")
    backfill.add_argument("--repo", required=True)
    backfill.add_argument("--commit", required=True)
    backfill.add_argument("--date", required=True)
    backfill.add_argument("--session", required=True)
    backfill.add_argument("--lens", default="bugs", choices=common.LENSES)
    backfill.add_argument("--depth", default="skim", choices=common.DEPTHS)
    backfill.add_argument("--prefix", default="source/")
    backfill.set_defaults(function=command_coverage_backfill)

    backlog = commands.add_parser("backlog")
    backlog.add_argument("--max", type=int, help="exit 1 if the backlog is at least this")
    backlog.set_defaults(function=command_backlog)

    sync = commands.add_parser("sync")
    sync.add_argument("--repo", required=True, help="the checkout holding the local audit branches")
    sync.add_argument("--base", default="origin/master")
    sync.add_argument("--gh", action="store_true", help="also look up PRs with the gh CLI")
    sync.add_argument("--repository", default="galacticusorg/galacticus")
    sync.set_defaults(function=command_sync)

    commands.add_parser("index").set_defaults(function=command_index)

    arguments = parser.parse_args(argv)
    arguments.function(arguments)


if __name__ == "__main__":
    main()
