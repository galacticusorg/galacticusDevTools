#!/usr/bin/env python3
import os
import re
import sys
import shutil
import argparse
import urllib.request
from galacticusYieldTables import (AtomicData, Provenance, decayProduct, md5Checksum, parseIsotope,
                                   stellarAstrophysicsPath, writeStellarProperties)

# Convert the Doherty et al. (2014a,b) super-AGB star models into the XML format read by Galacticus.
# Andrew Benson (22-October-2026); generated with assistance from Claude.

# Doherty et al. (2014a; MNRAS; 437; 195) and (2014b; MNRAS; 441; 582) provide net yields for super- and massive-AGB
# stars of 6.5-9 Msun, at Z = 0.02, 0.008 and 0.004 (paper II) and Z = 0.001 and 0.0001 (paper III): the range
# between the stars that end as carbon-oxygen white dwarfs and those that end as core-collapse supernovae, for
# which no yields were previously available to Galacticus. The upper mass of the grid rises with metallicity, from
# 7.5 Msun at Z <= 0.001 to 9 Msun at Z = 0.02, following the metallicity dependence of the mass above which stars
# go on to explode. Tables are taken from the online material at the first author's web site.
#
# Four features of the source tables are handled here:
#
#  * Each table gives two sets of yields. The "standard" set (columns `Yield` and `MassExp`) assumes that the
#    envelope remaining when the calculation stopped is expelled with the composition of the last computed model;
#    the "E-" set adds extrapolated thermal pulses. The standard set is used, as recommended by the authors.
#
#  * Yields are tabulated per *isotope*, including radioactive species (26Al, 55Fe, 60Fe, 35S) that decay after
#    ejection. Each isotope is credited to the element it decays to (see `decayProduct()`).
#
#  * The species "g" is not an isotope: it is the network's proxy for the s-process (the summed abundance of the
#    species beyond the network). Its yield is included in the total metal yield, but cannot be attributed to any
#    element.
#
#  * Galacticus does not interpolate yields across the minimum initial mass for a Type II supernova (its
#    `initialMassForSupernovaeTypeII` parameter, 8 Msun by default). Super-AGB models at or above that mass would
#    be treated as supernova progenitors, so are excluded (see `--mass-maximum`), and named in the provenance.
#
# The tables give, for each species, the net yield and the gross mass expelled; the ejected mass is the sum of the
# latter. No final masses or lifetimes are tabulated, so mass conservation is checked by requiring the net yields
# to sum to zero, and the remnant mass implied by the ejected mass to be that of a white dwarf.

baseURL   = "https://users.monash.edu/~cdoherty/research"
paperURLs = {"II" : "https://ui.adsabs.harvard.edu/abs/2014MNRAS.437..195D",
             "III": "https://ui.adsabs.harvard.edu/abs/2014MNRAS.441..582D"}

# Yield tables for the standard (Vassiliadis & Wood 1993; VW93) mass-loss rate, and the paper each comes from.
tables = (("TABLE1-VW93ML.txt"  , "II" ),
          ("P3Doh14b-table1.txt", "III"))

def retrieve(url, fileName):
    """Download `url` to `fileName` unless it is already present."""
    if not os.path.isfile(fileName):
        print(f"  downloading {url}")
        with urllib.request.urlopen(url, timeout=300) as response, open(fileName, 'wb') as file:
            shutil.copyfileobj(response, file)
    return fileName, url

def readTable(fileName):
    """Read one yield table, returning {(initial mass, metallicity): [(species, net yield, mass expelled)]}.

    Each model opens with a header line such as "7.0M Z=0.02 VW93", followed by a line of column names and one
    row per species of seven columns: the species, then the yield, mass expelled and production factor for each of
    the standard and "E-" sets."""
    models  = {}
    current = None
    for line in open(fileName):
        header = re.search(r'([0-9.]+)M\s+Z=([0-9.]+)', line)
        if header:
            current         = (float(header.group(1)), float(header.group(2)))
            models[current] = []
            continue
        fields = line.split()
        if len(fields) != 7 or fields[0] == "Species":
            continue
        if current is None:
            raise ValueError(f"data row before any model header in '{fileName}'")
        models[current].append((fields[0], float(fields[1]), float(fields[2])))
    if not models:
        raise ValueError(f"no models found in '{fileName}'")
    return models

