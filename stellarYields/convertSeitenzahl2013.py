#!/usr/bin/env python3
import os
import sys
import argparse
from galacticusYieldTables import (AtomicData, Provenance, readViceSNIaModel, stellarAstrophysicsPath, viceSNIaPath,
                                   viceRepoURL, viceRevision, writeSupernovaeTypeIaYields,
                                   writeSupernovaeTypeIaYieldsMetallicityDependent)

# Convert the Seitenzahl et al. (2013) Type Ia supernova yields into the XML format read by Galacticus.
# Andrew Benson (09-August-2026); generated with assistance from Claude.

# Seitenzahl et al. (2013; MNRAS; 429; 1156) report the first suite of three-dimensional delayed-detonation
# models of Chandrasekhar-mass Type Ia supernovae with detailed isotopic yields: fourteen models at Solar
# metallicity spanning ignition configurations from N1 (a single ignition spot) to N1600, plus variants of the
# N100 model at reduced central density (N100L, N100H).
#
# They additionally post-processed N100 at one-half, one-tenth and one-hundredth of the canonical metallicity.
# Together with N100 itself that gives four metallicities for one and the same explosion model, which is exactly
# what is wanted to exercise the metallicity-dependent yield format: only the progenitor metallicity varies, so
# the resulting trend is not confounded by a change of explosion model. This script therefore writes both the
# individual per-model files and a single metallicity-dependent file for the N100 sequence.
#
# Metallicity scale. The paper parameterizes progenitor metallicity through the 22Ne mass fraction, adopting
# 0.025 for the Solar case (electron fraction Ye = 0.49886), and states the approximation that all metals in the
# zero-age main sequence progenitor are locked into CNO, which burns to 14N and then to 22Ne during core helium
# burning. Under that assumption the metal mass fraction follows as Z = (14/22) * X(22Ne), which is what is used
# here; it puts the Solar model at Z = 0.0159. Deriving the scale from the paper's own stated assumption avoids
# having to impose an external, and inevitably inconsistent, value of the Solar metallicity.

paperURL = "https://ui.adsabs.harvard.edu/abs/2013MNRAS.429.1156S"
study    = "seitenzahl13"

# The 22Ne mass fraction adopted for the Solar-metallicity models.
neon22Solar = 0.025

# Conversion from 22Ne mass fraction to metal mass fraction, following the paper's assumption that all metals
# begin as CNO and are processed to 22Ne.
def metallicityFromNeon22(neon22):
    return neon22*14.0/22.0

# The fourteen Solar-metallicity models, and the ignition configuration each represents.
models = {
    "N1"    : "a single ignition spot"                        ,
    "N3"    : "three ignition spots"                          ,
    "N5"    : "five ignition spots"                           ,
    "N10"   : "ten ignition spots"                            ,
    "N20"   : "twenty ignition spots"                         ,
    "N40"   : "forty ignition spots"                          ,
    "N100"  : "one hundred ignition spots"                    ,
    "N100H" : "one hundred ignition spots, high central density",
    "N100L" : "one hundred ignition spots, low central density" ,
    "N150"  : "one hundred and fifty ignition spots"          ,
    "N200"  : "two hundred ignition spots"                    ,
    "N300C" : "three hundred ignition spots, compact"         ,
    "N1600" : "sixteen hundred ignition spots"                ,
    "N1600C": "sixteen hundred ignition spots, compact"       ,
    # The reduced-metallicity variants of N100. These are also combined into a single metallicity-dependent
    # file below, but are written individually too so that a single progenitor metallicity can be selected.
    "N100_Z0P5" : "one hundred ignition spots, one-half Solar progenitor metallicity"      ,
    "N100_Z0P1" : "one hundred ignition spots, one-tenth Solar progenitor metallicity"     ,
    "N100_Z0P01": "one hundred ignition spots, one-hundredth Solar progenitor metallicity",
}

# The N100 metallicity sequence: model name against its 22Ne mass fraction, as a fraction of the Solar value.
metallicitySequence = {
    "N100"      : 1.00,
    "N100_Z0P5" : 0.50,
    "N100_Z0P1" : 0.10,
    "N100_Z0P01": 0.01,
}

def convertModel(model, source, outputDirectory, atomicData, cache):
    isotopes, origin = readViceSNIaModel(study, model, atomicData, source=source, cache=cache)
    provenance = Provenance(
        scienceSource       = f"Seitenzahl et al. (2013, MNRAS, 429, 1156), model {model}",
        scienceURL          = paperURL,
        transcriptionSource = f"VICE (Johnson 2019), MIT licensed, revision {viceRevision}",
        transcriptionURL    = viceRepoURL,
        generatedBy         = "galacticusDevTools/stellarYields/convertSeitenzahl2013.py",
        inputs              = [origin],
        notes               = ["Yields are gross masses of each isotope ejected, in Solar masses.",
                               "Hydrogen and helium are excluded: the Galacticus reader sums all isotopes "
                               "present to form the total metal yield."],
    )
    fileName = os.path.join(outputDirectory, f"Supernovae_Type_Ia_Yields_Seitenzahl2013_{model}.xml")
    writeSupernovaeTypeIaYields(
        fileName    = fileName,
        isotopes    = isotopes,
        description = ("Yields for Type Ia supernovae from the three-dimensional delayed-detonation model "
                       +model+" ("+models[model]+") of Seitenzahl et al. (2013). Yields are given as the mass "
                       "(in Solar masses) of each isotope produced."),
        source      = f"Seitenzahl et al. (2013, MNRAS, 429, 1156; Model {model})",
        url         = paperURL,
        provenance  = provenance,
    )
    total = sum(isotope['yield'] for isotope in isotopes)
    print(f"  {model:8s}: {len(isotopes):3d} isotopes, total metal yield {total:.4f} Msun")
    return fileName, total

