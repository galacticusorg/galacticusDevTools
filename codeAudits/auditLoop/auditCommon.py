"""Shared helpers for the Galacticus audit-loop tools.

The audit state lives in a directory synced between machines (by default
`~/Dropbox/AI/audit`, overridden by `$AUDIT_STATE_DIR`):

    findings/F-NNNN.md        one file per finding: front matter + Markdown body
    coverage/<session>.jsonl  append-only review records, one file per session
    claims/<key>.json         short-lived locks on files being audited
    runs/<session>.md         per-run log; runs/<session>-usage.jsonl usage marks
    INDEX.md                  generated review queue (auditState.py index)

Everything is plain text so that it can be read and edited by hand, and so
that Dropbox can sync it. Each session writes only its own coverage and run
files, and findings are separate files, which keeps Dropbox conflicted copies
rare. Written for Python >= 3.9 (the system python3 on RHEL 9).
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import tempfile

SEVERITIES = ["critical", "high", "medium", "low", "latent"]
CONFIDENCES = ["confirmed", "plausible"]
COMPLEXITIES = ["S", "M", "L"]
CATEGORIES = ["wrong-result", "crash", "threading", "physics", "units", "latent", "docs", "other"]
STATUSES = [
    "verified",          # confirmed by a verifier, no fix yet
    "fix-staged",        # fix + test committed on a local branch, built and tested
    "in-peer-review",    # the in-session reviewer is iterating on it
    "ready-for-review",  # reviewer accepted: waiting for Andrew
    "accepted",          # Andrew accepted the fix
    "pr-open",           # a PR exists
    "merged",            # the fix is on origin/master
    "parked",            # needs Andrew's decision (question recorded)
    "rejected",          # not a bug, or not worth fixing
    "superseded",        # replaced by another finding/branch
]
# Statuses for which a finding still needs attention from someone.
OPEN_STATUSES = ["verified", "fix-staged", "in-peer-review", "ready-for-review", "accepted", "pr-open", "parked"]
# Statuses that count against the review back-pressure cap.
BACKLOG_STATUSES = ["ready-for-review"]
LENSES = ["bugs", "threading", "units", "physics", "docs"]
DEPTHS = ["full", "skim"]

# Front-matter key order when a finding is written.
FIELD_ORDER = [
    "id", "title", "status", "severity", "confidence", "complexity", "category",
    "files", "affects_reference_models", "branch", "base", "head", "depends_on",
    "diff_lines", "review_rounds", "pr", "questions_for_andrew", "found_by",
    "created", "updated",
]


def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def iso_now():
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(text):
    """Parse the ISO-8601 forms the tools write (date, or date-time with Z)."""
    text = str(text).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    value = datetime.datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value


def state_dir(override=None):
    path = override or os.environ.get("AUDIT_STATE_DIR") or os.path.expanduser("~/Dropbox/AI/audit")
    return os.path.abspath(path)


def ensure_layout(root):
    for sub in ("findings", "coverage", "claims", "runs"):
        os.makedirs(os.path.join(root, sub), exist_ok=True)


def atomic_write(path, text):
    """Write a file via a temporary file in the same directory, then rename."""
    directory = os.path.dirname(path) or "."
    handle, temporary = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def append_line(path, line):
    with open(path, "a") as stream:
        stream.write(line.rstrip("\n") + "\n")


# ------------------------------------------------------------------ front matter
#
# A deliberately small YAML subset, so no PyYAML is needed: one `key: value`
# per line. A value that starts with [ { " or is a number, true/false/null is
# JSON; anything else is a plain string. Lists are written as JSON.

def _parse_value(raw):
    raw = raw.strip()
    if raw == "":
        return None
    if raw[0] in "[{\"" or raw in ("true", "false", "null") or re.fullmatch(r"-?\d+(\.\d+)?", raw):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def _format_value(value):
    if value is None:
        return ""
    if isinstance(value, bool) or isinstance(value, (int, float)) or isinstance(value, (list, dict)):
        return json.dumps(value)
    text = str(value)
    # Quote strings that would otherwise be read back as something else.
    if text != text.strip() or text[:1] in "[{\"" or text in ("true", "false", "null") \
            or re.fullmatch(r"-?\d+(\.\d+)?", text) or "\n" in text:
        return json.dumps(text)
    return text


def parse_front_matter(text):
    """Split a finding file into (fields, body)."""
    if not text.startswith("---\n"):
        raise ValueError("no front matter (file must start with '---')")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("unterminated front matter")
    fields = {}
    for number, line in enumerate(text[4:end].split("\n"), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(.*)$", line)
        if not match:
            raise ValueError("line {}: expected 'key: value', got {!r}".format(number, line))
        fields[match.group(1)] = _parse_value(match.group(2))
    return fields, text[end + 5:]


def format_front_matter(fields, body):
    keys = [key for key in FIELD_ORDER if key in fields] + sorted(key for key in fields if key not in FIELD_ORDER)
    lines = ["---"]
    for key in keys:
        lines.append("{}: {}".format(key, _format_value(fields[key])).rstrip())
    lines.append("---")
    return "\n".join(lines) + "\n" + body


# ------------------------------------------------------------------ findings

FINDING_NAME = re.compile(r"^(F-\d{4,})\.md$")


def finding_path(root, identifier):
    return os.path.join(root, "findings", identifier + ".md")


def load_finding(root, identifier):
    with open(finding_path(root, identifier)) as stream:
        fields, body = parse_front_matter(stream.read())
    return fields, body


def save_finding(root, fields, body):
    fields["updated"] = iso_now()
    atomic_write(finding_path(root, fields["id"]), format_front_matter(fields, body))


def list_findings(root):
    """Return (findings, problems): findings as a list of (fields, body)."""
    findings = []
    problems = []
    directory = os.path.join(root, "findings")
    if not os.path.isdir(directory):
        return findings, problems
    for name in sorted(os.listdir(directory)):
        if name.startswith("."):
            continue
        if "conflicted copy" in name:
            problems.append("Dropbox conflicted copy: findings/{} (merge it by hand, then delete it)".format(name))
            continue
        if not FINDING_NAME.match(name):
            if name.endswith(".md"):
                problems.append("unexpected file name: findings/{}".format(name))
            continue
        try:
            with open(os.path.join(directory, name)) as stream:
                fields, body = parse_front_matter(stream.read())
        except (OSError, ValueError) as error:
            problems.append("findings/{}: {}".format(name, error))
            continue
        if fields.get("id") != name[:-3]:
            problems.append("findings/{}: id field is {!r}".format(name, fields.get("id")))
        findings.append((fields, body))
    return findings, problems


def next_finding_id(root):
    directory = os.path.join(root, "findings")
    highest = 0
    for name in os.listdir(directory):
        match = re.match(r"^F-(\d+)", name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def create_finding_file(root, fields, body):
    """Create a new finding with the next free id (exclusive create, so two
    sessions on one machine can not take the same id)."""
    for _ in range(100):
        identifier = "F-{:04d}".format(next_finding_id(root))
        path = finding_path(root, identifier)
        try:
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        fields = dict(fields)
        fields["id"] = identifier
        fields.setdefault("created", iso_now())
        fields["updated"] = iso_now()
        with os.fdopen(handle, "w") as stream:
            stream.write(format_front_matter(fields, body))
        return identifier
    raise RuntimeError("could not allocate a finding id")


# ------------------------------------------------------------------ coverage

def read_coverage(root):
    """All coverage records, oldest first. Malformed lines are skipped."""
    records = []
    directory = os.path.join(root, "coverage")
    if not os.path.isdir(directory):
        return records
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(directory, name)) as stream:
            for line in stream:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
    records.sort(key=lambda record: record.get("date", ""))
    return records


def latest_reviews(records, lens=None):
    """Map path -> most recent coverage record (for one lens, or any lens)."""
    latest = {}
    for record in records:
        if lens is not None and record.get("lens") != lens:
            continue
        path = record.get("path")
        if path is None:
            continue
        previous = latest.get(path)
        if previous is None or record.get("date", "") >= previous.get("date", ""):
            latest[path] = record
    return latest


# ------------------------------------------------------------------ claims

def claim_key(path):
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def claim_path(root, path):
    return os.path.join(root, "claims", claim_key(path) + ".json")


def read_claim(root, path):
    try:
        with open(claim_path(root, path)) as stream:
            return json.load(stream)
    except (OSError, ValueError):
        return None


def claim_expired(claim, at=None):
    at = at or now_utc()
    try:
        return parse_iso(claim["expires"]) <= at
    except (KeyError, ValueError, TypeError):
        return True


def active_claims(root):
    claims = {}
    directory = os.path.join(root, "claims")
    if not os.path.isdir(directory):
        return claims
    for name in os.listdir(directory):
        if not name.endswith(".json") or name.startswith("."):
            continue
        try:
            with open(os.path.join(directory, name)) as stream:
                claim = json.load(stream)
        except (OSError, ValueError):
            continue
        if not claim_expired(claim):
            claims[claim.get("path")] = claim
    return claims


# ------------------------------------------------------------------ git

def git(repo, *arguments, check=True):
    result = subprocess.run(["git", "-C", repo] + list(arguments), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
    if check and result.returncode != 0:
        raise RuntimeError("git {} failed: {}".format(" ".join(arguments), result.stderr.strip()))
    return result


def blob_hashes(repo, ref="HEAD", paths=None):
    """Map path -> blob hash for files at `ref` (optionally only `paths`)."""
    arguments = ["ls-tree", "-r", ref]
    if paths:
        arguments += ["--"] + list(paths)
    hashes = {}
    for line in git(repo, *arguments).stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob":
            hashes[path] = parts[2]
    return hashes
