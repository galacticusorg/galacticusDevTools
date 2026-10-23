#!/usr/bin/env python3
import os
import re
import sys
import shutil
import argparse
import urllib.request
from galacticusYieldTables import (AtomicData, Provenance, decayProduct, md5Checksum, stellarAstrophysicsPath,
                                   writeStellarProperties)

# Convert the Karakas (2010) asymptotic giant branch models into the XML format read by Galacticus.
# Andrew Benson (22-October-2026); generated with assistance from Claude.

# Karakas (2010; MNRAS; 403; 1413) provide net yields for thermally pulsing asymptotic giant branch (AGB) models of
# 1-6 Msun (6.5 Msun at Z = 0.02) at Z = 0.02, 0.008, 0.004 and 0.0001, extending well below the Z = 0.004 floor of
# the Marigo (2001) models that Galacticus uses by default, and with net yields for 77 species from hydrogen to
# nickel rather than for C, N and O alone. The yield tables (Tables A2-A5) are taken from the CDS copy of the paper
# (J/MNRAS/403/1413).
#
# Four features of the source tables are handled here:
#
#  * Yields are tabulated per *isotope*, including short-lived and radioactive species (e.g. 26Al, in both its
#    ground and isomeric states, 60Fe, 22Na, 8B) that decay after ejection. Each isotope is credited to the element
#    it decays to (see `decayProduct()`).
#
#  * The species "g" is not an isotope: it is the summed abundance of 64Ni to Bi, the network's proxy for the
#    s-process. Its yield is included in the total metal yield, but cannot be attributed to any element.
#
#  * The 6 Msun, Z = 0.0001 model is tabulated twice, once with the Vassiliadis & Wood (1993; VW93) AGB mass-loss
#    rate used for every other model in the grid, and once with the Reimers rate. The two are distinguished only by
#    their final masses (1.006 and 1.008 Msun respectively, per note 1 of the CDS ReadMe). The VW93 model is used,
#    for consistency with the rest of the grid.
#
#  * No lifetimes are tabulated, so none are written: a compilation must take its lifetimes from another source.
#
# The ejected mass is the initial minus the final mass. The consistency of this with the yields is checked: the net
# yields, summed over all species, must vanish (mass is conserved), and the wind mass implied by the table's
# columns of initial and ejected species masses must equal the ejected mass.

cdsBaseURL = "https://cdsarc.cds.unistra.fr/ftp/J/MNRAS/403/1413"
paperURL   = "https://ui.adsabs.harvard.edu/abs/2010MNRAS.403.1413K"

# Yield tables, one per metallicity.
tables = ("tablea2.dat", "tablea3.dat", "tablea4.dat", "tablea5.dat")

# Final masses of the duplicated model which used the Reimers mass-loss rate, and so is excluded.
excludedModels = {(6.0, 0.0001, 1.008): "Reimers mass loss (the VW93 model, final mass 1.006 Msun, is used)"}

def retrieve(url, fileName):
    """Download `url` to `fileName` unless it is already present."""
    if not os.path.isfile(fileName):
        print(f"  downloading {url}")
        with urllib.request.urlopen(url, timeout=300) as response, open(fileName, 'wb') as file:
            shutil.copyfileobj(response, file)
    return fileName, url

def readTable(fileName):
    """Read one yield table, returning {(initial mass, metallicity, final mass): [(species, mass number, net yield,
    mass lost, mass initially present)]}. Byte offsets follow the CDS ReadMe."""
    models = {}
    for line in open(fileName):
        if not line.strip():
            continue
        massInitial = float(line[ 0: 4])
        metallicity = float(line[ 5:11])
        massFinal   = float(line[12:17])
        species     =       line[21:25].strip()
        massNumber  = int  (line[30:32])
        yieldNet    = float(line[34:48])
        massLost    = float(line[49:63])
        massPresent = float(line[64:78])
        models.setdefault((massInitial, metallicity, massFinal), []).append(
            (species, massNumber, yieldNet, massLost, massPresent))
    return models

