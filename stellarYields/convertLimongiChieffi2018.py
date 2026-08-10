#!/usr/bin/env python3
import os
import sys
import shutil
import tarfile
import zipfile
import argparse
import urllib.request
from galacticusYieldTables import (AtomicData, Provenance, md5Checksum, stellarAstrophysicsPath,
                                   writeStellarProperties)

# Convert the Limongi & Chieffi (2018) massive star models into the XML format read by Galacticus.
# Andrew Benson (09-August-2026); generated with assistance from Claude.

# Limongi & Chieffi (2018; ApJS; 237; 13) provide models of 13-120 Msun stars at four metallicities
# ([Fe/H] = 0, -1, -2, -3) and three initial equatorial rotation velocities (0, 150 and 300 km/s), extending
# roughly a factor of twelve below the metallicity floor of the Portinari, Chiosi & Bressan (1998) models that
# Galacticus uses by default. Yields are taken from the ORFEO database, which tabulates *net* elemental yields
# directly -- the same convention Galacticus uses -- so no conversion is needed.
#
# Data are assembled from two sources:
#
#  * ORFEO (http://orfeo.iaps.inaf.it) supplies the net elemental yields (`tab_yieldsnet_ele_exp.dec`) and the
#    remnant masses. Note that despite the "exp" in the file name, these tables are the *total* ejecta: their
#    gross counterparts sum exactly to the initial mass minus the remnant mass, wind included. The script
#    asserts this.
#
#  * The CDS copy of the paper's Table 5 (J/ApJS/237/13) supplies stellar lifetimes, which ORFEO does not
#    tabulate. The table lists the duration of each evolutionary phase; the lifetime is their sum. Models which
#    were stopped early pad the table out to eight rows by repeating the final `PSN` row, so phases must be
#    de-duplicated before summing -- otherwise the lifetime of, for example, the 120 Msun [Fe/H]=-3 model
#    rotating at 300km/s is overstated by 35%.
#
# Explosion sets. LC18 report four sets which differ only in which stars explode. Sets F and M eject 0.07 Msun
# of 56Ni from every model; sets I and R let everything above 25 Msun collapse entirely to a black hole, so that
# only the wind is ejected. Set M (mixing and fallback) and set R are the two extremes usually quoted, and are
# the defaults converted here; use `--sets` to select others. Shipping both lets the explodability uncertainty
# be explored by swapping files.
#
# Models in the (pulsational) pair instability regime are excluded. LC18 stopped the evolution of these twelve
# models when the instability set in, and flag them with a remnant mass of -1, so their yields are not
# meaningful. Galacticus models pair-instability supernovae separately via the Heger & Woosley (2002) data.

orfeoBaseURL = "https://orfeo.iaps.inaf.it/2018-modelli"
cdsBaseURL   = "https://cdsarc.cds.unistra.fr/ftp/J/ApJS/237/13"
orfeoURL     = "http://orfeo.iaps.inaf.it"
paperURL     = "https://ui.adsabs.harvard.edu/abs/2018ApJS..237...13L"

# Explosion sets, and the column offset of each within the remnant mass table.
sets = {
    "F": {"offset":  0, "description": "every model ejects 0.07 Msun of 56Ni"                                 },
    "I": {"offset":  4, "description": "as set F below 25 Msun; above 25 Msun the star collapses entirely"     },
    "M": {"offset":  8, "description": "mixing and fallback, with the mass cut set to eject 0.07 Msun of 56Ni" },
    "R": {"offset": 12, "description": "as set M below 25 Msun; above 25 Msun the star collapses entirely"     },
}

# Metallicity labels used in the ORFEO model identifiers, and the corresponding [Fe/H].
metallicityLabels = {"a": 0, "b": -1, "c": -2, "d": -3}

# Rotation velocities.
velocities = (0, 150, 300)

def retrieve(url, fileName):
    """Download `url` to `fileName` unless it is already present, returning both so that the provenance can
    record the URL the data came from rather than a machine-specific cache path."""
    if not os.path.isfile(fileName):
        print(f"  downloading {url}")
        with urllib.request.urlopen(url, timeout=300) as response, open(fileName, 'wb') as file:
            shutil.copyfileobj(response, file)
    return fileName, url

def readYieldBlocks(fileName):
    """Read an ORFEO elemental yield table.

    The file holds one block per (metallicity, rotation velocity) combination. Each block opens with a header
    naming the nine mass columns (e.g. `013a000`), followed by one row per element carrying the element symbol,
    atomic number, mass number, the initial abundance, and the yield in each mass column. Returns a dict mapping
    the header tuple to its list of rows."""
    blocks  = {}
    current = None
    for line in open(fileName):
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "ele":
            current         = tuple(fields[4:])
            blocks[current] = []
        else:
            if current is None:
                raise ValueError(f"data row before any header in '{fileName}'")
            blocks[current].append(fields)
    if not blocks:
        raise ValueError(f"no yield blocks found in '{fileName}'")
    return blocks

