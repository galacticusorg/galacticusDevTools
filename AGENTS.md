# AGENTS.md

Guidance for AI coding agents (Claude Code, Codex, Copilot, Gemini CLI, Cursor,
…) working in this repository; humans may find it useful too. Claude Code loads
it through `.claude/CLAUDE.md`, which imports it.

This repository holds development and maintenance utilities for
[Galacticus](https://github.com/galacticusorg/galacticus). It is not part of the
model. Most tools act on a separate Galacticus checkout, so the main
repository's own
[`AGENTS.md`](https://github.com/galacticusorg/galacticus/blob/master/AGENTS.md)
and `docs/agents/` apply whenever a tool builds, runs or edits Galacticus.

## Layout

Tools are grouped by purpose into top-level directories: `physicsReferences/`,
`codeAudits/`, `maintenance/`, `debugging/` and `dataPreparation/`. Each has a
`ReadMe.md`, which is the authoritative description of its tools: read it
before using or changing one. The top-level `ReadMe.md` is an index of them all.

## Running tools

- **Point a tool at a Galacticus checkout explicitly.** Tools that need one take
  it as an argument, or expect to be run from its root with
  `GALACTICUS_EXEC_PATH` exported to that root in the same command. Never
  assume a checkout is at a fixed path.
- **Some tools rewrite files in place** (`maintenance/GPLerize.py`,
  `maintenance/migrateAllParameterFiles.py`). Run them only on a clean tree, so
  that `git diff` shows exactly what they changed, and delete the `~`-suffixed
  backups that `GPLerize.py` leaves.
- **Some tools touch the machine or spend usage.** `debugging/runBenchmarks.sh`
  changes CPU-frequency settings through `sudo`; the scripts in
  `codeAudits/auditLoop/` start Claude Code sessions. Confirm with the user
  before running either.
- **`audit/*` branches** in a Galacticus checkout belong to the audit loop
  (`codeAudits/auditLoop/`). Leave them alone unless the user asks.

## Adding or changing a tool

- Put it in the directory that matches its purpose. Name scripts in camelCase
  (`exponentialDiskAccelerations.py`), and make them executable, with a
  `#!/usr/bin/env python3` (or `bash`) shebang.
- Start the script with a comment or docstring saying what it computes or does,
  which Galacticus code or test it supports, and the author line
  `Name (DD-Month-YYYY)`, as in `physicsReferences/promptCusps.py`. Where an AI
  tool contributed, add its bare name to the author line.
- Document it in two places: a `### scriptName` section in its directory's
  `ReadMe.md` (purpose, usage, requirements), and a one-line entry in the
  top-level `ReadMe.md`, under the right directory and subgroup.
- **Physics references** (`physicsReferences/`) are independent calculations
  that Galacticus unit tests cite by name, so they must stay independent: don't
  import Galacticus code or copy its numerical results. Do copy its *unit
  definitions* (see "Writing an independent reference for a test" in the
  Galacticus developer guide). If you change a reference's output, check the
  tests in `source/tests/` that cite it.
- Prefer the Python standard library plus numpy/scipy/h5py/lxml (which a
  Galacticus environment already has). Name any other requirement in the
  tool's `ReadMe.md` section.
- If a tool has tests, as `codeAudits/auditLoop/tests/` does, run them after a
  change (`python3 -m pytest <dir>`).
- Use US English spelling throughout, as Galacticus does.

## Commits and pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org)
  (`type(scope): summary`, with the types Galacticus allows: `fix`, `feat`,
  `build`, `chore`, `ci`, `docs`, `style`, `test`, `refactor`, `perf`,
  `revert`, `clean`).
- Work on a branch and open a pull request; don't push to `master`. A
  maintainer reviews and merges.
- Describe in the commit message what an AI tool contributed and how the result
  was verified, as Galacticus' `CONTRIBUTING.md` asks. All AI-generated work
  must be verified by a human before submission.
- Never commit data files, outputs or credentials. `.gitignore` excludes editor
  backups and `__pycache__/`; check `git status` for anything else before
  committing.
