#!/usr/bin/env python3
"""Import the items of an audit PLAN.md (the 2026-10-21 overnight-audit plan) as findings.

    importPlan.py PLAN.md --repo <galacticus checkout> [--open-pr N ...] [--gh] [--pr-files FILE.json]
                  [--preview OUT.md] [--write]

Without --write nothing is written: the import is printed as a table (and, with
--preview, written to a Markdown file for review). With --write the findings
are created in the state directory (`$AUDIT_STATE_DIR`, or `--state`).

Each checkbox line `- [mark] **ID** text — taken: … — done: …` becomes one finding:

  status      [ ] / [~]: `parked` if the line asks for Andrew's decision ("Andrew's
              call", "for Andrew", "— waiting:"), else `verified`.
              [x]: `pr-open` if the item belongs to an open PR (named on the line,
              or in the plan's PR table, or given with --open-pr / --gh), else `merged`.
              [-]: `rejected`.
  severity    from the section: High → high, Medium → medium, Minor (physics) → low,
              Minor / latent → latent if the line says "latent", else low,
              Documentation → low, Phase 1 → medium.
  confidence  `plausible` if the line says *not run*, *not re-checked* or "code path only".
  category    docs in the Documentation section, physics for P* items, else inferred
              from the text (threading, crash, wrong-result), marked as inferred.
  files       the backticked source paths in the item's description (the text before the
              first " — "), resolved against --repo (adding `source/`, or matching a unique
              basename).
  pr_files    for pr-open items, the files the PR changes (--gh, or --pr-files mapping PR
              numbers to file lists), so that prioritize.py can leave them alone.

The original line is kept in the body, and `plan_id` records the item's ID. Items already
imported (same `plan_id`) are skipped, so the import can be repeated while PLAN.md is still
in use. Phase 3 items (unfinished audit work, not findings) are skipped.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auditCommon as common  # noqa: E402

ITEM = re.compile(r"^\s*- \[(?P<mark>[ x~\-])\] \*\*(?P<id>[^*]+)\*\*\s*(?P<rest>.*)$")
SECTION = re.compile(r"^(#{2,3})\s+(.*)$")
PATH_TOKEN = re.compile(r"`([^`\s:]+\.(?:F90|Inc|inc|py|xml|cpp|c|h))(?::[^`]*)?`")
COMMIT = re.compile(r"`([0-9a-f]{10,40})`")
PR_NUMBER = re.compile(r"(?:PRs?\s+)?#(\d{3,5})")
DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
PARKED = re.compile(r"Andrew's call|for Andrew|— waiting:", re.I)
PLAUSIBLE = re.compile(r"\*not run\*|\*not re-checked\*|code path only", re.I)


def section_severity(section, text):
    name = section.lower()
    if name.startswith("high"):
        return "high"
    if name.startswith("medium"):
        return "medium"
    if name.startswith("minor / latent") or name.startswith("minor/latent"):
        return "latent" if re.search(r"\blatent\b", text, re.I) else "low"
    if name.startswith("minor"):
        return "low"
    if name.startswith("documentation"):
        return "low"
    return "medium"


def infer_category(identifier, section, text):
    # Sessions appended unrelated N- items to the Documentation section, so trust the
    # section only for documentation IDs.
    if identifier.startswith(("D-", "PD-")):
        return "docs", False
    if re.match(r"^P[EG]?\d|^P\d", identifier):
        return "physics", False
    lowered = text.lower()
    if re.search(r"\bthread|openmp|\brac(e|es|y)\b|deadlock|critical section|threadprivate", lowered):
        return "threading", True
    if re.search(r"\babort|segfault|\bcrash|\bhangs?\b|\bfpe\b|heap corruption|free\(\)", lowered):
        return "crash", True
    if section.lower().startswith("documentation") and re.search(r"\bdoc|docstring|description", lowered):
        return "docs", True
    if re.search(r"\blatent\b", lowered):
        return "latent", True
    return "wrong-result", True


def expand_ids(text):
    """IDs named in a PR-table item cell, expanding ranges such as P24–P27 and R1554-2–4."""
    identifiers = set()
    for token in re.split(r"[+,()\s]+", text):
        token = token.strip()
        # P24–P27, PG3-22–PG3-24, R1554-2–4 (always an en dash: PG3-5 is one ID): the prefix may or
        # may not be repeated after the dash.
        range_match = re.fullmatch(r"([A-Z][A-Za-z]*(?:\d+-)?)(\d+)–(?:\1)?(\d+)", token)
        if range_match and int(range_match.group(3)) > int(range_match.group(2)):
            prefix, low, high = range_match.group(1), int(range_match.group(2)), int(range_match.group(3))
            identifiers |= {"{}{}".format(prefix, number) for number in range(low, high + 1)}
            identifiers.add(token)
            continue
        if re.fullmatch(r"[A-Z][A-Za-z0-9-]*", token):
            identifiers.add(token)
    return identifiers


def parse_pr_table(lines):
    """Map item ID -> list of (PR number, status text, branch) from the plan's PR table."""
    mapping = {}
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5 or not cells[3].startswith("#"):
            continue
        number = int(cells[3].lstrip("#"))
        branch = re.search(r"`([^`@]+?)\s*(?:@|`)", cells[2])
        for identifier in expand_ids(cells[1]):
            mapping.setdefault(identifier, []).append((number, cells[4], branch.group(1).strip() if branch else None))
    return mapping


