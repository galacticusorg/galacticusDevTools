#!/usr/bin/env python3
import os
import re
import sys
import glob
import shutil
import tarfile
import argparse
import urllib.request
from galacticusYieldTables import (AtomicData, Provenance, md5Checksum, parseIsotope,
                                   stellarAstrophysicsPath, writeStellarProperties)

# Convert the Sukhbold et al. (2016) core-collapse supernova models into the XML format read by Galacticus.
# Andrew Benson (09-August-2026); generated with assistance from Claude.

# Sukhbold et al. (2016; ApJ; 821; 38) provide 200 models spanning 9-120 Msun on a grid far denser than any
# other set available (0.1 Msun steps between 13 and 27 Msun), with a physically motivated prescription for
# which stars explode rather than a simple mass threshold. The price is that they are computed at a *single*
# metallicity -- Solar -- and for non-rotating progenitors only.
#
# THAT SINGLE METALLICITY IS THE IMPORTANT CAVEAT, and it has to be handled explicitly. Each model is written
# twice, at two bracketing metallicities with identical yields, which states plainly that these yields do not
# depend on metallicity. It is also what makes them usable at all: the irregular two dimensional interpolation
# used by the stellarAstrophysicsFile class extrapolates badly when the requested metallicity lies outside the
# range spanned by the tabulated points at the relevant masses, and for a table at a single metallicity that is
# almost always the case. Written at one metallicity these models return eleven times the expected metal yield,
# or zero, or hang the initial mass function integration, depending on what they are combined with.
#
# The yields remain metallicity independent, which is a real limitation of the models rather than of the
# encoding: any element supplied only by this file takes its Solar yield at every metallicity. They also carry
# no lifetimes, so a lifetime source must be combined with them.
#
# Data come from the Garching core-collapse supernova archive. Three features of the yield tables are handled
# here, each of which would otherwise corrupt the result silently:
#
#  * Each table ends with a block of 20 radioactive isotopes (c14 ... ni63) which is *supplementary*: the stable
#    block preceding it already contains their decay products. Summing the whole file therefore double counts.
#    That the stable block is already decayed can be checked directly -- for the 20.1 Msun W18 model the ejected
#    fe56 is 0.106 Msun, far above the ~0.018 Msun expected were it unprocessed, and consistent with the birth
#    abundance plus the 0.0906 Msun of ni56 listed separately. Note also that k40 appears in *both* blocks, so
#    reading the file into a dictionary keyed on isotope would silently overwrite the stable entry.
#
#  * The imploding models have only one data column (wind) where the exploding models have two (ejecta, wind),
#    since a star which collapses entirely ejects only its wind.
#
#  * The 14.0 Msun tables are truncated, lacking the ~95 heaviest stable isotopes. Those elements are omitted
#    from that model rather than recorded as zero: a zero *gross* yield would convert to a large negative *net*
#    yield, spuriously implying the element had been destroyed. Galacticus pads elements missing from a star
#    with a zero net yield, which is the physically correct value for unprocessed heavy elements.
#
# Yields in the archive are gross masses, so they are converted to the net yields Galacticus expects by
# subtracting the birth composition: net = gross - X_birth * M_ejected. The birth composition is the Lodders
# (2003) protosolar mixture used by the KEPLER progenitors, taken from the copy bundled with VICE; that it sums
# to X = 0.7111, Y = 0.2740, Z = 0.0149438 confirms the identification.

archiveBaseURL = "https://wwwmpa.mpa-garching.mpg.de/ccsnarchive/data/SEWBJ_2015/data"
archiveURL     = "https://wwwmpa.mpa-garching.mpg.de/ccsnarchive/data/SEWBJ_2015/"
paperURL       = "https://ui.adsabs.harvard.edu/abs/2016ApJ...821...38S"
viceRevision   = "8d4469c618afbcc9031540445fea3140c8bb1777"
birthURL       = ("https://raw.githubusercontent.com/giganano/VICE/"+viceRevision
                  +"/vice/yields/ccsne/S16/W18/FeH0/birth_composition.dat")

# The 20 radioactive isotopes appended to every table, in the order in which they appear.
radioactiveIsotopes = ["c14" , "na22", "al26", "si32", "cl36", "ar39", "k40" , "ca41", "ca45", "ti44",
                       "v49" , "mn53", "mn54", "fe55", "fe60", "co60", "ni56", "ni57", "ni59", "ni63"]

# The two metallicities at which each model is written. They bracket any metallicity a model is likely to
# request, so that interpolation never has to extrapolate in metallicity; the yields are identical at both.
metallicityBracketDefault = (1.0e-4, 1.0e-1)

# The explosion engines for which exploding-model yields are tabulated. The lowest mass models (9.0-12.0 Msun)
# always use the Z9.6 calibration, following Sukhbold et al.
engines = {
    "W18": "the W18 neutrino engine",
    "N20": "the N20 neutrino engine",
}

