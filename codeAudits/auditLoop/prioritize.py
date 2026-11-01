#!/usr/bin/env python3
"""Rank Galacticus source files for the next audit.

    prioritize.py [--repo DIR] [--lens bugs] [--top 30] [--json] [--explain PATH]

Each file gets

    score = wR*R + wC*C + wS*S + wB*B

  R  reference-model use: 1 if a reference model names the implementation
     the file defines (or the file defines the class itself), 0.5 if it is
     a class default (used unless a model overrides it), 0.3 if a directly
     used file `use`s a module it defines. The reference models are every
     XML file under parameters/reference/, the testSuite/parameters/validate_*
     files, and every XML file named by a testSuite/validate-*.py script.
  C  change: 1 if the file changed since its last review under this lens;
     otherwise recent churn, sum over commits in the last --churn-days of
     changed lines * exp(-age/--churn-scale-days), mapped to 0-1.
  S  staleness: 1 if never reviewed under this lens, else
     min(1, days since review / --stale-days). A `skim` counts as a review
     --skim-penalty-days older than it was.
  B  bug density: open or closed findings that name the file (and, at a
     quarter weight, its directory), saturating at 3.

Files claimed by another session, and files fully reviewed under this lens
in the last --cooldown-days and unchanged since, are left out. The static
reference-model mapping does not see implementations chosen by code rather
than by parameters, so R is a lower bound: a gcov-based mapping is the
planned upgrade.
"""
import argparse
import collections
import glob
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ElementTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auditCommon as common  # noqa: E402

SOURCE_SUFFIXES = (".F90", ".Inc", ".c", ".cpp", ".h")


# ------------------------------------------------------------------ source scan

FUNCTION_CLASS = re.compile(r"<functionClass\b.*?</functionClass>", re.S)
COMPONENT = re.compile(r"<component\b.*?</component>", re.S)
MODULE = re.compile(r"^\s*module\s+(?!procedure\b)(\w+)\s*$", re.I | re.M)
USE = re.compile(r"^\s*use\s*(?:,\s*(?:non_)?intrinsic\s*)?(?:::)?\s*(\w+)", re.I | re.M)
INCLUDE = re.compile(r"^\s*(?:#\s*)?include\s*[\"']([^\"']+)[\"']", re.I | re.M)
FUNCTIONS = re.compile(r"<functions>\s*([^<\s]+)\s*</functions>")


def tag_text(block, tag):
    match = re.search(r"<{0}>\s*(.*?)\s*</{0}>".format(tag), block, re.S)
    return match.group(1) if match else None


def capitalize(text):
    return text[:1].upper() + text[1:]


def scan_source(repo):
    """Collect, from the directive blocks and Fortran statements:
         classes:        class name -> (class file, default implementation name)
         implementations: implementation name -> file
         components:     (componentClass, name) -> defining file, plus defaults
         modules:        module name -> file;  uses: file -> modules;  includes: file -> files
    """
    classes = {}
    implementations = {}
    components = {}
    component_defaults = set()
    modules = {}
    uses = {}
    includes = {}
    texts = {}
    for path in sorted(glob.glob(os.path.join(repo, "source", "**", "*"), recursive=True)):
        if not path.endswith(SOURCE_SUFFIXES) or not os.path.isfile(path):
            continue
        relative = os.path.relpath(path, repo)
        with open(path, errors="replace") as stream:
            text = stream.read()
        texts[relative] = text
        for block in FUNCTION_CLASS.findall(text):
            name = tag_text(block, "name")
            if name:
                classes[name] = (relative, tag_text(block, "default"))
        for block in COMPONENT.findall(text):
            component_class, name = tag_text(block, "class"), tag_text(block, "name")
            if component_class and name:
                key = (component_class, name)
                components[key] = relative
                if (tag_text(block, "isDefault") or "").strip().lower() == "true":
                    component_defaults.add(key)
        for module in MODULE.findall(text):
            modules.setdefault(module.lower(), relative)
        uses[relative] = {module.lower() for module in USE.findall(text)}
        includes[relative] = set(INCLUDE.findall(text)) | set(FUNCTIONS.findall(text))
    # Implementation directives: <className name="classNameSomething" ...>.
    if classes:
        pattern = re.compile(r"<({})\s+name=\"(\w+)\"".format("|".join(sorted(map(re.escape, classes), key=len,
                                                                                  reverse=True))))
        for relative, text in texts.items():
            for class_name, name in pattern.findall(text):
                if name.startswith(class_name):
                    implementations.setdefault(name, relative)
    return {"classes": classes, "implementations": implementations, "components": components,
            "component_defaults": component_defaults, "modules": modules, "uses": uses, "includes": includes,
            "files": sorted(texts)}


# ------------------------------------------------------------------ reference models