def convertSequence(source, outputDirectory, atomicData, cache):
    yieldSets = []
    origins   = []
    for model, fraction in metallicitySequence.items():
        isotopes, origin = readViceSNIaModel(study, model, atomicData, source=source, cache=cache)
        metallicity      = metallicityFromNeon22(neon22Solar*fraction)
        yieldSets.append((metallicity, isotopes))
        origins  .append(origin)
        total = sum(isotope['yield'] for isotope in isotopes)
        print(f"  {model:11s} Z = {metallicity:.6f} (22Ne {neon22Solar*fraction:.5f}): "
              f"total metal yield {total:.4f} Msun")
    provenance = Provenance(
        scienceSource       = ("Seitenzahl et al. (2013, MNRAS, 429, 1156), model N100 post-processed at four "
                               "progenitor metallicities"),
        scienceURL          = paperURL,
        transcriptionSource = f"VICE (Johnson 2019), MIT licensed, revision {viceRevision}",
        transcriptionURL    = viceRepoURL,
        generatedBy         = "galacticusDevTools/stellarYields/convertSeitenzahl2013.py",
        inputs              = origins,
        notes               = ["Yields are gross masses of each isotope ejected, in Solar masses.",
                               "Hydrogen and helium are excluded: the Galacticus reader sums all isotopes "
                               "present to form the total metal yield.",
                               "Only the progenitor metallicity differs between these four sets; the explosion "
                               "model is the same N100 configuration throughout.",
                               "Metallicities follow from the 22Ne mass fractions of the paper (0.025 for the "
                               "Solar case, and one-half, one-tenth and one-hundredth of it) via "
                               "Z = (14/22) X(22Ne), which is the paper's own assumption that all metals begin "
                               "as CNO and are processed to 22Ne during core helium burning.",
                               "Galacticus interpolates linearly in metallicity between these sets, and holds "
                               "the yield constant beyond the tabulated range."],
    )
    fileName = os.path.join(outputDirectory, "Supernovae_Type_Ia_Yields_Seitenzahl2013_N100_MetallicityDependent.xml")
    writeSupernovaeTypeIaYieldsMetallicityDependent(
        fileName    = fileName,
        yieldSets   = yieldSets,
        description = ("Metallicity-dependent yields for Type Ia supernovae from the three-dimensional "
                       "delayed-detonation model N100 of Seitenzahl et al. (2013), post-processed at four "
                       "progenitor metallicities. Yields are given as the mass (in Solar masses) of each "
                       "isotope produced."),
        source      = "Seitenzahl et al. (2013, MNRAS, 429, 1156; Model N100, four progenitor metallicities)",
        url         = paperURL,
        provenance  = provenance,
    )
    print(f"    -> {fileName}")
    return fileName

def main():
    parser = argparse.ArgumentParser(description="Convert Seitenzahl et al. (2013) Type Ia supernova yields to "
                                                 "Galacticus XML format.")
    parser.add_argument("--models", nargs="+", default=sorted(models.keys()),
                        help="Solar-metallicity models to convert (default: all fourteen)")
    parser.add_argument("--no-sequence", action="store_true", dest="noSequence",
                        help="skip the metallicity-dependent N100 file")
    parser.add_argument("--source", default=None,
                        help="path to a local VICE 'vice/yields/sneia/seitenzahl13' directory; if omitted the "
                             "tables are downloaded from GitHub at the pinned revision")
    parser.add_argument("--cache-directory", default="viceData", dest="cacheDirectory",
                        help="directory in which the downloaded VICE archive is cached")
    parser.add_argument("--output-directory", default=None, dest="outputDirectory",
                        help="directory into which to write (default: "
                             "${GALACTICUS_DATA_PATH}/static/stellarAstrophysics)")
    arguments = parser.parse_args()
    for model in arguments.models:
        if model not in models:
            parser.error(f"unknown model '{model}'; known models are {', '.join(sorted(models.keys()))}")
    outputDirectory = arguments.outputDirectory if arguments.outputDirectory is not None \
                      else stellarAstrophysicsPath()
    atomicData = AtomicData()
    cache      = {}
    source     = arguments.source if arguments.source is not None \
                 else os.path.join(viceSNIaPath(arguments.cacheDirectory), 'seitenzahl13')
    print(f"Writing Seitenzahl et al. (2013) Type Ia yields to {outputDirectory}")
    for model in arguments.models:
        convertModel(model, source, outputDirectory, atomicData, cache)
    if not arguments.noSequence:
        print("Metallicity-dependent N100 sequence:")
        convertSequence(source, outputDirectory, atomicData, cache)

if __name__ == "__main__":
    sys.exit(main())
