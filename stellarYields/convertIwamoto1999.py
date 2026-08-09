#!/usr/bin/env python3
import os
import sys
import argparse
import urllib.request
import urllib.error
from galacticusYieldTables import (AtomicData, Provenance, filterMetals, md5Checksum, parseIsotope,
                                   stellarAstrophysicsPath, writeSupernovaeTypeIaYields)

# Convert the Iwamoto et al. (1999) Type Ia supernova yields into the XML format read by Galacticus.
# Andrew Benson (09-August-2026); generated with assistance from Claude.

# Iwamoto et al. (1999; ApJS; 125; 439) tabulate nucleosynthetic yields for seven Chandrasekhar-mass explosion
# models: the classic deflagration models W7 and W70 (their Table 3), and the delayed-detonation models WDD1,
# WDD2, WDD3, CDD1 and CDD2 (their Table 4). The published tables are typeset only -- there is no machine-readable
# version at CDS/VizieR -- so by default this script reads the transcription bundled with VICE (Johnson 2019,
# MIT-licensed), pinned to a fixed commit for reproducibility. Pass `--source` to point at a local checkout of
# VICE (or any directory laid out the same way) instead of downloading.
#
# The resulting files can be selected at run time via the `fileName` parameter of the Galacticus
# `supernovaeTypeIa` classes, e.g.:
#
#   <supernovaeTypeIa value="powerLawDTD">
#     <fileName value="%DATASTATICPATH%/stellarAstrophysics/Supernovae_Type_Ia_Yields_Iwamoto1999_WDD2.xml"/>
#   </supernovaeTypeIa>

# The VICE commit from which yields are read. Pinned so that a regenerated table is byte-for-byte reproducible.
viceRevision = "8d4469c618afbcc9031540445fea3140c8bb1777"
viceBaseURL  = "https://raw.githubusercontent.com/giganano/VICE/"+viceRevision+"/vice/yields/sneia/iwamoto99"
viceRepoURL  = "https://github.com/giganano/VICE"

# The models tabulated by Iwamoto et al. (1999), and the table of their paper in which each appears.
models = {
    "W7"  : {"table": "Table 3", "description": "Chandrasekhar-mass carbon deflagration model W7"           },
    "W70" : {"table": "Table 3", "description": "Chandrasekhar-mass carbon deflagration model W70"          },
    "WDD1": {"table": "Table 4", "description": "Chandrasekhar-mass delayed detonation model WDD1"          },
    "WDD2": {"table": "Table 4", "description": "Chandrasekhar-mass delayed detonation model WDD2"          },
    "WDD3": {"table": "Table 4", "description": "Chandrasekhar-mass delayed detonation model WDD3"          },
    "CDD1": {"table": "Table 4", "description": "Chandrasekhar-mass delayed detonation model CDD1"          },
    "CDD2": {"table": "Table 4", "description": "Chandrasekhar-mass delayed detonation model CDD2"          },
}

# Elements for which VICE provides a yield file. Files exist for every element it recognizes; those not
# synthesized by a given model simply contain zero yields.
elements = ["c" , "n" , "o" , "f" , "ne", "na", "mg", "al", "si", "p" , "s" , "cl", "ar", "k" , "ca", "sc",
            "ti", "v" , "cr", "mn", "fe", "co", "ni", "cu", "zn", "ga", "ge", "as", "se", "br", "kr", "rb",
            "sr", "y" , "zr", "nb", "mo", "ru", "rh", "pd", "ag", "cd", "in", "sn", "sb", "te", "i" , "xe",
            "cs", "ba", "la", "ce", "pr", "nd", "sm", "eu", "gd", "tb", "dy", "ho", "er", "tm", "yb", "lu",
            "hf", "ta", "w" , "re", "os", "ir", "pt", "au", "hg", "tl", "pb", "bi"]

# Read one element's yield file, returning a list of (isotope name, yield) pairs. The file format is a comment
# line followed by whitespace-separated "<isotope> <yield>" records.
def readElementFile(text, fileName):
    isotopes = []
    for line in text.splitlines():
        line = line.strip()
        if line == "" or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 2:
            raise ValueError(f"malformed record '{line}' in '{fileName}'")
        isotopes.append((fields[0], float(fields[1])))
    return isotopes