def reference_model_files(repo):
    files = set(glob.glob(os.path.join(repo, "parameters", "reference", "**", "*.xml"), recursive=True))
    files |= set(glob.glob(os.path.join(repo, "testSuite", "parameters", "validate_*.xml")))
    for script in glob.glob(os.path.join(repo, "testSuite", "validate-*.py")):
        with open(script, errors="replace") as stream:
            text = stream.read()
        for literal in re.findall(r"[\"']([^\"'\s]+\.xml)[\"']", text):
            for base in (repo, os.path.join(repo, "testSuite")):
                candidate = os.path.normpath(os.path.join(base, literal))
                if os.path.isfile(candidate):
                    files.add(candidate)
        # Directories a script globs over (e.g. the halo mass function manifest).
        for literal in re.findall(r"[\"']((?:testSuite/)?parameters/[^\"'\s]+/)[\"']", text):
            for base in (repo, os.path.join(repo, "testSuite")):
                directory = os.path.normpath(os.path.join(base, literal))
                if os.path.isdir(directory):
                    files |= set(glob.glob(os.path.join(directory, "**", "*.xml"), recursive=True))
    # Follow XIncludes to fragments outside the set.
    pending = sorted(files)
    while pending:
        path = pending.pop()
        try:
            with open(path, errors="replace") as stream:
                text = stream.read()
        except OSError:
            continue
        for href in re.findall(r"<xi:include[^>]*\bhref=\"([^\"]+)\"", text):
            target = os.path.normpath(os.path.join(os.path.dirname(path), href))
            if target not in files and os.path.isfile(target):
                files.add(target)
                pending.append(target)
    return sorted(files)


def parameter_selections(paths):
    """(element name, value) pairs for every element with a value attribute."""
    selections = set()
    for path in paths:
        try:
            tree = ElementTree.parse(path)
        except (ElementTree.ParseError, OSError):
            continue
        for element in tree.iter():
            if not isinstance(element.tag, str):
                continue
            value = element.get("value")
            if value and re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", value):
                selections.add((element.tag.split("}")[-1], value))
    return selections


def component_files(scan, key):
    """The files implementing a component: its whole directory if it is defined in a
    `_class.F90` of its own, otherwise just the defining file."""
    defining = scan["components"][key]
    if os.path.basename(defining) != "_class.F90":
        return [defining]
    directory = os.path.dirname(defining)
    return [path for path in scan["files"] if os.path.dirname(path) == directory]


def resolve_includes(scan, path):
    """Files included by `path`. Fortran includes are written relative to source/, often
    with a lower-case `.inc` for an `.Inc` file, so try both bases, ignoring case."""
    lowered = scan.setdefault("_lowered", {name.lower(): name for name in scan["files"]})
    targets = []
    for include in scan["includes"].get(path, ()):
        for base in (os.path.dirname(path), "source"):
            candidate = os.path.normpath(os.path.join(base, include)).lower()
            if candidate in lowered:
                targets.append(lowered[candidate])
                break
    return targets


def reference_use(repo, scan):
    """Map file -> (R, reason)."""
    selections = parameter_selections(reference_model_files(repo))
    direct = {}
    for tag, value in selections:
        if tag in scan["classes"]:
            implementation = tag + capitalize(value)
            if implementation in scan["implementations"]:
                direct.setdefault(scan["implementations"][implementation], "{}={}".format(tag, value))
                direct.setdefault(scan["classes"][tag][0], "class {}".format(tag))
        elif tag.startswith("component"):
            component_class = tag[len("component"):]
            key = (component_class[:1].lower() + component_class[1:], value)
            if key in scan["components"]:
                for path in component_files(scan, key):
                    direct.setdefault(path, "{}={}".format(tag, value))
    defaults = {}
    for class_name, (class_file, default) in scan["classes"].items():
        if default:
            implementation = class_name + capitalize(default)
            if implementation in scan["implementations"]:
                defaults.setdefault(scan["implementations"][implementation], "default {}".format(implementation))
    for key in scan["component_defaults"]:
        if key in scan["components"]:
            for path in component_files(scan, key):
                defaults.setdefault(path, "default component {}:{}".format(*key))
    # Include files take the score of the file including them.
    for table in (direct, defaults):
        for path in list(table):
            for target in resolve_includes(scan, path):
                table.setdefault(target, "included by " + path)
    support = {}
    for path in list(direct):
        for module in scan["uses"].get(path, ()):
            target = scan["modules"].get(module)
            if target and target not in direct:
                support.setdefault(target, "used by " + path)
    for path in list(support):
        for target in resolve_includes(scan, path):
            support.setdefault(target, "included by " + path)
    result = {}
    for path, reason in support.items():
        result[path] = (0.3, reason)
    for path, reason in defaults.items():
        result[path] = (0.5, reason)
    for path, reason in direct.items():
        result[path] = (1.0, reason)
    return result


# ------------------------------------------------------------------ churn

def churn(repo, days, scale_days, now, bulk_files=150):
    """Map file -> decayed changed-line count over the last `days` days."""
    result = common.git(repo, "log", "--since={}.days".format(days), "--no-merges", "--numstat",
                        "--format=@%ct", "--", "source", check=False)
    commits = []
    for line in result.stdout.splitlines():
        if line.startswith("@"):
            commits.append((int(line[1:]), []))
            continue
        parts = line.split("\t")
        if commits and len(parts) == 3 and parts[0] != "-":
            commits[-1][1].append((parts[2], int(parts[0]) + int(parts[1])))
    totals = collections.defaultdict(float)
    for timestamp, changes in commits:
        # Bulk mechanical commits (license-year updates, renames, the boundary
        # commit of a shallow clone) say nothing about where bugs are.
        if len(changes) > bulk_files:
            continue
        weight = math.exp(-max(0.0, (now - timestamp) / 86400.0) / scale_days)
        for path, changed in changes:
            totals[path] += weight * changed
    return totals


