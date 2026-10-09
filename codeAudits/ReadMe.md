# Code audits

Static analyses of a Galacticus checkout which look for inconsistencies across the code base.
Both are heuristic: their findings are meant to be reviewed, not applied blindly.

### `classContractSweep.py`

Sweeps a Galacticus checkout for ways in which implementations of one
`functionClass` can disagree with each other or with their consumers, and writes
the full findings to `classContractSweep.json` in the working directory. It
reports five kinds of finding:

* **C1 — optional-argument contracts.** The constraints a method's base `<code>`
  imposes, the arguments individual implementations require (either by an
  explicit `Error_Report` or, marked `*`, inferred from an unguarded use), and
  the consumer call sites which violate the base contract or omit an argument
  some implementation needs.
* **C2 — capability stubs.** Methods whose override in some implementation only
  raises a "not supported" error, together with the consumers which call that
  method on the generic class.
* **C3 — null-default hazards.** Classes whose default implementation is `null`,
  where a consumer calls a method the null implementation answers with an error
  or a `huge()` sentinel.
* **C4 — inherited base defaults.** Methods with base-class default code, and
  which implementations inherit it rather than overriding.
* **C5 — parameter-convention drift.** Within one class: same-named parameters
  differing in type or in the units their descriptions give, and near-duplicate
  parameter names.

```
export GALACTICUS_EXEC_PATH=<dir>
./classContractSweep.py [<parameter-catalog>]
```

The catalog argument enables the C5 checks; build it with
`scripts/build/parameterCatalog.py`. Note that a catalog left in a checkout is
not tracked by git and so may predate the working tree, in which case C5 reports
a state that no longer exists — regenerate it before trusting those findings.

The analysis is regex-based rather than a full parse, so findings are heuristic
and meant to be reviewed rather than acted on blindly. Two specific classes of
false positive are known and worth recognising:

* A near-duplicate parameter pair whose names differ only by a trailing capital
  or acronym — `A`/`B`, `haloMassFunctionA`/`haloMassFunctionP`,
  `coefficient`/`coefficientISM` — is an artifact of how names are split into
  words, and is usually a set of distinct fitting coefficients rather than a
  duplicate.
* A C1 "omits argument" finding against a call site may instead be a capability
  mismatch with no call-site fix: the argument may not exist in that context at
  all, as for an analysis un-operator applied to bin centers after a run, or a
  halo mass function evaluated on a mass grid with no node.

Generic interfaces and calls through `associate` aliases are not resolved, so
consumer counts are lower bounds.

### `namingAudit.py`

Audits API naming consistency across a Galacticus checkout and writes the full
findings to `namingAudit.json`. It reports two kinds of finding:

* **Spelling** — US-spelling violations in Fortran identifiers, in documentation
  prose (`<description>` directive elements and `!!{RST ... !!}` blocks), in
  Python, and in parameter files. This complements the `Spell-Check-RST` CI job,
  which covers only the generated documentation and cannot see identifiers,
  Python, or parameter files.
* **Structural** — class and implementation name styles, vowel-stripped
  implementation-name abbreviations, parameter name style and word order,
  boolean parameters that do not read as predicates, methods that express one
  concept under two word orders, module and procedure name styles, hyphenated
  file names, and property-extractor output names.

```
./namingAudit.py [--repo <dir>] [--catalog <file>] [--spelling] [--structural]
```

`--repo` defaults to `$GALACTICUS_EXEC_PATH`. The structural scan needs the
parameter catalog; if it is not found, the script prints the
`scripts/build/parameterCatalog.py` command that builds it. `--spelling` runs
only the spelling scan, which needs no catalog and no build, and is the mode
intended for a lint job.

The conventions checked, and their deliberate exceptions (cosmological
parameters written as symbols, fitting-formula coefficients written as paper
symbols, `*IsFatal`/`*Only` booleans, legacy `Upper_Snake_Case` procedures), are
documented in the *Naming conventions* section of the Galacticus developer
guide. To keep the two consistent, the script honours `aux/words.dict` — the
dictionary the documentation spelling builder uses — so proper names recorded
there (people, codes, simulations) are not flagged.

Findings are heuristic and meant to be reviewed rather than applied blindly. In
particular, an adjective-first parameter name may be an established physics
term, and an extractor which composes its dataset name from a prefix (for
example `'darkMatterProfileDMO'//propertyName`) correctly has a capitalized name
literal; those are reported separately rather than as defects.
