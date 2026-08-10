#!/usr/bin/env python3
import os
import re
import sys
import argparse
from galacticusYieldTables import (AtomicData, Provenance, readViceSNIaModel, stellarAstrophysicsPath,
                                   viceRepoURL, viceRevision, viceSNIaPath, writeSupernovaeTypeIaYields,
                                   writeSupernovaeTypeIaYieldsMetallicityDependent)

# Convert the Gronow et al. (2021a, b) Type Ia supernova yields into the XML format read by Galacticus.
# Andrew Benson (10-August-2026); generated with assistance from Claude.

# Gronow et al. (2021a; A&A; 649; A155) and (2021b; A&A; 656; A94) compute double detonations of
# sub-Chandrasekhar mass carbon-oxygen white dwarfs with a helium shell: a helium detonation ignites at the base
# of the shell and triggers a second detonation in the core. Eleven combinations of core and shell mass are each
# computed at four progenitor metallicities, giving 44 models. The Solar-metallicity models are from the 2021a
# paper and the rest from 2021b.
#
# Model names encode the core mass, the shell mass, and the metallicity relative to Solar: "M09_05_01" is a
# 0.9 Msun core with a 0.05 Msun helium shell at 0.1 Z_Solar.
#
# This script writes one file per model, and additionally one metallicity-dependent file per core/shell
# combination, tabulating that combination's four metallicities in a single table.
#
# Metallicity scale. These papers quote their metallicities relative to Solar, and cite Asplund et al. (2009)
# for the Solar composition, whose bulk Solar metal mass fraction is Z = 0.0142. That is the value used here to
# place the models on an absolute scale, so the scale is the papers' own rather than an imposed one.
#
# Note that this is deliberately NOT the Solar metallicity Galacticus itself uses (0.0188, from Allen's
# Astrophysical Quantities), nor the value used for the Seitenzahl et al. (2013) files (0.0159, which follows
# from that paper's stated 22Ne mass fractions). Each set of yields is placed on the scale its own authors
# adopted, which is what makes the tabulated metallicities mean what the papers intended; the differences
# between those scales are real differences of convention between the papers, not artefacts of the conversion.
# Use --solar-metallicity to override; the value used is recorded in every file's provenance.
#
# A further caveat, raised in the discussion on galacticusorg/galacticus#500, is that the treatment of iron in
# these calculations limits how quantitatively their metallicity trends should be read. This has not been
# verified against the papers here, and is noted in the provenance so that it travels with the data.

paperURLa = "https://ui.adsabs.harvard.edu/abs/2021A%26A...649A.155G"
paperURLb = "https://ui.adsabs.harvard.edu/abs/2021A%26A...656A..94G"
study     = "gronow21"

# The bulk Solar metal mass fraction of Asplund et al. (2009), which is the Solar composition these papers cite.
metallicitySolarDefault = 0.0142

# Metallicity suffixes used in the model names, as multiples of the Solar metallicity.
metallicitySuffixes = {"001": 0.01, "01": 0.1, "1": 1.0, "3": 3.0}

def parseModelName(model):
    """Split a model name such as 'M09_05_01' into core mass, shell mass, and metallicity relative to Solar."""
    match = re.fullmatch(r'M(\d{2})_(\d{2})_(\d{1,3})', model)
    if match is None:
        raise ValueError(f"unable to parse model name '{model}'")
    coreMass  = int(match.group(1))/10.0
    shellMass = int(match.group(2))/100.0
    suffix    = match.group(3)
    if suffix not in metallicitySuffixes:
        raise ValueError(f"unrecognized metallicity suffix '{suffix}' in model name '{model}'")
    return coreMass, shellMass, metallicitySuffixes[suffix]

def describe(coreMass, shellMass):
    return (f"a {coreMass:.1f} Msun carbon-oxygen core with a {shellMass:.2f} Msun helium shell")

def absoluteMetallicity(relative, metallicitySolar):
    """Place a metallicity quoted relative to Solar on an absolute scale.

    The product is rounded to twelve significant figures. Without this, 0.1 x 0.0142 writes out as
    0.0014200000000000003 -- the shortest decimal which reproduces that double exactly, and so what the lossless
    value formatting faithfully emits. The trailing digits are an artefact of binary representation rather than
    anything meaningful, and rounding them away costs nothing physically while keeping the tables readable."""
    return float(f"{relative*metallicitySolar:.12g}")