# ------------------------------------------------------------------ scoring

def bug_density(findings):
    per_file = collections.Counter()
    per_directory = collections.Counter()
    for fields, _ in findings:
        if fields.get("status") == "rejected":
            continue
        for entry in {entry.split(":")[0] for entry in fields.get("files") or []}:
            per_file[entry] += 1
            per_directory[os.path.dirname(entry)] += 1
    return per_file, per_directory


def rank(arguments):
    repo = os.path.abspath(arguments.repo)
    root = common.state_dir(arguments.state)
    now = common.now_utc()
    scan = scan_source(repo)
    reference = reference_use(repo, scan)
    churned = churn(repo, arguments.churn_days, arguments.churn_scale_days, now.timestamp(), arguments.bulk_files)
    hashes = common.blob_hashes(repo, "HEAD", ["source"])
    reviews = common.latest_reviews(common.read_coverage(root), arguments.lens)
    findings, _ = common.list_findings(root)
    per_file, per_directory = bug_density(findings)
    claims = common.active_claims(root)
    rows = []
    for path in scan["files"]:
        if path not in hashes:  # untracked
            continue
        if path in claims and claims[path].get("session") != arguments.session:
            continue
        review = reviews.get(path)
        changed = review is not None and review.get("blob") != hashes[path]
        if review is not None:
            age = (now - common.parse_iso(review["date"])).total_seconds() / 86400.0
            if review.get("depth") == "skim":
                age += arguments.skim_penalty_days
            elif not changed and age < arguments.cooldown_days:
                continue
            staleness = min(1.0, age / arguments.stale_days)
        else:
            staleness = 1.0
        r, r_reason = reference.get(path, (0.0, ""))
        c = 1.0 if changed else 1.0 - math.exp(-churned.get(path, 0.0) / arguments.churn_lines)
        b = min(1.0, (per_file[path] + 0.25 * per_directory[os.path.dirname(path)]) / 3.0)
        score = arguments.w_reference * r + arguments.w_change * c + arguments.w_stale * staleness \
            + arguments.w_bugs * b
        with open(os.path.join(repo, path), errors="replace") as stream:
            lines = sum(1 for _ in stream)
        rows.append({"path": path, "score": round(score, 3), "R": r, "C": round(c, 3), "S": round(staleness, 3),
                     "B": round(b, 3), "lines": lines, "changed_since_review": changed,
                     "last_review": review.get("date") if review else None, "why_R": r_reason})
    rows.sort(key=lambda row: (-row["score"], row["path"]))
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=os.environ.get("GALACTICUS_EXEC_PATH", "."),
                        help="Galacticus checkout, at the commit to be audited (default $GALACTICUS_EXEC_PATH)")
    parser.add_argument("--state", help="state directory (default $AUDIT_STATE_DIR or ~/Dropbox/AI/audit)")
    parser.add_argument("--lens", default="bugs", choices=common.LENSES)
    parser.add_argument("--session", help="this session's id: its own claims are not excluded")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--explain", metavar="PATH", help="print the score breakdown of one file")
    parser.add_argument("--w-reference", type=float, default=3.0)
    parser.add_argument("--w-change", type=float, default=2.0)
    parser.add_argument("--w-stale", type=float, default=1.5)
    parser.add_argument("--w-bugs", type=float, default=0.5)
    parser.add_argument("--churn-days", type=int, default=180)
    parser.add_argument("--churn-scale-days", type=float, default=90.0)
    parser.add_argument("--churn-lines", type=float, default=50.0,
                        help="decayed changed lines at which C reaches 1-1/e")
    parser.add_argument("--bulk-files", type=int, default=150,
                        help="ignore commits touching more than this many source files")
    parser.add_argument("--stale-days", type=float, default=180.0)
    parser.add_argument("--skim-penalty-days", type=float, default=120.0)
    parser.add_argument("--cooldown-days", type=float, default=30.0)
    arguments = parser.parse_args(argv)
    rows = rank(arguments)
    if arguments.explain:
        matches = [row for row in rows if row["path"] == arguments.explain]
        print(json.dumps(matches[0] if matches else {"path": arguments.explain, "excluded": True}, indent=1))
        return
    rows = rows[:arguments.top]
    if arguments.json:
        print(json.dumps(rows, indent=1))
        return
    print("{:>6}  {:>4} {:>5} {:>5} {:>5}  {:>6}  {}".format("score", "R", "C", "S", "B", "lines", "path"))
    for row in rows:
        print("{score:6.2f}  {R:4.1f} {C:5.2f} {S:5.2f} {B:5.2f}  {lines:6d}  {path}{flag}".format(
            flag="  [changed since review]" if row["changed_since_review"] else "", **row))


if __name__ == "__main__":
    main()
