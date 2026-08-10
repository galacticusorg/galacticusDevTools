#!/usr/bin/env python3
import os
import sys
import argparse
import xml.etree.ElementTree as ET
from galacticusYieldTables import Provenance, stellarAstrophysicsPath, writeStellarProperties

# Split the Portinari, Chiosi & Bressan (1998) stellar properties file into its lifetime and yield components.
# Andrew Benson (09-August-2026); generated with assistance from Claude.

# The Portinari, Chiosi & Bressan (1998; A&A; 334; 505) file supplies two logically separate things: stellar
# lifetimes, tabulated for 0.6-120 Msun, and ejected masses with yields, tabulated for 9-120 Msun. The two are
# carried by disjoint sets of `star` elements -- no entry has both -- so the file can be split losslessly.
#
# Splitting matters because the two are wanted independently. A compilation built around the Limongi & Chieffi
# (2018) massive star yields wants Portinari's lifetimes, which extend down to 0.6 Msun, but must not also take
# Portinari's yields: those cover 9-120 Msun and would overlap the Limongi & Chieffi models, leaving the
# interpolation to blend two mutually inconsistent sets of stellar models over the same region of the
# (mass, metallicity) plane.
#
# The standard compilation is unaffected: it simply includes both halves in place of the original file.

sourceText = "Table 10 of Portinari, Chiosi & Bressan (1998, A&A, 334, 505)"
sourceURL  = "https://ui.adsabs.harvard.edu/abs/1998A%26A...334..505P"

def readStars(fileName):
    """Read a stellar properties file, returning a list of dicts in the form used by `writeStellarProperties`."""
    stars = []
    for element in ET.parse(fileName).getroot().findall('star'):
        star = {"elementYieldMass": {}}
        for child in element:
            if child.tag.startswith("elementYieldMass"):
                star["elementYieldMass"][child.tag[len("elementYieldMass"):]] = float(child.text)
            elif child.tag in ("initialMass", "metallicity", "lifetime", "ejectedMass", "metalYieldMass"):
                star[child.tag] = float(child.text)
        stars.append(star)
    return stars

def main():
    parser = argparse.ArgumentParser(description="Split the Portinari, Chiosi & Bressan (1998) stellar "
                                                 "properties file into lifetime and yield components.")
    parser.add_argument("--input", default=None,
                        help="the file to split (default: the copy in ${GALACTICUS_DATA_PATH})")
    parser.add_argument("--output-directory", default=None, dest="outputDirectory",
                        help="directory into which to write (default: "
                             "${GALACTICUS_DATA_PATH}/static/stellarAstrophysics)")
    arguments       = parser.parse_args()
    outputDirectory = arguments.outputDirectory if arguments.outputDirectory is not None \
                      else stellarAstrophysicsPath()
    inputFileName   = arguments.input if arguments.input is not None \
                      else os.path.join(stellarAstrophysicsPath(),
                                        "stellarPropertiesPortinariChiosiBressan1998.xml")
    stars = readStars(inputFileName)

    # Partition. Every star must fall into exactly one of the two groups, or the split would not be lossless.
    lifetimes = [star for star in stars if "lifetime"    in star]
    yields    = [star for star in stars if "ejectedMass" in star or "metalYieldMass" in star]
    overlap   = [star for star in stars if "lifetime"    in star
                 and ("ejectedMass" in star or "metalYieldMass" in star)]
    if overlap:
        print(f"FAILED: {len(overlap)} stars carry both a lifetime and yields, so the split would not be "
              "lossless")
        return 1
    if len(lifetimes)+len(yields) != len(stars):
        print(f"FAILED: {len(stars)-len(lifetimes)-len(yields)} stars carry neither a lifetime nor yields")
        return 1

    for name, subset, description in (
            ("Lifetimes", lifetimes, "stellar lifetimes"                      ),
            ("Yields"   , yields   , "ejected masses and net elemental yields"),
    ):
        provenance = Provenance(
            scienceSource = sourceText,
            scienceURL    = sourceURL,
            generatedBy   = "galacticusDevTools/stellarYields/splitPortinariChiosiBressan1998.py",
            inputs        = [os.path.basename(inputFileName)],
            notes         = [f"This file carries only the {description} from the source compilation; the "
                             "remaining properties are in its companion file.",
                             "The two halves together reproduce the original file exactly."],
        )
        fileName = os.path.join(outputDirectory, f"stellarPropertiesPortinariChiosiBressan1998{name}.xml")
        writeStellarProperties(
            fileName   = fileName,
            stars      = subset,
            source     = f"{sourceText} [{description}]",
            url        = sourceURL,
            provenance = provenance,
        )
        print(f"  {len(subset):3d} stars -> {fileName}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
