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

### `convertLimongiChieffi2018.py`

Converts the Limongi & Chieffi (2018; ApJS; 237; 13) massive star models — 13–120 M☉ at four metallicities
([Fe/H] = 0, −1, −2, −3, i.e. Z = 1.345×10⁻² down to 3.24×10⁻⁵) and three initial rotation velocities — writing
one file per explosion set and rotation velocity:

```
./convertLimongiChieffi2018.py                          # sets M and R, all three rotation velocities
./convertLimongiChieffi2018.py --sets M --velocities 0
```

Data are assembled from two sources. ORFEO (<http://orfeo.iaps.inaf.it>) supplies the yields and remnant masses;
the CDS copy of the paper's Table 5 (`J/ApJS/237/13`) supplies stellar lifetimes, which ORFEO does not tabulate.
Source tables are cached under `--cache-directory` so that repeated runs do not re-download them.

Four things about the source data are worth knowing, all handled by the script:

- ORFEO tabulates **net** elemental yields directly (`tab_yieldsnet_ele_exp.dec`), which is already Galacticus'
  convention — no conversion is needed.
- Despite the `exp` in the file name, those tables are the **total** ejecta, not the explosive component alone.
  Their gross counterparts sum to exactly the initial mass minus the remnant mass, wind included; the script
  asserts this for every model.
- Table 5 gives the duration of **each evolutionary phase**, so the lifetime is their sum. Models stopped early
  pad the table to eight rows by repeating the final `PSN` row, so phases must be de-duplicated first —
  otherwise the lifetime of the 120 M☉, [Fe/H] = −3, 300 km/s model is overstated by 35%.
- Twelve models per set enter the (pulsational) pair instability regime, are flagged with a remnant mass of −1,
  and had their evolution stopped early. They are excluded, and named in each file's provenance.

**Explosion sets.** The four sets differ *only* in which stars explode, and this dominates the high-mass yields:
in sets I and R everything above 25 M☉ collapses entirely, so only the wind is ejected and the net metal yield
falls to ≈ 0 above 30 M☉, while sets F and M eject 0.07 M☉ of ⁵⁶Ni from every model. Sets M and R are converted
by default because they bracket that uncertainty.

#### Sanity check

Compared with Portinari, Chiosi & Bressan (1998) at near-solar metallicity, lifetimes agree to 2–8% and ejected
mass fractions to a few per cent across 13–120 M☉ — about what two independent stellar evolution codes should
give. Metal yields differ more (Limongi & Chieffi are roughly 50% higher above 40 M☉), which is expected: yields
are far more model-dependent than lifetimes.

### `splitPortinariChiosiBressan1998.py`

Splits the Portinari, Chiosi & Bressan (1998) file into its lifetime (0.6–120 M☉) and yield (9–120 M☉)
components. The two are carried by disjoint `star` elements, so the split is lossless — the script checks that no
entry carries both, and the two halves together reproduce the original exactly.

```
./splitPortinariChiosiBressan1998.py
```

This is needed because a compilation built around Limongi & Chieffi (2018) wants Portinari's *lifetimes*, which
reach down to 0.6 M☉, but must not also take Portinari's *yields*, which would overlap the Limongi & Chieffi
models and leave the interpolation blending two mutually inconsistent sets of stellar models over the same part
of the (mass, metallicity) plane. The standard compilation simply includes both halves and is unaffected —
verified by confirming that a model run is bit-identical before and after the split.

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