def notes(metallicitySolar, relative=None):
    common = ["Yields are gross masses of each isotope ejected, in Solar masses.",
              "Hydrogen and helium are excluded: the Galacticus reader sums all isotopes present to form the "
              "total metal yield.",
              f"Metallicities are quoted by the papers relative to Solar, and have been placed on an absolute "
              f"scale using Z_Solar = {metallicitySolar}. The papers cite Asplund et al. (2009) for the Solar "
              "composition, whose bulk Solar metal mass fraction is 0.0142, so this is the papers' own scale. "
              "It is deliberately not the Solar metallicity Galacticus itself uses (0.0188), nor that of the "
              "Seitenzahl et al. (2013) files (0.0159, from that paper's stated 22Ne mass fractions): each set "
              "of yields is placed on the scale its own authors adopted.",
              "The treatment of iron in these calculations limits how quantitatively their metallicity trends "
              "should be read; see the discussion on galacticusorg/galacticus issue 500."]
    if relative is not None:
        common.insert(2, f"Progenitor metallicity is {relative:g} times Solar.")
    return common

def convertModel(model, source, outputDirectory, atomicData, cache, metallicitySolar):
    coreMass, shellMass, relative = parseModelName(model)
    isotopes, origin = readViceSNIaModel(study, model, atomicData, source=source, cache=cache)
    paperURL = paperURLa if relative == 1.0 else paperURLb
    paper    = "Gronow et al. (2021a, A&A, 649, A155)" if relative == 1.0 \
               else "Gronow et al. (2021b, A&A, 656, A94)"
    provenance = Provenance(
        scienceSource       = f"{paper}, model {model}",
        scienceURL          = paperURL,
        transcriptionSource = f"VICE (Johnson 2019), MIT licensed, revision {viceRevision}",
        transcriptionURL    = viceRepoURL,
        generatedBy         = "galacticusDevTools/stellarYields/convertGronow2021.py",
        inputs              = [origin],
        notes               = notes(metallicitySolar, relative),
    )
    fileName = os.path.join(outputDirectory, f"Supernovae_Type_Ia_Yields_Gronow2021_{model}.xml")
    writeSupernovaeTypeIaYields(
        fileName    = fileName,
        isotopes    = isotopes,
        description = (f"Yields for Type Ia supernovae from the double detonation of {describe(coreMass, shellMass)} "
                       f"at {relative:g} times Solar metallicity, from {paper}. Yields are given as the mass "
                       "(in Solar masses) of each isotope produced."),
        source      = f"{paper}; Model {model}",
        url         = paperURL,
        provenance  = provenance,
    )
    return fileName, sum(isotope['yield'] for isotope in isotopes)

def convertSequence(coreMass, shellMass, models, source, outputDirectory, atomicData, cache, metallicitySolar):
    yieldSets = []
    origins   = []
    for model in models:
        _, _, relative   = parseModelName(model)
        isotopes, origin = readViceSNIaModel(study, model, atomicData, source=source, cache=cache)
        yieldSets.append((absoluteMetallicity(relative, metallicitySolar), isotopes))
        origins  .append(origin)
    label      = f"M{int(coreMass*10):02d}_{int(shellMass*100):02d}"
    provenance = Provenance(
        scienceSource       = (f"Gronow et al. (2021a, A&A, 649, A155; Solar metallicity) and (2021b, A&A, 656, "
                               f"A94; remaining metallicities), {describe(coreMass, shellMass)}"),
        scienceURL          = paperURLb,
        transcriptionSource = f"VICE (Johnson 2019), MIT licensed, revision {viceRevision}",
        transcriptionURL    = viceRepoURL,
        generatedBy         = "galacticusDevTools/stellarYields/convertGronow2021.py",
        inputs              = origins,
        notes               = notes(metallicitySolar)+[
                               "Only the progenitor metallicity differs between these sets; the core and shell "
                               "masses are the same throughout.",
                               "Galacticus interpolates linearly in metallicity between these sets, and holds "
                               "the yield constant beyond the tabulated range."],
    )
    fileName = os.path.join(outputDirectory,
                            f"Supernovae_Type_Ia_Yields_Gronow2021_{label}_MetallicityDependent.xml")
    writeSupernovaeTypeIaYieldsMetallicityDependent(
        fileName    = fileName,
        yieldSets   = yieldSets,
        description = (f"Metallicity-dependent yields for Type Ia supernovae from the double detonation of "
                       f"{describe(coreMass, shellMass)}, from Gronow et al. (2021a, b), tabulated at four "
                       "progenitor metallicities. Yields are given as the mass (in Solar masses) of each "
                       "isotope produced."),
        source      = ("Gronow et al. (2021a, A&A, 649, A155) and (2021b, A&A, 656, A94); "
                       f"{describe(coreMass, shellMass)}, four progenitor metallicities"),
        url         = paperURLb,
        provenance  = provenance,
    )
    return fileName

