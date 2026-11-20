#!/usr/bin/env python3
"""Render the audit state directory as a single, self-contained HTML page.

    auditDashboard.py --output DIR/index.html [--state DIR] [--repository OWNER/NAME] [--runs N]

The page holds every finding (front matter and Markdown body), the review queue in the order
`auditState.py index` uses, the active claims, a coverage summary, and the latest run logs. It
is meant to be rebuilt from cron and served read-only (e.g. by `tailscale serve`); it never
writes to the state directory. Finding bodies are rendered in the browser with marked and
DOMPurify from cdnjs; without them (offline) the bodies are shown as plain text.

The state directory is `$AUDIT_STATE_DIR`, or `~/Dropbox/AI/audit`; `--state` overrides both.
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auditCommon as common  # noqa: E402
import auditState  # noqa: E402


def run_logs(root, limit):
    """The newest `limit` run logs (runs/*.md), newest first, as (name, modified, text)."""
    directory = os.path.join(root, "runs")
    if not os.path.isdir(directory):
        return []
    logs = []
    for name in os.listdir(directory):
        if not name.endswith(".md") or name.startswith("."):
            continue
        path = os.path.join(directory, name)
        try:
            with open(path, errors="replace") as stream:
                text = stream.read()
            modified = os.path.getmtime(path)
        except OSError:
            continue
        logs.append((modified, name[:-3], text))
    logs.sort(reverse=True)
    return [{"name": name, "modified": stamp(modified), "text": text} for modified, name, text in logs[:limit]]


def stamp(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def coverage_summary(root):
    """Files reviewed per lens (full and skim), and per-session totals."""
    records = common.read_coverage(root)
    lenses = {}
    for lens in common.LENSES:
        latest = common.latest_reviews(records, lens)
        full = sum(1 for record in latest.values() if record.get("depth") == "full")
        lenses[lens] = {"full": full, "skim": len(latest) - full,
                        "last": max((record.get("date", "") for record in latest.values()), default="")}
    sessions = {}
    for record in records:
        entry = sessions.setdefault(record.get("session", "?"), {"session": record.get("session", "?"), "files": set(),
                                                                  "lenses": set(), "findings": set(), "last": ""})
        entry["files"].add(record.get("path"))
        entry["lenses"].add(record.get("lens"))
        entry["findings"].update(record.get("findings") or [])
        entry["last"] = max(entry["last"], record.get("date", ""))
    sessions = sorted(sessions.values(), key=lambda entry: entry["last"], reverse=True)
    return {
        "files": len(common.latest_reviews(records)),
        "lenses": lenses,
        "sessions": [{"session": entry["session"], "files": len(entry["files"]),
                      "lenses": sorted(lens for lens in entry["lenses"] if lens),
                      "findings": sorted(entry["findings"]), "last": entry["last"]} for entry in sessions[:20]],
    }


def collect(root, runs):
    findings, problems = common.list_findings(root)
    ready = [fields for fields, _ in findings if fields.get("status") == "ready-for-review"]
    queue = [fields["id"] for fields in auditState.review_order(ready)]
    items = []
    for fields, body in findings:
        entry = dict(fields)
        entry["body"] = body
        entry["complexity_note"] = auditState.complexity_mismatch(fields)
        items.append(entry)
    claims = [dict(claim, path=path) for path, claim in sorted(common.active_claims(root).items())]
    return {
        "generated": common.iso_now(),
        "state": root,
        "statuses": common.STATUSES,
        "open_statuses": common.OPEN_STATUSES,
        "severities": common.SEVERITIES,
        "categories": common.CATEGORIES,
        "findings": items,
        "queue": queue,
        "problems": problems,
        "claims": claims,
        "coverage": coverage_summary(root),
        "runs": run_logs(root, runs),
    }


def render(data, repository):
    data = dict(data, repository=repository)
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    # Keep the JSON from closing the <script> element that holds it.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return TEMPLATE.replace("__DATA__", payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", required=True, help="HTML file to write (written atomically)")
    parser.add_argument("--state", help="state directory (default $AUDIT_STATE_DIR or ~/Dropbox/AI/audit)")
    parser.add_argument("--repository", default="galacticusorg/galacticus",
                        help="GitHub repository for PR and file links (default: %(default)s)")
    parser.add_argument("--runs", type=int, default=20, help="number of run logs to include (default: %(default)s)")
    arguments = parser.parse_args(argv)
    root = common.state_dir(arguments.state)
    if not os.path.isdir(os.path.join(root, "findings")):
        print("auditDashboard.py: no findings directory in {}".format(root), file=sys.stderr)
        return 1
    data = collect(root, arguments.runs)
    output = os.path.abspath(arguments.output)
    os.makedirs(os.path.dirname(output), exist_ok=True)
    common.atomic_write(output, render(data, arguments.repository))
    os.chmod(output, 0o644)
    print("{}: {} findings, {} queued, {} claims, {} problems".format(
        output, len(data["findings"]), len(data["queue"]), len(data["claims"]), len(data["problems"])))
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Galacticus Audit Tracker</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js"></script>
<style>
:root {
  --bg:#f7f7f5; --panel:#ffffff; --ink:#1d1f21; --muted:#6b6f76; --line:#e2e2de; --accent:#2457c5;
  --sev-critical:#8e1b1b; --sev-high:#c2410c; --sev-medium:#a16207; --sev-low:#3f6212; --sev-latent:#64748b;
  --chip:#eef0f3; --warn-bg:#fff4e5; --warn-ink:#8a4b00;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#16181b; --panel:#1f2226; --ink:#e7e8ea; --muted:#9aa0a8; --line:#33373d; --accent:#79a6ff;
    --sev-critical:#ff8a8a; --sev-high:#ffa66b; --sev-medium:#f0c14b; --sev-low:#a3d977; --sev-latent:#a8b3c4;
    --chip:#2a2e34; --warn-bg:#3a2a12; --warn-ink:#f5c27a;
  }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
main { max-width:1240px; margin:0 auto; padding:20px 16px 48px; }
h1 { font-size:20px; margin:0 0 2px; } h2 { font-size:15px; margin:0 0 10px; }
a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; }
code, .mono { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
.sub { color:var(--muted); font-size:12.5px; }
.panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px 16px; margin-top:16px; }
.warn { background:var(--warn-bg); color:var(--warn-ink); border-radius:8px; padding:10px 14px; margin-top:14px; font-size:13px; }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
.chip { background:var(--chip); border:1px solid var(--line); border-radius:999px; padding:2px 10px; font-size:12.5px; cursor:pointer; color:var(--ink); }
.chip b { font-variant-numeric:tabular-nums; }
.chip.on { border-color:var(--accent); color:var(--accent); }
nav.tabs { display:flex; gap:4px; margin-top:16px; border-bottom:1px solid var(--line); flex-wrap:wrap; }
nav.tabs button { background:none; border:none; border-bottom:2px solid transparent; padding:6px 12px; font:inherit; color:var(--muted); cursor:pointer; }
nav.tabs button.on { color:var(--ink); border-bottom-color:var(--accent); font-weight:600; }
.controls { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; margin-bottom:10px; font-size:13px; }
input[type=search], select { font:inherit; color:var(--ink); background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:4px 8px; }
input[type=search] { min-width:240px; flex:1; max-width:420px; }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { padding:6px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
th { color:var(--muted); font-weight:500; white-space:nowrap; cursor:pointer; user-select:none; }
tbody tr { cursor:pointer; } tbody tr:hover td { background:color-mix(in srgb, var(--accent) 6%, transparent); }
td.n { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
td.id { white-space:nowrap; font-weight:600; }
td.q { color:var(--muted); font-size:12.5px; max-width:420px; }
.sev { font-weight:600; white-space:nowrap; }
.sev-critical { color:var(--sev-critical); } .sev-high { color:var(--sev-high); } .sev-medium { color:var(--sev-medium); }
.sev-low { color:var(--sev-low); } .sev-latent { color:var(--sev-latent); }
.status { display:inline-block; background:var(--chip); border-radius:4px; padding:0 6px; font-size:12px; white-space:nowrap; }
.empty { color:var(--muted); padding:8px 0; }
/* Detail overlay */
#detail { position:fixed; inset:0; background:rgba(0,0,0,.35); display:none; z-index:10; }
#detail.on { display:block; }
#detail .sheet { position:absolute; right:0; top:0; bottom:0; width:min(900px,100%); background:var(--panel); overflow-y:auto; padding:18px 22px 40px; border-left:1px solid var(--line); }
#detail .close { float:right; font-size:20px; background:none; border:none; color:var(--muted); cursor:pointer; }
.meta { display:grid; grid-template-columns:max-content 1fr; gap:3px 14px; font-size:13px; margin:12px 0 4px; }
.meta > span:nth-child(odd) { color:var(--muted); }
.question { background:var(--warn-bg); color:var(--warn-ink); border-radius:6px; padding:8px 12px; margin:10px 0; font-size:13px; }
.md { font-size:14px; overflow-wrap:anywhere; }
.md h1, .md h2 { font-size:16px; margin:22px 0 8px; border-bottom:1px solid var(--line); padding-bottom:3px; }
.md h3 { font-size:14.5px; margin:18px 0 6px; }
.md pre { background:var(--chip); padding:10px 12px; border-radius:6px; overflow-x:auto; }
.md :not(pre) > code { background:var(--chip); padding:0 4px; border-radius:3px; }
.md table { font-size:12.5px; } .md table td, .md table th { cursor:auto; }
pre.raw { white-space:pre-wrap; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
.grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }
details.run { border-bottom:1px solid var(--line); padding:6px 0; } details.run summary { cursor:pointer; }
</style>
</head>
<body>
<main>
  <h1>Galacticus audit tracker</h1>
  <div class="sub" id="hdr"></div>
  <div id="problems"></div>
  <div class="chips" id="chips"></div>
  <div id="claims"></div>
  <nav class="tabs" id="tabs">
    <button data-t="queue">Review queue</button>
    <button data-t="all">All findings</button>
    <button data-t="runs">Runs</button>
    <button data-t="coverage">Coverage</button>
  </nav>
  <section id="tab-queue"></section>
  <section id="tab-all" hidden>
    <div class="panel">
      <div class="controls">
        <input type="search" id="q" placeholder="Search titles, files, branches, bodies…">
        <label>Status <select id="fStatus"></select></label>
        <label>Severity <select id="fSev"></select></label>
        <label>Category <select id="fCat"></select></label>
        <span class="sub" id="count"></span>
      </div>
      <div class="scroll"><table id="all"></table></div>
    </div>
  </section>
  <section id="tab-runs" hidden></section>
  <section id="tab-coverage" hidden></section>
</main>
<div id="detail"><div class="sheet" id="sheet"></div></div>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const byId = Object.fromEntries(D.findings.map(f => [f.id, f]));
const sevRank = Object.fromEntries(D.severities.map((s, i) => [s, i]));
const GH = "https://github.com/" + D.repository;
const haveMd = typeof marked !== "undefined" && typeof DOMPurify !== "undefined";

const sev = s => s ? `<span class="sev sev-${esc(s)}">${esc(s)}</span>` : "—";
const status = s => `<span class="status">${esc(s || "—")}</span>`;
const prLink = n => n ? `<a href="${GH}/pull/${encodeURIComponent(n)}" target="_blank" rel="noopener">#${esc(n)}</a>` : "—";
function fileLink(f) {
  const m = String(f).match(/^([^:\s]+?)(?::(\d+))?(\s.*)?$/);
  if (!m || !/^[\w.\-\/]+$/.test(m[1]) || !m[1].includes("/")) return `<code>${esc(f)}</code>`;
  const href = `${GH}/blob/master/${m[1].split("/").map(encodeURIComponent).join("/")}${m[2] ? "#L" + m[2] : ""}`;
  return `<a href="${href}" target="_blank" rel="noopener"><code>${esc(m[1])}${m[2] ? ":" + m[2] : ""}</code></a>${esc(m[3] || "")}`;
}
// Titles are one-line Markdown: show `code` spans, escape everything else.
const title = s => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");
const list = v => Array.isArray(v) ? v : (v == null || v === "" ? [] : [v]);
const fmtDate = s => s ? String(s).replace("T", " ").replace(/:\d\dZ$/, "Z") : "—";

// ---------- header, problems, chips, claims ----------
const counts = {};
for (const f of D.findings) counts[f.status] = (counts[f.status] || 0) + 1;
$("hdr").innerHTML = `${D.findings.length} findings · generated ${esc(fmtDate(D.generated))} from <code>${esc(D.state)}</code>` +
  (haveMd ? "" : " · <b>Markdown renderer not loaded (offline?): bodies shown as plain text</b>");
if (D.problems.length)
  $("problems").innerHTML = `<div class="warn"><b>Problems in the state directory</b><ul style="margin:4px 0 0 18px;padding:0">` +
    D.problems.map(p => `<li>${esc(p)}</li>`).join("") + "</ul></div>";
$("chips").innerHTML = D.statuses.filter(s => counts[s]).map(s =>
  `<button class="chip" data-s="${esc(s)}">${esc(s)} <b>${counts[s]}</b></button>`).join("");
$("chips").onclick = e => {
  const b = e.target.closest("button[data-s]"); if (!b) return;
  $("fStatus").value = b.dataset.s; showTab("all"); renderAll();
};
if (D.claims.length)
  $("claims").innerHTML = `<div class="panel"><h2>Being audited now</h2><table><thead><tr><th>File</th><th>Session</th><th>Claimed</th><th>Expires</th></tr></thead><tbody>` +
    D.claims.map(c => `<tr><td>${fileLink(c.path)}</td><td class="mono">${esc(c.session)}</td><td>${esc(fmtDate(c.claimed))}</td><td>${esc(fmtDate(c.expires))}</td></tr>`).join("") +
    "</tbody></table></div>";

// ---------- review queue ----------
function queueRows(ids, numbered) {
  return ids.map((id, i) => {
    const f = byId[id];
    return `<tr data-id="${esc(id)}">${numbered ? `<td class="n">${i + 1}</td>` : ""}<td class="id">${esc(id)}</td>` +
      `<td>${title(f.title)}</td><td>${sev(f.severity)}</td><td>${esc(f.complexity_note || f.complexity || "—")}</td>` +
      `<td class="mono">${esc(f.branch || "—")}</td><td>${list(f.depends_on).map(esc).join(", ") || "—"}</td>` +
      `<td class="q">${esc(f.questions_for_andrew || "")}</td></tr>`;
  }).join("");
}
function renderQueue() {
  const parked = D.findings.filter(f => f.status === "parked")
    .sort((a, b) => (sevRank[a.severity] ?? 9) - (sevRank[b.severity] ?? 9) || a.id.localeCompare(b.id)).map(f => f.id);
  const accepted = D.findings.filter(f => f.status === "accepted" || f.status === "pr-open")
    .sort((a, b) => (sevRank[a.severity] ?? 9) - (sevRank[b.severity] ?? 9) || a.id.localeCompare(b.id));
  const head = numbered => `<thead><tr>${numbered ? "<th>#</th>" : ""}<th>Finding</th><th>Title</th><th>Severity</th><th>Complexity</th><th>Branch</th><th>Depends on</th><th>Questions</th></tr></thead>`;
  $("tab-queue").innerHTML =
    `<div class="panel"><h2>Ready for review <span class="sub">— easiest first, stacked branches after their parents (${D.queue.length})</span></h2>` +
    (D.queue.length ? `<div class="scroll"><table>${head(true)}<tbody>${queueRows(D.queue, true)}</tbody></table></div>` : '<div class="empty">Nothing waiting.</div>') + "</div>" +
    `<div class="panel"><h2>Parked: needs your decision <span class="sub">(${parked.length})</span></h2>` +
    (parked.length ? `<div class="scroll"><table>${head(false)}<tbody>${queueRows(parked, false)}</tbody></table></div>` : '<div class="empty">Nothing parked.</div>') + "</div>" +
    `<div class="panel"><h2>Accepted / PR open <span class="sub">(${accepted.length})</span></h2>` +
    (accepted.length ? `<div class="scroll"><table><thead><tr><th>Finding</th><th>Title</th><th>Status</th><th>Severity</th><th>PR</th><th>Updated</th></tr></thead><tbody>` +
      accepted.map(f => `<tr data-id="${esc(f.id)}"><td class="id">${esc(f.id)}</td><td>${title(f.title)}</td><td>${status(f.status)}</td><td>${sev(f.severity)}</td><td>${prLink(f.pr)}</td><td class="n">${esc(fmtDate(f.updated))}</td></tr>`).join("") +
      "</tbody></table></div>" : '<div class="empty">None.</div>') + "</div>";
}

// ---------- all findings ----------
const opt = (vals, all) => `<option value="">${all}</option>` + vals.map(v => `<option>${esc(v)}</option>`).join("");
$("fStatus").innerHTML = `<option value="">any</option><option value="@open">open (needs attention)</option>` + D.statuses.map(v => `<option>${esc(v)}</option>`).join("");
$("fSev").innerHTML = opt(D.severities, "any");
$("fCat").innerHTML = opt(D.categories, "any");
const sortState = {key:"id", dir:1};
const COLS = [
  ["id", "Finding"], ["title", "Title"], ["status", "Status"], ["severity", "Severity"], ["category", "Category"],
  ["files", "Files"], ["pr", "PR"], ["updated", "Updated"],
];
function sortKey(f, k) {
  if (k === "severity") return sevRank[f.severity] ?? 9;
  if (k === "status") return D.statuses.indexOf(f.status);
  if (k === "files") return list(f.files).join(" ");
  if (k === "pr") return f.pr ? +f.pr : 1e9;
  return String(f[k] ?? "");
}
function renderAll() {
  const q = $("q").value.trim().toLowerCase(), st = $("fStatus").value, sv = $("fSev").value, ct = $("fCat").value;
  let rows = D.findings.filter(f =>
    (!st || (st === "@open" ? D.open_statuses.includes(f.status) : f.status === st)) &&
    (!sv || f.severity === sv) && (!ct || f.category === ct) &&
    (!q || [f.id, f.title, f.branch, f.questions_for_andrew, list(f.files).join(" "), f.body].join("\n").toLowerCase().includes(q)));
  rows.sort((a, b) => { const x = sortKey(a, sortState.key), y = sortKey(b, sortState.key); return (x < y ? -1 : x > y ? 1 : 0) * sortState.dir; });
  $("count").textContent = `${rows.length} of ${D.findings.length}`;
  $("all").innerHTML = `<thead><tr>${COLS.map(([k, l]) => `<th data-k="${k}">${l}${sortState.key === k ? (sortState.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(f => `<tr data-id="${esc(f.id)}"><td class="id">${esc(f.id)}</td><td>${title(f.title)}</td><td>${status(f.status)}</td>` +
      `<td>${sev(f.severity)}</td><td>${esc(f.category || "—")}</td>` +
      `<td class="mono">${list(f.files).slice(0, 3).map(esc).join("<br>")}${list(f.files).length > 3 ? `<br>… ${list(f.files).length - 3} more` : ""}</td>` +
      `<td>${prLink(f.pr)}</td><td class="n">${esc(String(f.updated || "").slice(0, 10))}</td></tr>`).join("") + "</tbody>";
}
$("all").addEventListener("click", e => {
  const th = e.target.closest("th[data-k]");
  if (th) { sortState.dir = sortState.key === th.dataset.k ? -sortState.dir : 1; sortState.key = th.dataset.k; renderAll(); }
});
for (const id of ["q", "fStatus", "fSev", "fCat"]) $(id).addEventListener("input", renderAll);

// ---------- runs and coverage ----------
function md(text) {
  if (!haveMd) return `<pre class="raw">${esc(text)}</pre>`;
  let html = DOMPurify.sanitize(marked.parse(text, {gfm:true}));
  // Link finding identifiers (outside existing links and code) to their detail view.
  const tmp = document.createElement("div"); tmp.innerHTML = html;
  const walker = document.createTreeWalker(tmp, NodeFilter.SHOW_TEXT);
  const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes) {
    if (!/F-\d{4}/.test(n.nodeValue) || n.parentElement.closest("a,code,pre")) continue;
    const span = document.createElement("span");
    span.innerHTML = esc(n.nodeValue).replace(/\bF-\d{4,}\b/g, id => byId[id] ? `<a href="#${id}">${id}</a>` : id);
    n.replaceWith(...span.childNodes);
  }
  for (const a of tmp.querySelectorAll("a[href]")) {
    const m = a.getAttribute("href").match(/(?:^|\/)(F-\d{4,})\.md$/);
    if (m) a.setAttribute("href", "#" + m[1]);
    else if (!a.getAttribute("href").startsWith("#")) { a.target = "_blank"; a.rel = "noopener"; }
  }
  return tmp.innerHTML;
}
function renderRuns() {
  $("tab-runs").innerHTML = `<div class="panel"><h2>Latest run logs <span class="sub">(${D.runs.length})</span></h2>` +
    (D.runs.length ? D.runs.map((r, i) => `<details class="run"${i === 0 ? " open" : ""}><summary><b class="mono">${esc(r.name)}</b> ` +
      `<span class="sub">· modified ${esc(fmtDate(r.modified))} · ${esc((r.text.split("\n")[0] || "").slice(0, 140))}</span></summary>` +
      `<div class="md">${md(r.text)}</div></details>`).join("") : '<div class="empty">No run logs.</div>') + "</div>";
}
function renderCoverage() {
  const c = D.coverage;
  $("tab-coverage").innerHTML = `<div class="grid2"><div class="panel"><h2>Files reviewed, by lens <span class="sub">(${c.files} distinct files in any lens)</span></h2>` +
    `<table><thead><tr><th>Lens</th><th>Full</th><th>Skim</th><th>Latest review</th></tr></thead><tbody>` +
    Object.entries(c.lenses).map(([l, v]) => `<tr><td>${esc(l)}</td><td class="n">${v.full}</td><td class="n">${v.skim}</td><td class="n">${esc(fmtDate(v.last))}</td></tr>`).join("") +
    `</tbody></table></div><div class="panel"><h2>Recent sessions</h2><table><thead><tr><th>Session</th><th>Files</th><th>Lenses</th><th>Findings</th><th>Last record</th></tr></thead><tbody>` +
    c.sessions.map(s => `<tr><td class="mono">${esc(s.session)}</td><td class="n">${s.files}</td><td>${s.lenses.map(esc).join(", ")}</td>` +
      `<td>${s.findings.map(id => byId[id] ? `<a href="#${id}">${id}</a>` : esc(id)).join(" ") || "—"}</td><td class="n">${esc(fmtDate(s.last))}</td></tr>`).join("") +
    "</tbody></table></div></div>";
}

// ---------- detail ----------
function showDetail(id) {
  const f = byId[id];
  if (!f) { $("detail").classList.remove("on"); return; }
  const row = (k, v) => v ? `<span>${k}</span><span>${v}</span>` : "";
  const deps = list(f.depends_on).map(d => byId[d] ? `<a href="#${d}">${d}</a>` : esc(d)).join(", ");
  const dl = f.diff_lines ? `${f.diff_lines.source ?? "?"} source / ${f.diff_lines.tests ?? "?"} tests` : "";
  $("sheet").innerHTML = `<button class="close" aria-label="Close" onclick="location.hash=''">×</button>` +
    `<div class="sub">${esc(f.id)}</div><h1 style="font-size:18px;margin:2px 0 6px">${title(f.title)}</h1>` +
    `<div>${status(f.status)} ${sev(f.severity)} <span class="sub">· ${esc(f.confidence || "")} · ${esc(f.category || "")}</span></div>` +
    (f.questions_for_andrew ? `<div class="question"><b>Question:</b> ${esc(f.questions_for_andrew)}</div>` : "") +
    `<div class="meta">` +
      row("Files", list(f.files).map(fileLink).join("<br>")) +
      row("Complexity", esc(f.complexity_note || f.complexity || "")) +
      row("Branch", f.branch ? `<code>${esc(f.branch)}</code>${f.head ? ` @ <code>${esc(f.head)}</code>` : ""}${f.base ? ` <span class="sub">(base <code>${esc(f.base)}</code>)</span>` : ""}` : "") +
      row("Diff", esc(dl)) +
      row("Depends on", deps) +
      row("PR", f.pr ? prLink(f.pr) : "") +
      row("Reference models", f.affects_reference_models == null ? "" : (f.affects_reference_models ? "<b>affected</b>" : "not affected")) +
      row("Review rounds", f.review_rounds ? esc(f.review_rounds) : "") +
      row("Found by", esc(f.found_by || "")) +
      row("Plan item", esc(f.plan_id || "")) +
      row("Created / updated", `${esc(fmtDate(f.created))} / ${esc(fmtDate(f.updated))}`) +
    `</div><div class="md">${md(f.body || "")}</div>`;
  $("detail").classList.add("on");
  $("sheet").scrollTop = 0;
}
$("detail").addEventListener("click", e => { if (e.target.id === "detail") location.hash = ""; });
addEventListener("keydown", e => { if (e.key === "Escape" && $("detail").classList.contains("on")) location.hash = ""; });
document.addEventListener("click", e => {
  if (e.target.closest("a")) return;
  const tr = e.target.closest("tr[data-id]"); if (tr) location.hash = tr.dataset.id;
});
addEventListener("hashchange", () => showDetail(location.hash.slice(1)));

// ---------- tabs ----------
function showTab(t) {
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("on", b.dataset.t === t);
  for (const s of ["queue", "all", "runs", "coverage"]) $("tab-" + s).hidden = s !== t;
  try { localStorage.setItem("auditTab", t); } catch (e) {}
}
$("tabs").onclick = e => { const b = e.target.closest("button[data-t]"); if (b) showTab(b.dataset.t); };

renderQueue(); renderAll(); renderRuns(); renderCoverage();
let initial = "queue"; try { initial = localStorage.getItem("auditTab") || "queue"; } catch (e) {}
showTab(initial);
if (location.hash.length > 1) showDetail(location.hash.slice(1));
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