def retrieve(url, fileName):
    """Download `url` to `fileName` unless already present; return both."""
    if not os.path.isfile(fileName):
        print(f"  downloading {url}")
        with urllib.request.urlopen(url, timeout=600) as response, open(fileName, 'wb') as file:
            shutil.copyfileobj(response, file)
    return fileName, url

def readBirthComposition(fileName):
    """Read the birth composition, returning {element symbol: mass fraction}, and validate that it sums to one."""
    composition = {}
    for line in open(fileName):
        fields = line.split()
        if len(fields) == 2:
            composition[fields[0].lower()] = float(fields[1])
    helium = composition.get('he')
    if helium is None:
        raise ValueError(f"no helium abundance in '{fileName}'")
    metals   = sum(value for element, value in composition.items() if element != 'he')
    hydrogen = 1.0-helium-metals
    if not 0.70 < hydrogen < 0.72:
        raise ValueError(f"birth composition implies an implausible hydrogen mass fraction of {hydrogen:.4f}")
    return composition, metals

def readYieldTable(fileName):
    """Read one model's yield table, returning {element symbol: gross ejected mass} and the total ejected mass.

    The final block of radioactive isotopes is dropped: the stable block above it already contains their decay
    products, so including them would double count."""
    rows = [line.split() for line in open(fileName).read().splitlines()[1:] if line.split()]
    if [row[0] for row in rows[-len(radioactiveIsotopes):]] != radioactiveIsotopes:
        raise ValueError(f"'{fileName}' does not end with the expected block of radioactive isotopes")
    rows      = rows[:-len(radioactiveIsotopes)]
    gross     = {}
    massTotal = 0.0
    for row in rows:
        # Exploding models tabulate ejecta and wind separately; imploding models eject only their wind.
        mass    = sum(float(value) for value in row[1:])
        element = parseIsotope(row[0])[0].lower()
        gross[element] = gross.get(element, 0.0)+mass
        massTotal     += mass
    return gross, massTotal

def modelMass(fileName):
    return float(re.fullmatch(r's(.+)\.yield_table', os.path.basename(fileName)).group(1))

def collectModels(yieldPath, engine):
    """Return {mass: (fileName, description)} for the complete 200 model set of the given engine.

    The set comprises the Z9.6 models at the lowest masses, the exploding models of the chosen engine, and --
    for those masses which do not explode under that engine -- the wind-only imploding models. The imploding
    yields are tabulated only for the W18 engine, but a star which collapses entirely ejects only its wind,
    which is set by the progenitor's mass loss history and not by the explosion engine, so the same tables
    apply."""
    def masses(directory):
        return {modelMass(name): name for name in glob.glob(os.path.join(yieldPath, directory, "*.yield_table"))}
    lowMass    = masses("Z9.6"          )
    exploding  = masses(engine          )
    imploding  = masses("implosions_W18")
    fullGrid   = set(masses("W18")) | set(imploding)
    collapsing = fullGrid-set(exploding)
    missing    = collapsing-set(imploding)
    if missing:
        raise ValueError(f"no imploding model available for masses {sorted(missing)}")
    models = {}
    for mass, name in lowMass  .items(): models[mass] = (name, "Z9.6 engine"     )
    for mass, name in exploding.items(): models[mass] = (name, f"{engine} engine")
    for mass in collapsing:              models[mass] = (imploding[mass], "collapses entirely; wind only")
    return models