def item_ids(identifier):
    """The IDs an item heading covers, e.g. 'P29–P31+P36' -> P29, P30, P31, P36."""
    return expand_ids(identifier) | {identifier}


def resolve_path(token, repo, tracked):
    token = token.split(":")[0]
    # A generated file names its source: work/build/x/y.p.F90 -> source/x/y.F90.
    token = re.sub(r"^work/build/", "source/", token)
    token = re.sub(r"\.p\.F90$", ".F90", token)
    if repo is None:
        return token, True
    for candidate in (token, "source/" + token):
        if candidate in tracked:
            return candidate, True
    matches = [path for path in tracked if os.path.basename(path) == os.path.basename(token)
               and path.endswith(token)]
    if len(matches) == 1:
        return matches[0], True
    matches = [path for path in tracked if os.path.basename(path).lower() == os.path.basename(token).lower()]
    if len(matches) == 1:
        return matches[0], True
    return token, False


def commit_files(repo, hashes):
    """Source files (not tests) changed by the cited commits that exist in `repo`. A merge
    commit counts as its diff against the first parent."""
    files = []
    for commit in hashes:
        exists = common.git(repo, "rev-parse", "--verify", "--quiet", commit + "^{commit}", check=False)
        if exists.returncode != 0:
            continue
        full = exists.stdout.strip()
        parents = common.git(repo, "rev-list", "--parents", "-n", "1", full).stdout.split()
        if len(parents) > 2:
            # Only a merge into master (a PR's merge commit) says what the fix changed; a merge of
            # master into a branch would bring in everything master gained.
            if full not in first_parent_history(repo):
                continue
            changed = common.git(repo, "diff", "--name-only", parents[1], full, check=False).stdout
        else:
            changed = common.git(repo, "show", "--name-only", "--format=", commit, check=False).stdout
        for path in changed.splitlines():
            if path.startswith("source/") and not path.startswith("source/tests/") and path not in files:
                files.append(path)
    # Many files means something other than a fix (a refactor, a bulk change): better none.
    return files if len(files) <= MAXIMUM_COMMIT_FILES else []


MAXIMUM_COMMIT_FILES = 40
_FIRST_PARENT = {}


def first_parent_history(repo, base="origin/master"):
    if repo not in _FIRST_PARENT:
        result = common.git(repo, "rev-list", "--first-parent", base, check=False)
        _FIRST_PARENT[repo] = set(result.stdout.split()) if result.returncode == 0 else set()
    return _FIRST_PARENT[repo]