def readRemnantMasses(fileName):
    """Read the ORFEO remnant mass table, returning {(mass, velocity, [Fe/H], set): remnantMass}."""
    remnants = {}
    for line in open(fileName):
        if not line.strip() or line.strip().startswith("M "):
            continue
        fields = line.split()
        mass, velocity = int(fields[0]), int(fields[1])
        values = [float(value) for value in fields[2:]]
        if len(values) != 16:
            raise ValueError(f"expected 16 remnant masses per row in '{fileName}', got {len(values)}")
        for setName, setData in sets.items():
            for index, metallicity in enumerate((0, -1, -2, -3)):
                remnants[(mass, velocity, metallicity, setName)] = values[setData["offset"]+index]
    return remnants

def readLifetimes(fileName):
    """Read lifetimes from the CDS copy of Table 5, returning {(mass, velocity, [Fe/H]): lifetime/Gyr}.

    Table 5 gives the duration of each evolutionary phase. Models stopped early repeat their final `PSN` row to
    pad the table to eight rows, so each phase is counted once."""
    phases = {}
    for line in open(fileName):
        if not line.strip():
            continue
        velocity    = int  (line[ 0:  3])
        metallicity = int  (line[ 4:  6])
        mass        = int  (line[ 7: 10])
        phase       =       line[11: 14].strip()
        duration    = float(line[15: 22])
        # Keep one entry per phase; repeated `PSN` rows are padding, not additional phases.
        phases.setdefault((mass, velocity, metallicity), {})[phase] = duration
    return {key: sum(durations.values())/1.0e9 for key, durations in phases.items()}

def convert(setName, velocity, yieldBlocks, grossBlocks, remnants, lifetimes, outputDirectory, atomicData,
            inputs):
    stars      = []
    excluded   = []
    for header, rows in yieldBlocks.items():
        # Every column in a block shares the metallicity and rotation velocity; take them from the first.
        if int(header[0][4:]) != velocity:
            continue
        metallicity = metallicityLabels[header[0][3]]
        # The initial metal mass fraction, summed over all elements heavier than helium.
        metalFraction = sum(float(row[3]) for row in rows if int(row[1]) > 2)
        grossRows     = grossBlocks[header]
        for column, tag in enumerate(header):
            mass     = int(tag[:3])
            remnant  = remnants[(mass, velocity, metallicity, setName)]
            if remnant < 0.0:
                # Flagged by LC18 as entering the (pulsational) pair instability regime; evolution was stopped
                # early, so the yields are not meaningful.
                excluded.append(tag)
                continue
            # Take the ejected mass from the gross yields rather than from the initial minus remnant mass. The
            # two agree, but the remnant masses are tabulated to only four decimal places, which for the models
            # that collapse almost entirely leaves the difference with barely three significant figures. Using
            # the summed yields also guarantees that the ejected mass and the yields are mutually consistent.
            massEjected      = sum(float(row[4+column]) for row in grossRows)
            massEjectedTable = mass-remnant
            # Consistency check. The tolerance admits the rounding of the tabulated remnant mass (worst case
            # 5e-5 Msun) while remaining far tighter than any genuine inconsistency, which would be of order a
            # Solar mass.
            if abs(massEjected-massEjectedTable) > max(1.0e-3*massEjectedTable, 1.0e-4):
                raise ValueError(f"model {tag} set {setName}: gross yields sum to {massEjected:.6f} Msun but "
                                 f"initial minus remnant mass is {massEjectedTable:.6f} Msun")
            elementYield = {}
            for row in rows:
                atomicNumber = int(row[1])
                if atomicNumber <= 2:
                    continue
                elementYield[atomicData.shortLabel(atomicNumber)] = float(row[4+column])
            lifetime = lifetimes.get((mass, velocity, metallicity))
            if lifetime is None:
                raise ValueError(f"no lifetime available for model {tag}")
            stars.append({
                "initialMass"      : float(mass),
                "metallicity"      : metalFraction,
                "lifetime"         : lifetime,
                "ejectedMass"      : massEjected,
                "metalYieldMass"   : sum(elementYield.values()),
                "elementYieldMass" : elementYield,
            })
    if not stars:
        raise RuntimeError(f"no models converted for set {setName}, v={velocity}")
    stars.sort(key=lambda star: (star["metallicity"], star["initialMass"]))
    provenance = Provenance(
        scienceSource       = (f"Limongi & Chieffi (2018, ApJS, 237, 13), explosion set {setName}, initial "
                               f"equatorial rotation velocity {velocity} km/s"),
        scienceURL          = paperURL,
        transcriptionSource = ("Yields and remnant masses from the ORFEO database; lifetimes from the CDS copy "
                               "of the paper's Table 5 (J/ApJS/237/13)"),
        transcriptionURL    = orfeoURL,
        generatedBy         = "galacticusDevTools/stellarYields/convertLimongiChieffi2018.py",
        inputs              = inputs,
        notes               = [f"Explosion set {setName}: {sets[setName]['description']}.",
                               "Yields are net elemental yields in Solar masses, and may be negative.",
                               "Ejected mass is the sum of the gross yields, verified equal to the initial mass "
                               "minus the tabulated remnant mass.",
                               "Lifetime is the sum of the durations of all evolutionary phases.",
                               "Covers initial masses of 13 Msun and above only, and so must be combined with a "
                               "source of asymptotic giant branch yields.",
                               ("Excluded as entering the (pulsational) pair instability regime: "
                                +(", ".join(sorted(excluded)) if excluded else "none"))],
    )
    fileName = os.path.join(outputDirectory,
                            f"stellarPropertiesLimongiChieffi2018_set{setName}_v{velocity:03d}.xml")
    writeStellarProperties(
        fileName   = fileName,
        stars      = stars,
        source     = (f"Limongi & Chieffi (2018, ApJS, 237, 13; explosion set {setName}, "
                      f"v_rot = {velocity} km/s)"),
        url        = paperURL,
        provenance = provenance,
    )
    metallicities = sorted({star["metallicity"] for star in stars})
    print(f"  set {setName}, v={velocity:3d} km/s: {len(stars):3d} models, "
          f"{len(excluded)} excluded, Z = {', '.join(f'{Z:.3e}' for Z in metallicities)}")
    print(f"    -> {fileName}")
    return fileName