def convert(engine, yieldPath, birthComposition, metallicity, outputDirectory, atomicData, inputs,
            metallicityBracket):
    models = collectModels(yieldPath, engine)
    stars  = []
    for mass in sorted(models):
        fileName, _  = models[mass]
        gross, massEjected = readYieldTable(fileName)
        if massEjected <= 0.0:
            raise ValueError(f"model '{fileName}' ejects no mass")
        elementYield = {}
        for element, grossMass in gross.items():
            if element == 'h':
                continue
            fraction = birthComposition.get(element)
            if fraction is None:
                raise KeyError(f"no birth abundance for element '{element}'")
            net = grossMass-fraction*massEjected
            if element != 'he':
                elementYield[atomicData.shortLabel(atomicData.atomicNumber(element))] = net
        # Write the model at both bracketing metallicities, with identical yields.
        for metallicityBracketing in metallicityBracket:
            stars.append({
                "initialMass"      : mass,
                "metallicity"      : metallicityBracketing,
                "ejectedMass"      : massEjected,
                "metalYieldMass"   : sum(elementYield.values()),
                "elementYieldMass" : elementYield,
            })
    provenance = Provenance(
        scienceSource       = f"Sukhbold et al. (2016, ApJ, 821, 38), {engines[engine]}",
        scienceURL          = paperURL,
        transcriptionSource = ("Yields from the Garching core-collapse supernova archive; birth composition "
                               "(Lodders 2003, as used by the KEPLER progenitors) from VICE (Johnson 2019), "
                               f"MIT licensed, revision {viceRevision}"),
        transcriptionURL    = archiveURL,
        generatedBy         = "galacticusDevTools/stellarYields/convertSukhbold2016.py",
        inputs              = inputs,
        notes               = [f"Models 9.0-12.0 Msun use the Z9.6 calibration; above that, {engines[engine]}; "
                              "masses which do not explode contribute their wind only.",
                              "SINGLE METALLICITY. These models are computed at Solar metallicity only, and for "
                              "non-rotating progenitors. Galacticus clamps a requested metallicity to the range "
                              "tabulated for each element, so any element supplied only by this file will take "
                              "its Solar yield at every metallicity.",
                              "Each model is written twice, at two bracketing metallicities with identical "
                              "yields. That is an explicit statement that these yields do not depend on "
                              "metallicity, and it is also what makes them usable: the irregular two "
                              "dimensional interpolation of the stellarAstrophysicsFile class extrapolates "
                              "badly when the requested metallicity falls outside the range spanned by the "
                              "tabulated points at the relevant masses, which for a table at a single "
                              "metallicity is almost always. Written at one metallicity these models return "
                              "eleven times the expected metal yield, or zero, or hang the initial mass "
                              "function integration, depending on what they are combined with; bracketing "
                              "makes every request an interpolation and recovers the expected result.",
                              "NO LIFETIMES. A source of stellar lifetimes must be combined with this file.",
                              "Yields are net elemental yields in Solar masses, and may be negative; they were "
                              "converted from the gross yields of the archive by subtracting the birth "
                              "composition.",
                              "The supplementary block of 20 radioactive isotopes in each source table is "
                              "excluded: the stable block already contains their decay products."],
    )
    fileName = os.path.join(outputDirectory, f"stellarPropertiesSukhbold2016_{engine}.xml")
    writeStellarProperties(
        fileName   = fileName,
        stars      = stars,
        source     = f"Sukhbold et al. (2016, ApJ, 821, 38; {engines[engine]})",
        url        = paperURL,
        provenance = provenance,
    )
    massRange = (min(star["initialMass"] for star in stars), max(star["initialMass"] for star in stars))
    print(f"  {engine}: {len(stars)//len(metallicityBracket):3d} models, M = {massRange[0]}-{massRange[1]} "
          f"Msun, computed at Z = {metallicity:.7f}, written at Z = "
          f"{' and '.join(f'{Z:g}' for Z in metallicityBracket)}")
    print(f"    -> {fileName}")
    return fileName

def main():
    parser = argparse.ArgumentParser(description="Convert Sukhbold et al. (2016) core-collapse supernova models "
                                                 "to Galacticus XML format.")
    parser.add_argument("--engines", nargs="+", default=sorted(engines.keys()),
                        help="explosion engines to convert (default: all)")
    parser.add_argument("--metallicity-bracket", nargs=2, type=float, default=list(metallicityBracketDefault),
                        dest="metallicityBracket",
                        help="the two metallicities at which each model is written, bracketing any value a "
                             f"model is likely to request (default: {metallicityBracketDefault})")
    parser.add_argument("--cache-directory", default="s16Data", dest="cacheDirectory",
                        help="directory in which downloaded source tables are cached")
    parser.add_argument("--output-directory", default=None, dest="outputDirectory",
                        help="directory into which to write (default: "
                             "${GALACTICUS_DATA_PATH}/static/stellarAstrophysics)")
    arguments = parser.parse_args()
    for engine in arguments.engines:
        if engine not in engines:
            parser.error(f"unknown engine '{engine}'; known engines are {', '.join(sorted(engines.keys()))}")
    outputDirectory = arguments.outputDirectory if arguments.outputDirectory is not None \
                      else stellarAstrophysicsPath()
    os.makedirs(arguments.cacheDirectory, exist_ok=True)
    atomicData = AtomicData()

    print("Retrieving source tables")
    yieldArchive, yieldsURL = retrieve(f"{archiveBaseURL}/nucleosynthesis_yields.tar.gz",
                                       os.path.join(arguments.cacheDirectory, "nucleosynthesis_yields.tar.gz"))
    birthFile   , birthFileURL = retrieve(birthURL,
                                          os.path.join(arguments.cacheDirectory, "birth_composition.dat"))
    yieldPath = os.path.join(arguments.cacheDirectory, "nucleosynthesis_yields")
    if not os.path.isdir(yieldPath):
        with tarfile.open(yieldArchive) as archive:
            archive.extractall(arguments.cacheDirectory)
    birthComposition, metallicity = readBirthComposition(birthFile)
    inputs = [f"{url} (md5 {md5Checksum(name)})"
              for name, url in ((yieldArchive, yieldsURL), (birthFile, birthFileURL))]

    print(f"Writing Sukhbold et al. (2016) stellar properties to {outputDirectory}")
    for engine in arguments.engines:
        convert(engine, yieldPath, birthComposition, metallicity, outputDirectory, atomicData, inputs,
                tuple(arguments.metallicityBracket))

if __name__ == "__main__":
    sys.exit(main())
