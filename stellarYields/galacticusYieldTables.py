#!/usr/bin/env python3
import os
import re
import hashlib
import datetime
import xml.etree.ElementTree as ET
import xml.dom.minidom

# Shared helpers for converting published stellar yield tables into the XML formats read by Galacticus.
# Andrew Benson (09-August-2026); generated with assistance from Claude.

# Two formats are supported, matching the two readers in Galacticus:
#
#  * `stellarProperties` -- a `<stars>` document of per-star `<star>` elements, read by the
#    `stellarAstrophysicsFile` class (`source/stellar_astrophysics/file.F90`). Yields in this format are *net*
#    yields (newly synthesized minus destroyed, so they may be negative), while `ejectedMass` is the gross mass
#    returned to the ISM.
#
#  * `supernovaeTypeIaYields` -- a `<supernovaeYields>` document of per-isotope `<isotope>` elements, read by the
#    `supernovaeTypeIaFixedYield` class (`source/stellar_astrophysics/supernovae_type_Ia/fixed_yield.F90`). That
#    reader sums *every* isotope in the file to form the total metal yield, so the file must contain metals only
#    -- see `filterMetals()` below.
#
# Every file written carries a provenance comment recording where the numbers came from and how they were
# generated, so that a table can be traced back to its source and regenerated.

# Default location of the Galacticus datasets, and of the atomic data therein.
def dataPath():
    path = os.environ.get('GALACTICUS_DATA_PATH')
    if path is None:
        raise RuntimeError("the GALACTICUS_DATA_PATH environment variable must be set")
    return path

def stellarAstrophysicsPath():
    return os.path.join(dataPath(), 'static', 'stellarAstrophysics')

# Compute the md5 checksum of a file, used to pin the exact input a table was built from.
def md5Checksum(fileName):
    m = hashlib.md5()
    with open(fileName, 'rb') as file:
        for block in iter(lambda: file.read(8192), b''):
            m.update(block)
    return m.hexdigest()

class AtomicData:
    """Element symbol to atomic number mapping, read from Galacticus' own atomic data file.

    Using Galacticus' file (rather than an independent periodic table) guarantees that the short labels we write
    into `elementYieldMass<X>` tags are exactly those `Atomic_Short_Label()` will look for at run time."""

    def __init__(self, fileName=None):
        if fileName is None:
            fileName = os.path.join(dataPath(), 'static', 'abundances', 'Atomic_Data.xml')
        self.fileName      = fileName
        self._numberOf     = {}
        self._labelOf      = {}
        for element in ET.parse(fileName).getroot().findall('element'):
            atomicNumber = int(element.find('atomicNumber').text)
            shortLabel   =     element.find('shortLabel'  ).text.strip()
            self._numberOf[shortLabel.lower()] = atomicNumber
            self._labelOf [atomicNumber      ] = shortLabel

    def atomicNumber(self, symbol):
        """Return the atomic number of the given element symbol (case-insensitive)."""
        try:
            return self._numberOf[symbol.strip().lower()]
        except KeyError:
            raise KeyError(f"element '{symbol}' is not present in '{self.fileName}'")

    def shortLabel(self, atomicNumber):
        """Return the Galacticus short label for the given atomic number."""
        try:
            return self._labelOf[atomicNumber]
        except KeyError:
            raise KeyError(f"atomic number {atomicNumber} is not present in '{self.fileName}'")

# Split an isotope name of the form used by most published tables (e.g. "fe56", "c12") into its element symbol
# and mass number.
def parseIsotope(name):
    match = re.fullmatch(r'([A-Za-z]+)[-_]?([0-9]+)', name.strip())
    if match is None:
        raise ValueError(f"unable to parse isotope name '{name}'")
    return match.group(1), int(match.group(2))

# Retain only metals (atomic number greater than 2). The Galacticus Type Ia reader sums every isotope present in
# the file into the total metal yield, so hydrogen and helium must be excluded or the total is meaningless.
def filterMetals(isotopes):
    return [isotope for isotope in isotopes if isotope['atomicNumber'] > 2]