def convert(models, atomicData, massMaximum, outputDirectory, inputs):
    stars    = []
    excluded = []
    for (massInitial, metallicity), rows in sorted(models.items()):
        if massInitial >= massMaximum:
            excluded.append(f"{massInitial} Msun at Z = {metallicity}")
            continue
        massEjected = sum(row[2] for row in rows)
        yieldTotal  = sum(row[1] for row in rows)
        # Mass conservation: the net yields must sum to zero. The tables give three significant figures, so the
        # tolerance is set accordingly.
        if abs(yieldTotal) > 5.0e-4*massEjected:
            raise ValueError(f"model {massInitial} Msun, Z = {metallicity}: net yields sum to {yieldTotal:.4e} Msun")
        # The remnant of a super-AGB star is an oxygen-neon white dwarf, so must lie below the Chandrasekhar mass,
        # and well above the masses of the carbon-oxygen white dwarfs left by lower mass stars.
        massRemnant = massInitial-massEjected
        if not 0.8 < massRemnant < 1.44:
            raise ValueError(f"model {massInitial} Msun, Z = {metallicity}: implied remnant mass {massRemnant:.3f} "
                             f"Msun is not that of an oxygen-neon white dwarf")
        elementYield = {}
        yieldMetals  = 0.0
        for species, yieldNet, _ in rows:
            if species == "g":
                # The s-process proxy: a metal, but not attributable to an element.
                yieldMetals += yieldNet
                continue
            if species in ("n", "p", "d"):
                # Free neutrons, protons and deuterons are not metals.
                continue
            symbol, massNumber = parseIsotope(species)
            atomicNumber       = decayProduct(atomicData.atomicNumber(symbol), massNumber)
            if atomicNumber <= 2:
                continue
            label               = atomicData.shortLabel(atomicNumber)
            elementYield[label] = elementYield.get(label, 0.0)+yieldNet
            yieldMetals        += yieldNet
        stars.append({
            "initialMass"      : massInitial,
            "metallicity"      : metallicity,
            "ejectedMass"      : massEjected,
            "metalYieldMass"   : yieldMetals,
            "elementYieldMass" : elementYield,
        })
    stars.sort(key=lambda star: (star["metallicity"], star["initialMass"]))
    provenance = Provenance(
        scienceSource       = ("Doherty et al. (2014a, MNRAS, 437, 195; paper II) and (2014b, MNRAS, 441, 582; "
                               "paper III), standard yields with the VW93 mass-loss rate"),
        scienceURL          = f"{paperURLs['II']} ; {paperURLs['III']}",
        transcriptionSource = "Online yield tables accompanying papers II and III",
        transcriptionURL    = f"{baseURL}/yields.html",
        generatedBy         = "galacticusDevTools/dataPreparation/stellarYields/convertDoherty2014.py",
        inputs              = inputs,
        notes               = ["Yields are net elemental yields in Solar masses, and may be negative.",
                               "The standard yields are used, in which the envelope remaining when the "
                               "calculation stopped is expelled with the composition of the last computed model; "
                               "the alternative set with extrapolated thermal pulses is not.",
                               "Isotopic yields are summed into elements, with radioactive isotopes credited to "
                               "the element they decay to.",
                               "The metal yield includes that of the s-process proxy species g, which is not "
                               "attributable to any element. These models therefore contribute no yield to any "
                               "element beyond nickel.",
                               "Ejected mass is the sum of the masses expelled of each species.",
                               "No lifetimes are tabulated, so a compilation must take them from another source.",
                               (f"Models at or above {massMaximum} Msun are excluded, so that none lie above the "
                                "minimum initial mass for a Type II supernova assumed by Galacticus: "
                                +(", ".join(excluded) if excluded else "none")+". In the models, the mass above "
                                "which stars explode rises with metallicity, but Galacticus applies a single "
                                "metallicity-independent minimum mass, so the excluded models (which end as white "
                                "dwarfs) cannot be used without treating them as supernova progenitors."),
                               "Metallicities are the nominal Z of the models, with Z = 0.02 for the Solar model. "
                               "They are not rescaled to match sources using other Solar mixtures (e.g. Z = 0.01345 "
                               "for the Asplund et al. 2009 mixture of Limongi & Chieffi 2018)."],
    )
    fileName = os.path.join(outputDirectory, "stellarPropertiesDoherty2014.xml")
    writeStellarProperties(
        fileName   = fileName,
        stars      = stars,
        source     = "Doherty et al. (2014a, MNRAS, 437, 195; 2014b, MNRAS, 441, 582)",
        url        = paperURLs["II"],
        provenance = provenance,
    )
    metallicities = sorted({star["metallicity"] for star in stars})
    print(f"  {len(stars)} models, {len(excluded)} excluded, Z = {', '.join(f'{Z:g}' for Z in metallicities)}")
    print(f"    -> {fileName}")
    return fileName

def main():
    parser = argparse.ArgumentParser(description="Convert Doherty et al. (2014) super-AGB models to Galacticus XML "
                                                 "format.")
    parser.add_argument("--mass-maximum", type=float, default=8.0, dest="massMaximum",
                        help="exclude models of this initial mass or above; should not exceed the "
                             "initialMassForSupernovaeTypeII used by Galacticus (default: 8.0)")
    parser.add_argument("--cache-directory", default="doherty14Data", dest="cacheDirectory",
                        help="directory in which downloaded source tables are cached")
    parser.add_argument("--output-directory", default=None, dest="outputDirectory",
                        help="directory into which to write (default: "
                             "${GALACTICUS_DATA_PATH}/static/stellarAstrophysics)")
    arguments = parser.parse_args()
    outputDirectory = arguments.outputDirectory if arguments.outputDirectory is not None \
                      else stellarAstrophysicsPath()
    os.makedirs(arguments.cacheDirectory, exist_ok=True)
    atomicData = AtomicData()
    print("Retrieving source tables")
    models = {}
    inputs = []
    for table, paper in tables:
        fileName, url = retrieve(f"{baseURL}/{table}", os.path.join(arguments.cacheDirectory, table))
        for key, rows in readTable(fileName).items():
            if key in models:
                raise ValueError(f"model {key} appears in more than one table")
            models[key] = rows
        inputs.append(f"{url} (paper {paper}; md5 {md5Checksum(fileName)})")
    print(f"Writing Doherty et al. (2014) stellar properties to {outputDirectory}")
    convert(models, atomicData, arguments.massMaximum, outputDirectory, inputs)

if __name__ == "__main__":
    sys.exit(main())