# Retrieve one element file, either from a local checkout or from GitHub.
def retrieve(source, model, element, cache):
    if source is not None:
        fileName = os.path.join(source, model, element+".dat")
        if not os.path.isfile(fileName):
            return None, None
        with open(fileName) as file:
            return file.read(), fileName
    url = f"{viceBaseURL}/{model}/{element}.dat"
    if url in cache:
        return cache[url]
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            text = response.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        if error.code == 404:
            cache[url] = (None, None)
            return None, None
        raise
    cache[url] = (text, url)
    return text, url

def convert(model, source, outputDirectory, atomicData):
    cache    = {}
    isotopes = []
    sources  = []
    for element in elements:
        text, origin = retrieve(source, model, element, cache)
        if text is None:
            continue
        sources.append(origin)
        for name, yield_ in readElementFile(text, origin):
            symbol, massNumber = parseIsotope(name)
            isotopes.append({
                "element"     : atomicData.shortLabel(atomicData.atomicNumber(symbol)),
                "massNumber"  : massNumber,
                "atomicNumber": atomicData.atomicNumber(symbol),
                "yield"       : yield_,
            })
    if not isotopes:
        raise RuntimeError(f"no yield data found for model '{model}'")
    # Retain metals only: the Galacticus reader sums every isotope in the file to form the total metal yield.
    isotopes = filterMetals(isotopes)
    inputs   = []
    if source is not None:
        inputs = [f"{fileName} (md5 {md5Checksum(fileName)})" for fileName in sorted(sources)]
    else:
        inputs = [f"{viceBaseURL}/{model}/<element>.dat ({len(sources)} element files)"]
    provenance = Provenance(
        scienceSource       = f"{models[model]['table']} of Iwamoto et al. (1999, ApJS, 125, 439), model {model}",
        scienceURL          = "https://ui.adsabs.harvard.edu/abs/1999ApJS..125..439I",
        transcriptionSource = f"VICE (Johnson 2019), MIT licensed, revision {viceRevision}",
        transcriptionURL    = viceRepoURL,
        generatedBy         = "galacticusDevTools/stellarYields/convertIwamoto1999.py",
        inputs              = inputs,
        notes               = ["Yields are gross masses of each isotope ejected, in Solar masses.",
                               "Hydrogen and helium are excluded: the Galacticus reader sums all isotopes "
                               "present to form the total metal yield."],
    )
    fileName = os.path.join(outputDirectory, f"Supernovae_Type_Ia_Yields_Iwamoto1999_{model}.xml")
    writeSupernovaeTypeIaYields(
        fileName    = fileName,
        isotopes    = isotopes,
        description = ("Yields for Type Ia supernovae from the "+models[model]['description']+" of Iwamoto et "
                       "al. (1999). Yields are given as the mass (in Solar masses) of each isotope produced."),
        source      = f"{models[model]['table']} of Iwamoto et al. (1999, ApJS, 125, 439; Model {model})",
        url         = "https://ui.adsabs.harvard.edu/abs/1999ApJS..125..439I",
        provenance  = provenance,
    )
    total = sum(isotope['yield'] for isotope in isotopes)
    print(f"  {model:5s}: {len(isotopes):3d} isotopes, total metal yield {total:.4f} Msun -> {fileName}")
    return fileName

def main():
    parser = argparse.ArgumentParser(description="Convert Iwamoto et al. (1999) Type Ia supernova yields to "
                                                 "Galacticus XML format.")
    parser.add_argument("--models", nargs="+", default=sorted(models.keys()),
                        help="models to convert (default: all)")
    parser.add_argument("--source", default=None,
                        help="path to a local VICE 'vice/yields/sneia/iwamoto99' directory; if omitted the "
                             "tables are downloaded from GitHub at the pinned revision")
    parser.add_argument("--output-directory", default=None, dest="outputDirectory",
                        help="directory into which to write (default: "
                             "${GALACTICUS_DATA_PATH}/static/stellarAstrophysics)")
    arguments = parser.parse_args()
    for model in arguments.models:
        if model not in models:
            parser.error(f"unknown model '{model}'; known models are {', '.join(sorted(models.keys()))}")
    outputDirectory = arguments.outputDirectory if arguments.outputDirectory is not None \
                      else stellarAstrophysicsPath()
    atomicData      = AtomicData()
    print(f"Writing Iwamoto et al. (1999) Type Ia yields to {outputDirectory}")
    for model in arguments.models:
        convert(model, arguments.source, outputDirectory, atomicData)

if __name__ == "__main__":
    sys.exit(main())