def clean_title(identifier, description):
    text = description.strip()
    # Drop leading status notes in (possibly nested) parentheses: "(accepted …; PRs #1 (with X), #2)".
    while text.startswith("("):
        depth = 0
        for index, character in enumerate(text):
            depth += {"(": 1, ")": -1}.get(character, 0)
            if depth == 0:
                break
        else:
            break
        text = text[index + 1:].lstrip()
    text = re.sub(r"`[^`]*\.(?:F90|Inc|inc|py|xml|c|cpp|h)[^`]*`", "", text)
    # Tidy what removing the paths left behind: "(, called only by )", "in :".
    text = re.sub(r"\(\s*[,;:]?\s*\)", "", text)
    text = re.sub(r"\(\s*[,;]\s*", "(", text)
    text = re.sub(r"\s+([,;:.)])", r"\1", text)
    text = re.sub(r"^[\s,;:.]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" .;—-")
    if len(text) > 140:
        text = text[:140].rsplit(" ", 1)[0] + "…"
    return text or identifier


def question_text(rest):
    match = re.search(r"(Andrew's call[^—]*|for Andrew[^—]*|waiting:[^—]*)", rest)
    if not match:
        return None
    text = re.sub(r"\s+", " ", match.group(1)).strip()
    return text[:400] + ("…" if len(text) > 400 else "")


def gh_pr_files(number, repository):
    if shutil.which("gh") is None:
        return None
    result = subprocess.run(["gh", "pr", "view", str(number), "--repo", repository, "--json", "files"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode != 0:
        return None
    return [entry["path"] for entry in json.loads(result.stdout).get("files", [])]


def gh_open_prs(repository):
    if shutil.which("gh") is None:
        return set()
    result = subprocess.run(["gh", "pr", "list", "--repo", repository, "--state", "open", "--limit", "200",
                             "--json", "number"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
    if result.returncode != 0:
        return set()
    return {entry["number"] for entry in json.loads(result.stdout)}


def parse_plan(text, repo=None, open_prs=(), pr_files=None):
    """Return (records, skipped): records are dicts of finding fields plus 'body'."""
    lines = text.splitlines()
    tracked = set(common.blob_hashes(repo)) if repo else set()
    table = parse_pr_table(lines)
    open_prs = set(open_prs)
    for entries in table.values():
        for number, status, _ in entries:
            if status.lower().startswith("open"):
                open_prs.add(number)
    pr_files = pr_files or {}
    records, skipped = [], []
    section = ""
    phase = ""
    for line in lines:
        heading = SECTION.match(line)
        if heading:
            if len(heading.group(1)) == 2:
                phase, section = heading.group(2), heading.group(2)
            else:
                section = heading.group(2)
            continue
        match = ITEM.match(line)
        if not match:
            continue
        identifier = match.group("id").strip()
        mark, rest = match.group("mark"), match.group("rest")
        if phase.lower().startswith("phase 3"):
            skipped.append((identifier, "Phase 3: audit work, not a finding"))
            continue
        description = rest.split(" — ")[0]
        notes = []
        # Files from the description.
        files, unresolved = [], []
        for token in PATH_TOKEN.findall(description):
            if token.startswith(("/", "~")) or "{" in token:
                continue  # a scratch file or a brace pattern, not a repository path
            path, found = resolve_path(token, repo, tracked)
            if path not in files:
                files.append(path)
            if not found:
                unresolved.append(path)
        if unresolved:
            notes.append("path(s) not found in the checkout: " + ", ".join(unresolved))
        if not files and repo is not None:
            files = commit_files(repo, COMMIT.findall(rest))
            if files:
                notes.append("files taken from the commits the line cites")
        if not files:
            notes.append("PLAN.md names no source file for this item: add `files` by hand")
        # PRs.
        # Only a done item belongs to a PR; an open item may just mention one.
        mentioned = [int(number) for number in PR_NUMBER.findall(rest)] if mark == "x" else []
        from_table = [entry for key in item_ids(identifier) for entry in table.get(key, [])] if mark == "x" else []
        open_here = []
        for number in mentioned:
            if number in open_prs and number not in open_here:
                open_here.append(number)
        open_here += [number for number, _, _ in from_table if number in open_prs and number not in open_here]
        branch = next((branch for number, _, branch in from_table if number in open_here and branch), None)
        # Status.
        question = None
        if mark == "x":
            if open_here:
                status = "pr-open"
            else:
                status = "merged"
                if not re.search(r"merged", rest, re.I):
                    notes.append("marked done in PLAN.md without saying merged: imported as merged")
        elif mark == "-":
            status = "rejected"
        elif PARKED.search(rest):
            status = "parked"
            question = question_text(rest)
        else:
            status = "verified"
            if mark == "~":
                notes.append("claimed in PLAN.md when imported (work may be in progress)")
        category, inferred = infer_category(identifier, section, rest)
        if inferred:
            notes.append("category inferred from the text")
        dates = DATE.findall(rest)
        fields = {
            "title": clean_title(identifier, description),
            "status": status,
            "severity": section_severity(section, rest),
            "confidence": "plausible" if PLAUSIBLE.search(rest) else "confirmed",
            "category": category,
            "files": files,
            "plan_id": identifier,
            "found_by": "PLAN.md import (overnight audit 2026-10-21)",
            "review_rounds": 0,
        }
        if dates:
            fields["created"] = min(dates)
        if question:
            fields["questions_for_andrew"] = question
        if open_here:
            fields["pr"] = open_here[0]
            if len(open_here) > 1:
                notes.append("also in open PR(s): " + ", ".join("#{}".format(n) for n in open_here[1:]))
            collected = []
            for number in open_here:
                for path in pr_files.get(number, []) or []:
                    if path not in collected:
                        collected.append(path)
            if collected:
                fields["pr_files"] = collected
        if branch:
            fields["branch"] = branch
        body = "\n## From PLAN.md\n\nSection: {}{}\n\n{}\n".format(
            section, " ({})".format(phase) if phase and phase != section else "", line.strip())
        if notes:
            body += "\n## Import notes\n\n" + "".join("- {}\n".format(note) for note in notes)
        body += ("\nThe evidence is in the report section the ID points at "
                 "(`~/Dropbox/AI/memory/overnight-2026-10-21/`), or in the line above for `N-` items.\n")
        records.append(dict(fields, body=body, notes=notes))
    return records, skipped


def existing_plan_ids(root):
    findings, _ = common.list_findings(root)
    return {fields.get("plan_id") for fields, _ in findings if fields.get("plan_id")}


def preview(records, skipped, existing):
    counts = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    lines = ["# PLAN.md import preview", "",
             "**{} items:** {}. Skipped: {}. Already imported: {}.".format(
                 len(records), ", ".join("{} {}".format(n, s) for s, n in sorted(counts.items())),
                 len(skipped), sum(1 for r in records if r["plan_id"] in existing)), "",
             "| ID | Status | Severity | Confidence | Category | Files | PR | Title | Notes |",
             "|---|---|---|---|---|---|---|---|---|"]
    order = {status: rank for rank, status in enumerate(common.STATUSES)}
    for record in sorted(records, key=lambda r: (order.get(r["status"], 99), r["plan_id"])):
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            record["plan_id"], record["status"], record["severity"], record["confidence"], record["category"],
            "<br>".join(record["files"]) or "-", "#{}".format(record["pr"]) if record.get("pr") else "-",
            record["title"].replace("|", "\\|"), "; ".join(record["notes"]).replace("|", "\\|") or "-"))
    if skipped:
        lines += ["", "## Skipped", ""] + ["- {}: {}".format(identifier, why) for identifier, why in skipped]
    return "\n".join(lines) + "\n"


def write_records(root, records, existing):
    created = []
    for record in records:
        if record["plan_id"] in existing:
            continue
        fields = {key: value for key, value in record.items() if key not in ("body", "notes")}
        identifier = common.create_finding_file(root, fields, record["body"])
        fields, body = common.load_finding(root, identifier)
        body = body.rstrip("\n") + "\n\n## History\n\n- {} imported from PLAN.md item {} (status: {})\n".format(
            common.iso_now(), record["plan_id"], record["status"])
        common.save_finding(root, fields, body)
        created.append((identifier, record["plan_id"]))
    return created


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plan", help="path to PLAN.md")
    parser.add_argument("--repo", help="Galacticus checkout, to resolve file paths (recommended)")
    parser.add_argument("--state", help="state directory (default $AUDIT_STATE_DIR or ~/Dropbox/AI/audit)")
    parser.add_argument("--open-pr", type=int, action="append", default=[], help="an open PR number (repeat)")
    parser.add_argument("--gh", action="store_true", help="look up open PRs and their files with the gh CLI")
    parser.add_argument("--repository", default="galacticusorg/galacticus")
    parser.add_argument("--pr-files", help="JSON file mapping PR number -> list of changed files")
    parser.add_argument("--preview", help="write the preview table to this Markdown file")
    parser.add_argument("--write", action="store_true", help="create the findings (default: preview only)")
    arguments = parser.parse_args(argv)
    with open(arguments.plan) as stream:
        text = stream.read()
    open_prs = set(arguments.open_pr)
    pr_files = {}
    if arguments.pr_files:
        with open(arguments.pr_files) as stream:
            pr_files = {int(key): value for key, value in json.load(stream).items()}
    if arguments.gh:
        open_prs |= gh_open_prs(arguments.repository)
    records, skipped = parse_plan(text, arguments.repo, open_prs, pr_files)
    if arguments.gh:
        for record in records:
            if record["status"] == "pr-open" and "pr_files" not in record:
                files = gh_pr_files(record["pr"], arguments.repository)
                if files:
                    record["pr_files"] = files
    root = common.state_dir(arguments.state)
    existing = existing_plan_ids(root) if os.path.isdir(os.path.join(root, "findings")) else set()
    report = preview(records, skipped, existing)
    if arguments.preview:
        with open(arguments.preview, "w") as stream:
            stream.write(report)
    if not arguments.write:
        print(report)
        print("(preview only: add --write to create the findings in {})".format(root))
        return
    common.ensure_layout(root)
    created = write_records(root, records, existing)
    print("created {} finding(s) in {}; {} already imported".format(
        len(created), root, sum(1 for r in records if r["plan_id"] in existing)))
    for identifier, plan_id in created:
        print("  {} <- {}".format(identifier, plan_id))


if __name__ == "__main__":
    main()