def main():
    parser = argparse.ArgumentParser(description="Convert Gronow et al. (2021a, b) Type Ia supernova yields to "
                                                 "Galacticus XML format.")
    parser.add_argument("--solar-metallicity", type=float, default=metallicitySolarDefault,
                        dest="metallicitySolar",
                        help="the Solar metal mass fraction used to place the papers' relative metallicities on "
                             f"an absolute scale (default: {metallicitySolarDefault}, the bulk Solar value of "
                             "Asplund et al. 2009, which is the composition these papers cite)")
    parser.add_argument("--no-sequences", action="store_true", dest="noSequences",
                        help="skip the metallicity-dependent files")
    parser.add_argument("--source", default=None,
                        help="path to a local VICE 'vice/yields/sneia/gronow21' directory; if omitted the "
                             "tables are downloaded from GitHub at the pinned revision")
    parser.add_argument("--cache-directory", default="viceData", dest="cacheDirectory",
                        help="directory in which the downloaded VICE archive is cached")
    parser.add_argument("--output-directory", default=None, dest="outputDirectory",
                        help="directory into which to write (default: "
                             "${GALACTICUS_DATA_PATH}/static/stellarAstrophysics)")
    arguments       = parser.parse_args()
    outputDirectory = arguments.outputDirectory if arguments.outputDirectory is not None \
                      else stellarAstrophysicsPath()
    source          = arguments.source if arguments.source is not None \
                      else os.path.join(viceSNIaPath(arguments.cacheDirectory), study)
    atomicData = AtomicData()
    cache      = {}

    # Enumerate the models present, and group them by core and shell mass.
    models = sorted(name for name in os.listdir(source)
                    if os.path.isdir(os.path.join(source, name)) and re.fullmatch(r'M\d{2}_\d{2}_\d{1,3}', name))
    if not models:
        raise RuntimeError(f"no Gronow models found in '{source}'")
    combinations = {}
    for model in models:
        coreMass, shellMass, _ = parseModelName(model)
        combinations.setdefault((coreMass, shellMass), []).append(model)

    print(f"Writing Gronow et al. (2021a, b) Type Ia yields to {outputDirectory}")
    print(f"  assuming Z_Solar = {arguments.metallicitySolar}")
    for model in models:
        _, total = convertModel(model, source, outputDirectory, atomicData, cache, arguments.metallicitySolar)
        print(f"  {model:12s}: total metal yield {total:.4f} Msun")
    if not arguments.noSequences:
        print(f"Metallicity-dependent files ({len(combinations)} core/shell combinations):")
        for (coreMass, shellMass), group in sorted(combinations.items()):
            group = sorted(group, key=lambda name: parseModelName(name)[2])
            fileName = convertSequence(coreMass, shellMass, group, source, outputDirectory, atomicData, cache,
                                       arguments.metallicitySolar)
            print(f"  core {coreMass:.1f} Msun, shell {shellMass:.2f} Msun: {len(group)} metallicities "
                  f"-> {os.path.basename(fileName)}")

if __name__ == "__main__":
    sys.exit(main())