def convert(models, atomicData, outputDirectory, inputs):
    stars    = []
    excluded = []
    for (massInitial, metallicity, massFinal), rows in sorted(models.items()):
        if (massInitial, metallicity, massFinal) in excludedModels:
            excluded.append(f"{massInitial} Msun, Z = {metallicity} (final mass {massFinal} Msun): "
                            f"{excludedModels[(massInitial, metallicity, massFinal)]}")
            continue
        massEjected = massInitial-massFinal
        # Mass conservation: the net yields, summed over every species, must vanish, and the mass lost in the wind
        # must equal the ejected mass. Final masses are tabulated to three decimal places, which sets the tolerance.
        yieldTotal = sum(row[2] for row in rows)
        massLost   = sum(row[3] for row in rows)
        if abs(yieldTotal) > 2.0e-3*massEjected:
            raise ValueError(f"model {massInitial} Msun, Z = {metallicity}: net yields sum to {yieldTotal:.4e} Msun")
        if abs(massLost-massEjected) > max(2.0e-3*massEjected, 1.0e-3):
            raise ValueError(f"model {massInitial} Msun, Z = {metallicity}: wind mass {massLost:.4f} Msun differs "
                             f"from the initial minus final mass, {massEjected:.4f} Msun")
        elementYield = {}
        yieldMetals  = 0.0
        for species, massNumber, yieldNet, _, _ in rows:
            if species == "g":
                # The s-process proxy: a metal, but not attributable to an element.
                yieldMetals += yieldNet
                continue
            if species in ("n", "p", "d"):
                # Free neutrons, protons and deuterons are not metals. (Compare the whole species name: the element
                # symbol of nitrogen is also "n".)
                continue
            symbol = re.match(r'[A-Za-z]+', species).group(0)
            atomicNumber = decayProduct(atomicData.atomicNumber(symbol), massNumber)
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
        scienceSource       = "Karakas (2010, MNRAS, 403, 1413)",
        scienceURL          = paperURL,
        transcriptionSource = "CDS copy of the paper's Tables A2-A5 (J/MNRAS/403/1413)",
        transcriptionURL    = cdsBaseURL,
        generatedBy         = "galacticusDevTools/dataPreparation/stellarYields/convertKarakas2010.py",
        inputs              = inputs,
        notes               = ["Yields are net elemental yields in Solar masses, and may be negative.",
                               "Isotopic yields are summed into elements, with short-lived and radioactive "
                               "isotopes credited to the element they decay to.",
                               "The metal yield includes that of the s-process proxy species g (the summed "
                               "abundance of 64Ni to Bi), which is not attributable to any element. These models "
                               "therefore contribute no yield to any element beyond nickel.",
                               "Ejected mass is the initial minus the final mass.",
                               "No lifetimes are tabulated, so a compilation must take them from another source.",
                               "Covers initial masses up to 6 Msun (6.5 Msun at Z = 0.02) only, and so must be "
                               "combined with a source of super-AGB and massive star yields.",
                               "Metallicities are the nominal Z of the models, with Z = 0.02 for the Solar model. "
                               "They are not rescaled to match sources using other Solar mixtures (e.g. Z = 0.01345 "
                               "for the Asplund et al. 2009 mixture of Limongi & Chieffi 2018).",
                               "The later models of Karakas & Lugaro (2016) and Karakas et al. (2018), which extend "
                               "the grid to Z = 0.0028-0.03 and up to 8 Msun, are not included.",
                               ("Excluded: "+("; ".join(excluded) if excluded else "none"))],
    )
    fileName = os.path.join(outputDirectory, "stellarPropertiesKarakas2010.xml")
    writeStellarProperties(
        fileName   = fileName,
        stars      = stars,
        source     = "Karakas (2010, MNRAS, 403, 1413)",
        url        = paperURL,
        provenance = provenance,
    )
    metallicities = sorted({star["metallicity"] for star in stars})
    print(f"  {len(stars)} models, {len(excluded)} excluded, Z = {', '.join(f'{Z:g}' for Z in metallicities)}")
    print(f"    -> {fileName}")
    return fileName

def main():
    parser = argparse.ArgumentParser(description="Convert Karakas (2010) AGB models to Galacticus XML format.")
    parser.add_argument("--cache-directory", default="karakas10Data", dest="cacheDirectory",
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
    for table in tables:
        fileName, url = retrieve(f"{cdsBaseURL}/{table}", os.path.join(arguments.cacheDirectory, table))
        models.update(readTable(fileName))
        inputs.append(f"{url} (md5 {md5Checksum(fileName)})")
    print(f"Writing Karakas (2010) stellar properties to {outputDirectory}")
    convert(models, atomicData, outputDirectory, inputs)

if __name__ == "__main__":
    sys.exit(main())
