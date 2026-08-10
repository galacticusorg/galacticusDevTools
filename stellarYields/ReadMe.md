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

### `convertSukhbold2016.py`

Converts the Sukhbold et al. (2016; ApJ; 821; 38) core-collapse supernova models — 200 models spanning
9–120 M☉ on a grid far denser than any alternative (0.1 M☉ steps between 13 and 27 M☉), with a physically
motivated prescription for which stars explode — writing one file per explosion engine:

```
./convertSukhbold2016.py                    # W18 and N20 engines
./convertSukhbold2016.py --engines W18
```

Each engine's 200-model set is assembled from three directories in the Garching archive: the Z9.6 calibration
for 9.0–12.0 M☉, that engine's exploding models above, and — for the masses that do *not* explode under it — the
wind-only imploding models. Those are tabulated only for W18, but a star that collapses entirely ejects only its
wind, which is set by the progenitor's mass loss and not by the engine, so the same tables apply to N20.

Three features of the source tables would each corrupt the result silently, and are handled:

- Each table ends with a block of **20 radioactive isotopes** which is *supplementary* — the stable block above
  already contains their decay products, so summing the whole file double-counts. This is checkable directly:
  for the 20.1 M☉ W18 model the ejected `fe56` is 0.106 M☉, far above the ~0.018 M☉ expected if unprocessed, and
  consistent with the birth abundance plus the 0.0906 M☉ of `ni56` listed separately. Note `k40` appears in
  **both** blocks, so reading the file into a dict keyed on isotope silently loses the stable entry.
- The **imploding models have one data column** (wind) where exploding models have two (ejecta, wind).
- The **14.0 M☉ tables are truncated**, missing the ~95 heaviest stable isotopes. Those elements are omitted
  rather than written as zero: a zero *gross* yield converts to a large negative *net* yield, spuriously
  implying destruction. Galacticus pads elements missing from a star with zero net yield, which is correct.

Gross yields are converted to net by subtracting the birth composition — the Lodders (2003) protosolar mixture
used by the KEPLER progenitors, taken from the copy bundled with VICE. That it sums to X = 0.7111, Y = 0.2740,
Z = 0.0149438 confirms the identification, and the script rejects a composition implying an implausible X.

#### These files do not yet work in a model

The converted data are correct — their IMF-weighted metal yield is 0.0156 against 0.0290 for Portinari, Chiosi &
Bressan (1998), exactly as expected when roughly half the models collapse entirely, and the characteristic
interleaved islands of explodability are reproduced (99 of 200 models eject only their wind).

But because every model sits at a **single metallicity**, the point set handed to the irregular two-dimensional
interpolation in `stellarAstrophysicsFile` is degenerate, and the interpolation returns unusable values. A test
model gives 11.4× the expected metal yield when combined with Heger & Woosley (2002), zero without it, and
crashes inside the IMF integration when the grid is thinned. Thinning not helping is the point: this is the
single metallicity, not the grid density. Using these models needs a `stellarAstrophysics` implementation that
interpolates in mass alone at fixed metallicity. No compilation file is shipped for them until then.

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

### `convertSeitenzahl2013.py`

Converts the Seitenzahl et al. (2013; MNRAS; 429; 1156) three-dimensional delayed-detonation models — fourteen
Chandrasekhar-mass models at Solar metallicity, spanning ignition configurations from N1 to N1600 — writing one
file per model, plus a metallicity-dependent file:

```
./convertSeitenzahl2013.py                     # all fourteen models and the N100 sequence
./convertSeitenzahl2013.py --no-sequence
```

The paper also post-processed the N100 model at one-half, one-tenth and one-hundredth of the canonical
metallicity. Together with N100 itself that gives **four metallicities for one and the same explosion model**,
which is what the metallicity-dependent format wants: the trend is not confounded by a change of explosion
model. The script writes those four sets into a single
`Supernovae_Type_Ia_Yields_Seitenzahl2013_N100_MetallicityDependent.xml`.

**Metallicity scale.** The paper parameterizes progenitor metallicity through the ²²Ne mass fraction, adopting
0.025 for the Solar case, and states the approximation that all metals begin as CNO and are processed to ¹⁴N and
then ²²Ne during core helium burning. Under that assumption Z = (14/22)·X(²²Ne), which is what is used here and
puts the Solar model at Z = 0.0159. Taking the scale from the paper's own assumption avoids imposing an
external — and inevitably inconsistent — value of the Solar metallicity.

#### Sanity check

Every model totals ≈1.40 M☉, as it must when a Chandrasekhar-mass white dwarf burns essentially completely, so
the total is *not* a useful discriminator. The physics is in the composition, and across the metallicity
sequence it behaves exactly as the neutron excess from ²²Ne implies: nickel rises 33% and manganese 18% with
increasing metallicity, while the alpha element calcium falls 17%, and iron, silicon and carbon stay flat. A
conversion that leaves the composition flat across the sequence is wrong.

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