def main():
    parser = argparse.ArgumentParser(description="Convert Limongi & Chieffi (2018) massive star models to "
                                                 "Galacticus XML format.")
    parser.add_argument("--sets", nargs="+", default=["M", "R"],
                        help="explosion sets to convert (default: M and R)")
    parser.add_argument("--velocities", nargs="+", type=int, default=list(velocities),
                        help="initial rotation velocities to convert (default: all)")
    parser.add_argument("--cache-directory", default="lc18Data", dest="cacheDirectory",
                        help="directory in which downloaded source tables are cached")
    parser.add_argument("--output-directory", default=None, dest="outputDirectory",
                        help="directory into which to write (default: "
                             "${GALACTICUS_DATA_PATH}/static/stellarAstrophysics)")
    arguments = parser.parse_args()
    for setName in arguments.sets:
        if setName not in sets:
            parser.error(f"unknown set '{setName}'; known sets are {', '.join(sorted(sets.keys()))}")
    for velocity in arguments.velocities:
        if velocity not in velocities:
            parser.error(f"unknown velocity '{velocity}'; known velocities are "
                         f"{', '.join(str(v) for v in velocities)}")
    outputDirectory = arguments.outputDirectory if arguments.outputDirectory is not None \
                      else stellarAstrophysicsPath()
    os.makedirs(arguments.cacheDirectory, exist_ok=True)
    atomicData = AtomicData()

    # Retrieve the shared inputs.
    print("Retrieving source tables")
    remnantArchive, remnantURL = retrieve(f"{orfeoBaseURL}/remas/remnant_masses.zip",
                                          os.path.join(arguments.cacheDirectory, "remnant_masses.zip"))
    with zipfile.ZipFile(remnantArchive) as archive:
        archive.extractall(arguments.cacheDirectory)
    remnantFile                = os.path.join(arguments.cacheDirectory, "remnant_masses.txt")
    lifetimeFile, lifetimeURL  = retrieve(f"{cdsBaseURL}/table5.dat",
                                          os.path.join(arguments.cacheDirectory, "table5.dat"))
    remnants     = readRemnantMasses(remnantFile )
    lifetimes    = readLifetimes    (lifetimeFile)

    print(f"Writing Limongi & Chieffi (2018) stellar properties to {outputDirectory}")
    for setName in arguments.sets:
        archiveName, archiveURL = retrieve(f"{orfeoBaseURL}/yields/tab_{setName}.tgz",
                                           os.path.join(arguments.cacheDirectory, f"tab_{setName}.tgz"))
        setDirectory = os.path.join(arguments.cacheDirectory, f"set{setName}")
        os.makedirs(setDirectory, exist_ok=True)
        with tarfile.open(archiveName) as archive:
            archive.extractall(setDirectory)
        netFile   = os.path.join(setDirectory, "tab_yieldsnet_ele_exp.dec")
        grossFile = os.path.join(setDirectory, "tab_yieldstot_ele_exp.dec")
        inputs    = [f"{url} (md5 {md5Checksum(name)})"
                     for name, url in ((archiveName , archiveURL ),
                                       (remnantArchive, remnantURL),
                                       (lifetimeFile, lifetimeURL))]
        yieldBlocks = readYieldBlocks(netFile  )
        grossBlocks = readYieldBlocks(grossFile)
        for velocity in arguments.velocities:
            convert(setName, velocity, yieldBlocks, grossBlocks, remnants, lifetimes, outputDirectory,
                    atomicData, inputs)

if __name__ == "__main__":
    sys.exit(main())