class Provenance:
    """Provenance record written as an XML comment into every generated file."""

    def __init__(self, scienceSource, scienceURL, transcriptionSource=None, transcriptionURL=None,
                 generatedBy=None, inputs=None, notes=None):
        self.scienceSource       = scienceSource
        self.scienceURL          = scienceURL
        self.transcriptionSource = transcriptionSource
        self.transcriptionURL    = transcriptionURL
        self.generatedBy         = generatedBy
        self.inputs              = inputs if inputs is not None else []
        self.notes               = notes  if notes  is not None else []
        self.retrieved           = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')

    def comment(self):
        lines = ["  Provenance:", f"  Science source      : {self.scienceSource}",
                 f"  Science URL         : {self.scienceURL}"]
        if self.transcriptionSource is not None:
            lines.append(f"  Transcription source: {self.transcriptionSource}")
        if self.transcriptionURL is not None:
            lines.append(f"  Transcription URL   : {self.transcriptionURL}")
        if self.generatedBy is not None:
            lines.append(f"  Generated by        : {self.generatedBy}")
        lines.append(f"  Retrieved           : {self.retrieved}")
        for input_ in self.inputs:
            lines.append(f"  Input               : {input_}")
        for note in self.notes:
            lines.append(f"  Note                : {note}")
        # The sequence "--" is illegal inside an XML comment, so neutralize any that appear in the content.
        return "\n" + "\n".join(line.replace('--', '- -') for line in lines) + "\n"

# Format a value for output. `repr` gives the shortest decimal string which reads back as exactly the same
# double, so values are never silently degraded -- which matters when an existing table is being restructured
# rather than converted, where any loss of precision would be a corruption of the source data.
def formatValue(value):
    return repr(float(value))

# Serialize an ElementTree root, with a leading provenance comment, as an indented XML file.
def _write(root, provenance, fileName):
    text     = ET.tostring(root, encoding='unicode')
    document = xml.dom.minidom.parseString(text)
    document.insertBefore(document.createComment(provenance.comment()), document.documentElement)
    pretty   = document.toprettyxml(indent="  ")
    # minidom emits blank lines where the source had none; strip them for readability.
    pretty   = "\n".join(line for line in pretty.split("\n") if line.strip() != "")
    os.makedirs(os.path.dirname(os.path.abspath(fileName)), exist_ok=True)
    with open(fileName, 'w') as file:
        file.write(pretty + "\n")
    return fileName

def writeSupernovaeTypeIaYields(fileName, isotopes, description, source, url, provenance):
    """Write a Type Ia supernova yield file.

    `isotopes` is a list of dicts with keys `element` (symbol), `massNumber`, `atomicNumber` and `yield`. Only
    metals should be present -- pass the list through `filterMetals()` first."""
    nonMetals = [isotope for isotope in isotopes if isotope['atomicNumber'] <= 2]
    if nonMetals:
        raise ValueError("hydrogen/helium isotopes must be removed before writing: "
                         "the Galacticus reader sums all isotopes into the total metal yield")
    root = ET.Element('supernovaeYields')
    ET.SubElement(root, 'description').text = description
    ET.SubElement(root, 'source'     ).text = source
    ET.SubElement(root, 'url'        ).text = url
    for isotope in sorted(isotopes, key=lambda i: (i['atomicNumber'], i['massNumber'])):
        node = ET.SubElement(root, 'isotope')
        ET.SubElement(node, 'name'        ).text = f"{isotope['massNumber']}{isotope['element']}"
        ET.SubElement(node, 'atomicMass'  ).text = f"{isotope['massNumber']}"
        ET.SubElement(node, 'atomicNumber').text = f"{isotope['atomicNumber']}"
        ET.SubElement(node, 'yield'       ).text = formatValue(isotope['yield'])
    return _write(root, provenance, fileName)

def writeStellarProperties(fileName, stars, source, url, provenance, fileFormat=1):
    """Write a stellar properties file.

    `stars` is a list of dicts. `initialMass` and `metallicity` are required; `lifetime`, `ejectedMass`,
    `metalYieldMass` and `elementYieldMass` (itself a dict of element symbol to net yield) are optional. Yields
    are *net* yields and may legitimately be negative."""
    root = ET.Element('stars')
    ET.SubElement(root, 'fileFormat').text = f"{fileFormat}"
    ET.SubElement(root, 'source'    ).text = source
    ET.SubElement(root, 'url'       ).text = url
    for star in stars:
        if 'initialMass' not in star or 'metallicity' not in star:
            raise ValueError("every star must have an initial mass and a metallicity")
        node = ET.SubElement(root, 'star')
        ET.SubElement(node, 'initialMass').text = formatValue(star['initialMass'])
        ET.SubElement(node, 'metallicity').text = formatValue(star['metallicity'])
        for name in ('lifetime', 'ejectedMass', 'metalYieldMass'):
            if star.get(name) is not None:
                ET.SubElement(node, name).text = formatValue(star[name])
        for element, yield_ in sorted(star.get('elementYieldMass', {}).items()):
            ET.SubElement(node, 'elementYieldMass'+element).text = formatValue(yield_)
    return _write(root, provenance, fileName)
