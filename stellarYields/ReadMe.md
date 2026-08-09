# Stellar yield table converters

Scripts that convert published stellar nucleosynthesis yield tables into the XML formats read by
[Galacticus](https://github.com/galacticusorg/galacticus), and write them into the
[datasets](https://github.com/galacticusorg/datasets) repository.

These exist so that alternative yield sets can be added — and *regenerated* — reproducibly. Before these
scripts, the yield files under `static/stellarAstrophysics/` in the datasets repository had been built by hand,
with no record of which upstream table or which model variant they came from. Every file written here carries a
provenance comment recording the science source, the transcription source (where the numbers were read from a
redistribution rather than the paper), the retrieval date, the exact input files, and the script that produced
it.

See [galacticusorg/galacticus#500](https://github.com/galacticusorg/galacticus/issues/500) for the survey of
candidate yield sets and the staged plan these scripts implement.

## Requirements

- Python 3, standard library only (no third-party packages).
- `GALACTICUS_DATA_PATH` set to a checkout of the datasets repository. This is used both to locate the output
  directory and to read `static/abundances/Atomic_Data.xml`, which supplies the element symbol ↔ atomic number
  mapping. Reading Galacticus' own atomic data (rather than an independent periodic table) guarantees the
  `elementYieldMass<X>` tags we write are exactly the short labels `Atomic_Short_Label()` looks for at run time.

## The two file formats

`galacticusYieldTables.py` is a shared module — not a script — providing the writers for both formats Galacticus
reads, plus the atomic data lookup and provenance record. The distinction between the two matters when adding a
new converter:

| Format | Written by | Read by | Convention |
|---|---|---|---|
| `<stars>` (stellar properties) | `writeStellarProperties()` | `stellarAstrophysicsFile` | Yields are **net** (newly synthesized minus destroyed, so they may be negative); `ejectedMass` is the **gross** mass returned |
| `<supernovaeYields>` (Type Ia) | `writeSupernovaeTypeIaYields()` | `supernovaeTypeIaFixedYield` | Yields are **gross** isotope masses; **metals only** |

Two traps worth knowing about, both enforced by the module:

- The Type Ia reader sums **every** isotope present in the file to form the total metal yield. Hydrogen and
  helium must therefore be excluded, or the total is meaningless. Pass isotope lists through `filterMetals()`;
  `writeSupernovaeTypeIaYields()` raises if any survive.
- Net yields in the `<stars>` format are legitimately negative for elements a star destroys, so do not clamp
  them at zero.

## Scripts

### `convertIwamoto1999.py`

Converts the Iwamoto et al. (1999; ApJS; 125; 439) Type Ia supernova yields — the deflagration models `W7` and
`W70` (their Table 3) and the delayed-detonation models `WDD1`, `WDD2`, `WDD3`, `CDD1` and `CDD2` (their
Table 4) — writing one file per model:

```
./convertIwamoto1999.py                            # all seven models
./convertIwamoto1999.py --models WDD2 CDD1         # selected models
./convertIwamoto1999.py --output-directory ./out   # somewhere other than GALACTICUS_DATA_PATH
./convertIwamoto1999.py --source /path/to/VICE/vice/yields/sneia/iwamoto99
```

The published tables are typeset only — there is no machine-readable version at CDS/VizieR — so by default the
script reads the transcription bundled with [VICE](https://github.com/giganano/VICE) (MIT licensed), pinned to a
fixed commit so that a regenerated table is reproducible. Use `--source` to read from a local VICE checkout
instead of downloading.

The output files are selected at run time through the `fileName` parameter of the Galacticus `supernovaeTypeIa`
classes:

```xml
<supernovaeTypeIa value="powerLawDTD">
  <fileName value="%DATASTATICPATH%/stellarAstrophysics/Supernovae_Type_Ia_Yields_Iwamoto1999_WDD2.xml"/>
</supernovaeTypeIa>
```

Omitting `fileName` retains the previous default, the Nomoto et al. (1997) W7 yields in
`Supernovae_Type_Ia_Yields.xml`.

#### Sanity check

The `W7` model of Iwamoto et al. (1999) is a revision of the Nomoto et al. (1997) W7 model that Galacticus has
shipped by default. Converting it reproduces the same 66 isotopes with a total metal yield of 1.3708 M☉ against
1.3728 M☉ for the existing file. Element by element, everything from carbon to aluminium is *identical*, while
the iron-peak species differ by 10–45% — the expected signature of the revised electron-capture rates, which
change the iron-peak yields while leaving the products of explosive carbon, oxygen and silicon burning alone.
Iron itself agrees to 0.7%. A converter change that disturbs the light elements, or that moves iron by more than
a per cent or so, is wrong.
