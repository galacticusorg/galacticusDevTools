#!/usr/bin/env python3
"""API naming-consistency audit for Galacticus.

Reports US-spelling violations (in identifiers, in documentation prose, in
Python, and in parameter files) and structural naming conventions for classes,
implementations, parameters, methods, modules, procedures, files, and output
property names.

Andrew Benson (09-September-2026).

Usage:

    namingAudit.py [--repo <dir>] [--catalog <file>] [--spelling] [--structural]
                   [--json <file>] [--sites <n>] [--quiet]

`--repo` defaults to `$GALACTICUS_EXEC_PATH`.  The structural scan needs the
parameter catalog, `parameters.catalog.json`; if it is not found the script
reports the command which builds it:

    python3 scripts/build/parameterCatalog.py <repo> <repo>/parameters.catalog.json

`--spelling` runs only the spelling scan, which needs no catalog and no build,
and is the mode intended for a lint job.

Findings are heuristic and are meant to be reviewed, not applied blindly; see
"Known limitations" at the foot of this file.
"""

import argparse
import collections
import glob
import json
import os
import re
import sys

# --------------------------------------------------------------- British spellings
# Stems which take "-ise"/"-isation" in British usage and "-ize"/"-ization" in US
# usage.  Matched with an explicit suffix list rather than a general rule so that
# words which are genuinely spelled "-ise" in US English (see ALLOW) are not hit.
ISE_STEMS = sorted(set([
    'apologis', 'authoris', 'capitalis', 'categoris', 'centralis', 'characteris',
    'civilis', 'colonis', 'criticis', 'crystallis', 'customis', 'deputis',
    'diagonalis', 'digitis', 'discretis', 'dramatis', 'emphasis', 'energis',
    'equalis', 'factoris', 'familiaris', 'fertilis', 'finalis', 'formalis',
    'fossilis', 'galvanis', 'generalis', 'globalis', 'harmonis', 'homogenis',
    'hospitalis', 'hypnotis', 'idealis', 'immobilis', 'immunis', 'individualis',
    'industrialis', 'initialis', 'internalis', 'ionis', 'italicis', 'jeopardis',
    'legalis', 'legitimis', 'liberalis', 'linearis', 'localis', 'magnetis',
    'marginalis', 'materialis', 'maximis', 'mechanis', 'memoris', 'metabolis',
    'minimis', 'mobilis', 'modernis', 'monopolis', 'moralis', 'nationalis',
    'naturalis', 'neutralis', 'normalis', 'optimis', 'organis', 'orthogonalis',
    'oxidis', 'parameteris', 'parametris', 'patronis', 'penalis', 'personalis',
    'plagiaris', 'polaris', 'popularis', 'pressuris', 'prioritis', 'pulveris',
    'quantis', 'radicalis', 'randomis', 'rationalis', 'realis', 'recognis',
    'regularis', 'reorganis', 'revolutionis', 'romanticis', 'sanitis',
    'satiris', 'scandalis', 'scrutinis', 'secularis', 'sensitis', 'serialis',
    'socialis', 'solemnis', 'specialis', 'stabilis', 'standardis', 'sterilis',
    'stigmatis', 'subsidis', 'summaris', 'symbolis', 'symmetris', 'synchronis',
    'synthesis', 'tabularis', 'temporis', 'terroris', 'theoris', 'traumatis',
    'trivialis', 'tyrannis', 'unionis', 'urbanis', 'utilis', 'vandalis',
    'vaporis', 'vectoris', 'verbalis', 'victimis', 'virtualis', 'visualis',
    'vocalis', 'westernis', 'womanis',
]))
_ISE_SUFFIXES = r'(?:e|es|ed|ing|ation|ations|able|er|ers)'

BRITISH = {
    r'^(?:' + '|'.join(ISE_STEMS) + r')' + _ISE_SUFFIXES + r'$': 'ise',
    r'^analys(?:e|ed|es|ing)$': 'analyse (analysis is fine)',
    r'^catalys(?:e|ed|es|ing)$': 'catalyse',
    r'^(?:colour|behaviour|favour|flavour|honour|neighbour|harbour|labour|vapour'
    r'|humour|armour|rumour|endeavour|savour|odour|tumour|vigour|rigour)'
    r'(?:s|ed|ing|able|ite|ly|ful)?$': 'our',
    r'^(?:centre|metre|litre|fibre|calibre|theatre|sombre|lustre|spectre'
    r'|manoeuvre|meagre|sabre|sceptre|louvre)(?:s|d)?$': 're',
    r'^(?:kilometre|millimetre|centimetre|micrometre|nanometre)s?$': 're',
    r'^(?:modell|labell|cancell|travell|levell|channell|signall|totall|fuell'
    r'|tunnell|marvell|quarrell|pedall|dialling|counsell|initiall)'
    r'(?:ed|ing|er|ers)$': 'll',
    r'^(?:catalogue|analogue|monologue|epilogue|prologue)(?:s|d)?$': 'ogue',
    r'^(?:haemo\w*|anaemi\w*|aeon|aeons|artefact|artefacts|aluminium|sulphur\w*'
    r'|programme|programmes|ageing|licence|licences|defence|defences|offence'
    r'|offences|practise|practised|practising|skilful|fulfil|enrol|instalment'
    r'|instalments|cheque|cheques|tyre|tyres|mould|moulds|moulded|smoulder\w*'
    r'|plough\w*|kerb|storey|storeys|jewellery|manoeuvr\w*|encyclopaedi\w*'
    r'|orthopaedic|paediatric|mediaeval|oestrogen|foetus|foetal|gaol|draught'
    r'|draughts|pyjamas|whisky|yoghurt|cosy|sceptic\w*|omelette|doughnut|grey'
    r'|greys|greyed|greying)$': 'misc',
}
BRITISH = {re.compile(pattern): kind for pattern, kind in BRITISH.items()}

# Words which are correct US spellings despite matching a pattern above.
ALLOW = set('''
    advertise advise apprise arise chastise comprise compromise concise despise
    devise disguise enterprise excise exercise expertise franchise improvise
    incise likewise merchandise mise noise otherwise precise premise premises
    promise promised promises raise reprise revise rise supervise surprise
    televise wise analyses analysis spectra spectrum
    megaparsec megaparsecs kiloparsec kiloparsecs gigaparsec gigaparsecs parsec
    parsecs programme
'''.split())


def load_dictionary(repo):
    """Return the words from `aux/words.dict`, lower-cased.

    This is the dictionary the documentation spelling builder uses.  Honouring it
    here keeps the two checks consistent and, in particular, suppresses proper
    names -- of people (`Storey`, of Storey & Hummer), codes, and simulations --
    which the patterns above would otherwise flag.  Add new technical terms and
    proper names there, not here; it must not be used for British spellings.
    """
    path = os.path.join(repo, 'aux', 'words.dict')
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return {line.strip().lower() for line in fh if line.strip()}
    except OSError:
        print(f"namingAudit.py: warning: could not read {path}; proper names "
              f"will not be suppressed", file=sys.stderr)
        return set()


def split_identifier(name):
    """Split a camelCase / Upper_Snake_Case identifier into lower-cased words."""
    parts = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', name.replace('_', ' '))
    return [word.lower() for word in parts.split() if word]


def british_hits(words, dictionary):
    """Return [(word, kind)] for each word which looks like a British spelling."""
    hits = []
    for word in words:
        if word in ALLOW or word in dictionary:
            continue
        for pattern, kind in BRITISH.items():
            if pattern.match(word):
                hits.append((word, kind))
                break
    return hits


# ------------------------------------------------------------------ text extraction
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
WORD = re.compile(r"[A-Za-z]+(?:'[a-z]+)?")

# Sphinx/reStructuredText constructs whose content is not prose and is not
# spell-checked by Sphinx either: interpreted-text roles (`:cite:t:`key``,
# `:term:`X``, `:math:`...``) and inline literals (` ``code`` `).  Stripping them
# removes, among others, the BibTeX citation keys (`font_colours_2008`,
# `meiksin_colour_2006`) which otherwise read as the British spelling "colour".
RST_ROLE = re.compile(r':[a-zA-Z0-9_+:.-]+:`[^`]*`')
RST_LITERAL = re.compile(r'``[^`]*``')
RST_TARGET = re.compile(r'`[^`]*`_')


def strip_rst(text):
    """Remove RST roles and inline literals, whose content is not prose."""
    text = RST_ROLE.sub(' ', text)
    text = RST_LITERAL.sub(' ', text)
    text = RST_TARGET.sub(' ', text)
    return text


FORTRAN_SUFFIXES = ('.F90', '.Inc', '.inc', '.f', '.f90')

_DIRECTIVE_OPEN = re.compile(r'!!\[')
_DIRECTIVE_CLOSE = re.compile(r'!!\]')
_RST_OPEN = re.compile(r'!!\{')
_RST_CLOSE = re.compile(r'!!\}')
# Prose-bearing elements within an XML directive block.
_PROSE_ELEMENT = re.compile(
    r'<(description|label|comment|unitsDescription)>(.*?)</\1>', re.S)


def classify_fortran(text):
    """Split a Fortran source into (codeLines, proseLines), each [(lineNumber, text)].

    A Galacticus source file carries three kinds of text, and conflating them is
    the main source of both missed hits and false positives:

    * `!![ ... !!]` XML directive blocks -- the `<description>` elements of which
      are rendered into the manual and *are* spell-checked by Sphinx.  Their text
      is prose; the surrounding XML tags and attributes are neither prose nor
      Fortran identifiers, and are ignored.
    * `!!{RST ... !!}` documentation blocks -- prose.
    * `!` comments -- prose.  Everything else is Fortran code.

    Scanning directive blocks as code (as the first version of this script did)
    both hides the description prose from the spelling check and pulls BibTeX
    citation keys in as though they were identifiers.
    """
    lines = text.split('\n')
    code, prose = [], []
    in_directive = in_rst = False
    directive = []                                     # (lineNumber, text)
    for number, line in enumerate(lines, start=1):
        if not in_directive and not in_rst:
            if _DIRECTIVE_OPEN.search(line):
                in_directive = True
                directive = [(number, line[_DIRECTIVE_OPEN.search(line).end():])]
                if _DIRECTIVE_CLOSE.search(directive[0][1]):
                    in_directive = False
                    prose.extend(_directive_prose(directive))
                continue
            if _RST_OPEN.search(line):
                in_rst = True
                rest = line[_RST_OPEN.search(line).end():]
                rest = re.sub(r'^RST\b', '', rest)
                if _RST_CLOSE.search(rest):
                    in_rst = False
                    rest = rest[:_RST_CLOSE.search(rest).start()]
                prose.append((number, rest))
                continue
            if '!' in line:
                head, comment = line.split('!', 1)
                if head.strip():
                    code.append((number, head))
                prose.append((number, comment))
            else:
                code.append((number, line))
            continue
        if in_directive:
            if _DIRECTIVE_CLOSE.search(line):
                directive.append((number, line[:_DIRECTIVE_CLOSE.search(line).start()]))
                in_directive = False
                prose.extend(_directive_prose(directive))
            else:
                directive.append((number, line))
            continue
        if in_rst:
            if _RST_CLOSE.search(line):
                prose.append((number, line[:_RST_CLOSE.search(line).start()]))
                in_rst = False
            else:
                prose.append((number, line))
    return code, prose


def _directive_prose(directive):
    """Return the prose-bearing text of an XML directive block, with line numbers."""
    if not directive:
        return []
    joined = '\n'.join(text for _, text in directive)
    first = directive[0][0]
    result = []
    for match in _PROSE_ELEMENT.finditer(joined):
        offset = joined[:match.start(2)].count('\n')
        for index, line in enumerate(match.group(2).split('\n')):
            result.append((first + offset + index, line))
    return result


def scan_files(paths, root, mode, dictionary):
    """Scan `paths`, returning {word: Counter({'path:line': count})}.

    `mode` is 'fortran' (classify code and prose, reporting both separately),
    'python', or 'text' (parameter files and other markup).
    """
    found = {'identifiers': collections.defaultdict(collections.Counter),
             'prose': collections.defaultdict(collections.Counter)}
    for path in paths:
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError:
            continue
        relative = os.path.relpath(path, root)
        if mode == 'fortran':
            code, prose = classify_fortran(text)
            _record(found['identifiers'], code, relative, dictionary, 'identifiers')
            _record(found['prose'], prose, relative, dictionary, 'prose')
        else:
            lines = list(enumerate(text.split('\n'), start=1))
            # Python and markup are scanned as a whole: identifiers, strings, and
            # comments are all author-written text subject to the same rule.
            _record(found['prose'], lines, relative, dictionary,
                    'both' if mode == 'python' else 'prose')
    return found


def _record(target, lines, relative, dictionary, kind):
    """Accumulate British-spelling hits from `lines` into `target`.

    `kind` selects how a line is read: 'identifiers' splits camelCase and
    Upper_Snake_Case identifiers into words, 'prose' takes ordinary words, and
    'both' takes the union of the two -- deduplicated per line, so that a word
    which is both an identifier fragment and a plain word is counted once.
    """
    for number, line in lines:
        identifiers = []
        for identifier in IDENTIFIER.findall(line):
            identifiers += split_identifier(identifier)
        prose = [w.lower() for w in WORD.findall(strip_rst(line))]
        if kind == 'identifiers':
            words = identifiers
        elif kind == 'prose':
            words = prose
        else:
            words = sorted(set(identifiers) | set(prose))
        for word, _kind in british_hits(words, dictionary):
            target[word][f'{relative}:{number}'] += 1


# ------------------------------------------------------------------ structural scan
QUALIFIER = {
    'minimum', 'maximum', 'initial', 'final', 'mean', 'total', 'virial',
    'stellar', 'halo', 'scale', 'core', 'outer', 'inner', 'characteristic',
    'critical', 'reference', 'central', 'peak', 'cutoff', 'threshold',
    'effective', 'relative', 'absolute', 'logarithmic', 'specific',
    'fractional', 'fixed', 'lower', 'upper', 'low', 'high', 'old', 'new',
    'first', 'last', 'max', 'min',
}
NOUN = {
    'mass', 'radius', 'radii', 'time', 'times', 'redshift', 'velocity',
    'density', 'temperature', 'energy', 'luminosity', 'age', 'metallicity',
    'fraction', 'count', 'index', 'wavelength', 'wavenumber', 'angle',
    'momentum', 'length', 'scale', 'magnitude', 'distance', 'rate',
    'timescale', 'concentration', 'spin', 'tolerance', 'step', 'width',
    'height', 'number', 'size', 'pressure', 'entropy', 'frequency',
}
BOOLEAN_PREFIX = re.compile(
    r'^(?:is|are|use|uses|include|includes|apply|applies|allow|allows|enforce|'
    r'require|requires|report|reports|store|stores|output|outputs|ignore|skip|'
    r'enable|disable|force|check|assume|assumes|treat|reuse|track|tracks|write|'
    r'read|compute|computes|show|has|have|do|does|can|verbose|dump|debug|'
    r'exclude|fail|fails|halt|abort|warn|remove|fix|match|matches|correct|'
    r'strict|invert|accept|permit|convert|converts|resolve|interpolate|'
    r'extrapolate|truncate|tabulate|log|flag|test|run|perform|update|create|'
    r'build|builds|add|adds|append|appends|collect|collects|extract|extracts|'
    r'emulate|flush|label|labels|load|merge|merges|analyze|analyse|evolve|'
    r'process|randomize|normalize|diagonalize|initialize|fill|bin|branch|'
    r'starve|backtrack|group|only|non)')
# Consonant runs which occur in ordinary (usually proper) names and are not a
# sign of a vowel-stripped abbreviation.
_CONSONANT_RUN = re.compile(r'[bcdfghjklmnpqrstvwxz]{5,}')


def structural_scan(catalog, fortran, root, dictionary):
    """Return the structural findings for the given parameter catalog."""
    implementations = catalog['implementations']
    classes = collections.defaultdict(list)
    for name, record in implementations.items():
        classes[record['functionClass']].append(name)

    structural = {}

    # Implementation names must be the class name plus an UpperCamelCase suffix.
    bad_prefix, abbreviations = [], []
    for klass, names in classes.items():
        for name in names:
            if not name.startswith(klass):
                bad_prefix.append((klass, name))
                continue
            suffix = name[len(klass):]
            if suffix and not suffix[0].isupper():
                bad_prefix.append((klass, name))
            for run in _CONSONANT_RUN.finditer(suffix):
                # A consonant run inside a word which is in `words.dict` (e.g.
                # "Bertschinger") is a proper name, not an abbreviation.
                word = _enclosing_word(suffix, run.start())
                if word.lower() not in dictionary:
                    abbreviations.append((klass, name))
                    break
    structural['implementationPrefix'] = bad_prefix
    structural['truncatedAbbreviations'] = sorted(set(abbreviations))
    structural['classNameStyle'] = [c for c in classes
                                    if not re.fullmatch(r'[a-z][A-Za-z0-9]*', c)]

    # Parameter names.
    parameters = collections.defaultdict(set)
    parameter_types = collections.defaultdict(set)
    for record in implementations.values():
        for parameter in record['parameters']:
            if parameter.get('provenance') != 'default':
                continue
            parameters[parameter['name']].add(record['functionClass'])
            parameter_types[parameter['name']].add(parameter.get('type'))
    structural['parameterStyle'] = sorted(
        n for n in parameters if not re.fullmatch(r'[a-z][A-Za-z0-9]*', n))
    adjective_first = []
    for name in parameters:
        words = split_identifier(name)
        if len(words) >= 2 and words[0] in QUALIFIER and words[1] in NOUN:
            adjective_first.append(name)
    structural['parameterAdjectiveFirst'] = sorted(adjective_first)
    lowered = {n.lower(): n for n in parameters}
    pairs = []
    for name in adjective_first:
        words = split_identifier(name)
        swapped = words[1] + words[0].capitalize() + \
            ''.join(w.capitalize() for w in words[2:])
        if swapped.lower() in lowered:
            other = lowered[swapped.lower()]
            pairs.append((name, other,
                          sorted(parameters[name]), sorted(parameters[other])))
    structural['parameterBothOrders'] = pairs
    structural['booleanNotPredicate'] = sorted(
        name for name, types in parameter_types.items()
        if types == {'boolean'} and not BOOLEAN_PREFIX.match(name))

    # Method names, from the functionClass directives.
    methods = collections.defaultdict(set)
    for path in fortran:
        if not path.endswith('_class.F90'):
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError:
            continue
        for block in re.finditer(r'<functionClass\b[^>]*>(.*?)</functionClass>',
                                 text, re.S):
            owner = re.search(r'<name>\s*([^<\s]+)\s*</name>', block.group(1))
            if not owner:
                continue
            for method in re.finditer(r'<method\s+name="([^"]+)"', block.group(1)):
                methods[method.group(1)].add(owner.group(1))
    by_words = collections.defaultdict(set)
    for method in methods:
        by_words[tuple(sorted(split_identifier(method)))].add(method)
    structural['methodNameVariants'] = [
        (sorted(group), {m: sorted(methods[m]) for m in group})
        for group in by_words.values() if len(group) > 1]
    structural['methodStyle'] = sorted(
        m for m in methods if not re.fullmatch(r'[a-z][A-Za-z0-9]*', m))

    # Modules, procedures, and file names.
    module_names = []
    procedure_styles = collections.Counter()
    legacy_directories = collections.Counter()
    procedure = re.compile(
        r'^\s*(?:(?:pure|elemental|recursive|impure|module)\s+)*'
        r'(?:(?:double\s+precision|integer|logical|real|complex|character|type|class)'
        r'\s*(?:\([^)]*\))?\s*(?:\([^)]*\))?\s+)?(function|subroutine)\s+'
        r'([A-Za-z_][A-Za-z0-9_]*)', re.I)
    for path in fortran:
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                lines = fh.read().split('\n')
        except OSError:
            continue
        for line in lines:
            module = re.match(r'^\s*module\s+([A-Za-z_]\w*)\s*$', line, re.I)
            if module:
                module_names.append((module.group(1), os.path.relpath(path, root)))
            if line.lstrip().startswith('!'):
                continue
            match = procedure.match(line.split('!')[0])
            if match and not re.match(r'^\s*end\b', line, re.I):
                name = match.group(2)
                if '_' in name and name[0].isupper():
                    style = 'Upper_Snake'
                elif re.fullmatch(r'[a-z][A-Za-z0-9]*', name):
                    style = 'lowerCamel'
                elif re.fullmatch(r'[A-Z][A-Za-z0-9]*', name):
                    style = 'UpperCamel'
                else:
                    style = 'other'
                procedure_styles[style] += 1
                if style == 'Upper_Snake':
                    relative = os.path.relpath(path, os.path.join(root, 'source'))
                    legacy_directories[os.path.dirname(relative).split('/')[0]] += 1
    structural['moduleNameStyleBad'] = [
        (n, f) for n, f in module_names
        if not re.fullmatch(r'[A-Z][A-Za-z0-9]*(_[A-Za-z0-9]+)*', n)]
    structural['procedureStyles'] = dict(procedure_styles)
    structural['legacyProcedureDirs'] = legacy_directories.most_common(12)
    files = [os.path.relpath(f, os.path.join(root, 'source')) for f in fortran]
    structural['fileNamesWithHyphen'] = sorted(
        f for f in files if '-' in os.path.basename(f))

    # Property-extractor output names.  Note that an extractor may compose its
    # dataset name from a prefix and this value (for example
    # `'darkMatterProfileDMO'//propertyName`), in which case an initial capital
    # is correct; such names are reported separately rather than as defects.
    output_names = collections.Counter()
    composed = set()
    for path in fortran:
        if '/nodes/property_extractor/' not in path.replace(os.sep, '/'):
            continue
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError:
            continue
        prefixed = bool(re.search(r"var_str\(\s*'[A-Za-z][A-Za-z0-9_]*'\s*//", text))
        for match in re.finditer(r"var_str\(\s*'([A-Za-z][A-Za-z0-9_:]*)'\s*\)", text):
            output_names[match.group(1)] += 1
            if prefixed:
                composed.add(match.group(1))
    structural['outputNameStyleBad'] = sorted(
        n for n in output_names
        if not re.fullmatch(r'[a-z][A-Za-z0-9]*(:[A-Za-z0-9]+)*', n)
        and n not in composed)
    structural['outputNameComposedSuffix'] = sorted(composed)
    structural['outputNameCount'] = len(output_names)
    return structural


def _enclosing_word(text, position):
    """Return the CamelCase word of `text` containing `position`."""
    start = position
    while start > 0 and not text[start].isupper():
        start -= 1
    end = position + 1
    while end < len(text) and not text[end].isupper():
        end += 1
    return text[start:end]


# ------------------------------------------------------------------------- driver
def find_catalog(repo, explicit):
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for candidate in (os.path.join(repo, 'parameters.catalog.json'),
                      os.path.join(repo, 'work', 'build', 'parameters.catalog.json')):
        if os.path.exists(candidate):
            return candidate
    return None


def summarize(found, sites):
    return {word: {'count': sum(counter.values()),
                   'sites': sorted(counter)[:sites]}
            for word, counter in sorted(found.items(),
                                        key=lambda kv: -sum(kv[1].values()))}


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='API naming-consistency audit for Galacticus.')
    parser.add_argument('--repo', default=os.environ.get('GALACTICUS_EXEC_PATH'),
                        help='Galacticus repository root (default: $GALACTICUS_EXEC_PATH)')
    parser.add_argument('--catalog', default=None,
                        help='path to parameters.catalog.json (structural scan only)')
    parser.add_argument('--spelling', action='store_true',
                        help='run only the spelling scan (needs no catalog)')
    parser.add_argument('--structural', action='store_true',
                        help='run only the structural scan')
    parser.add_argument('--json', default='namingAudit.json',
                        help='write the full findings here (default: namingAudit.json)')
    parser.add_argument('--sites', type=int, default=6,
                        help='number of example sites to record per word (default: 6)')
    parser.add_argument('--quiet', action='store_true',
                        help='write the JSON but print no summary')
    options = parser.parse_args(argv)

    if not options.repo:
        parser.error('no repository given; pass --repo or set GALACTICUS_EXEC_PATH')
    root = os.path.abspath(options.repo)
    if not os.path.isdir(os.path.join(root, 'source')):
        parser.error(f'{root} does not look like a Galacticus checkout (no source/)')

    do_spelling = options.spelling or not options.structural
    do_structural = options.structural or not options.spelling

    dictionary = load_dictionary(root)
    fortran = sorted(set(
        glob.glob(os.path.join(root, 'source', '**', '*.F90'), recursive=True) +
        glob.glob(os.path.join(root, 'source', '**', '*.[Ii]nc'), recursive=True)))
    fortran = [f for f in fortran if '/external/' not in f.replace(os.sep, '/')]

    output = {'counts': {}}

    if do_spelling:
        python = (glob.glob(os.path.join(root, 'python', '**', '*.py'), recursive=True) +
                  glob.glob(os.path.join(root, 'scripts', '**', '*.py'), recursive=True) +
                  glob.glob(os.path.join(root, 'testSuite', '*.py')))
        markup = (glob.glob(os.path.join(root, 'parameters', '**', '*.xml'), recursive=True) +
                  glob.glob(os.path.join(root, 'testSuite', '**', '*.xml'), recursive=True) +
                  glob.glob(os.path.join(root, 'constraints', '**', '*.xml'), recursive=True))
        fortran_found = scan_files(fortran, root, 'fortran', dictionary)
        python_found = scan_files(python, root, 'python', dictionary)
        markup_found = scan_files(markup, root, 'text', dictionary)
        spelling = {
            'fortranIdentifiers': fortran_found['identifiers'],
            'fortranProse': fortran_found['prose'],
            'pythonIdentifiersAndProse': python_found['prose'],
            'parameterFiles': markup_found['prose'],
        }
        output['spelling'] = {k: summarize(v, options.sites)
                              for k, v in spelling.items()}

    if do_structural:
        catalog_path = find_catalog(root, options.catalog)
        if catalog_path is None:
            print('namingAudit.py: no parameter catalog found. Build one with:\n'
                  f'    python3 {os.path.join("scripts", "build", "parameterCatalog.py")}'
                  f' {root} {os.path.join(root, "parameters.catalog.json")}\n'
                  '  or pass --catalog <file>, or run with --spelling to skip the '
                  'structural scan.', file=sys.stderr)
            return 2
        with open(catalog_path, encoding='utf-8') as fh:
            catalog = json.load(fh)
        output['structural'] = structural_scan(catalog, fortran, root, dictionary)
        output['counts'].update({
            'classes': len({r['functionClass']
                            for r in catalog['implementations'].values()}),
            'implementations': len(catalog['implementations']),
        })

    with open(options.json, 'w', encoding='utf-8') as fh:
        json.dump(output, fh, indent=1, default=list)

    if options.quiet:
        return 0
    if 'spelling' in output:
        print('Spelling:')
        for section, words in output['spelling'].items():
            total = sum(w['count'] for w in words.values())
            print(f'  {section:28s} {len(words):3d} distinct, {total:4d} occurrences')
    if 'structural' in output:
        print('Structural:')
        for key in ('implementationPrefix', 'truncatedAbbreviations',
                    'classNameStyle', 'parameterStyle', 'parameterAdjectiveFirst',
                    'parameterBothOrders', 'booleanNotPredicate',
                    'methodNameVariants', 'methodStyle', 'moduleNameStyleBad',
                    'fileNamesWithHyphen', 'outputNameStyleBad',
                    'outputNameComposedSuffix'):
            print(f'  {key:28s} {len(output["structural"][key]):4d}')
        print(f'  procedureStyles              {output["structural"]["procedureStyles"]}')
    print(f'\nFull findings written to {options.json}')
    return 0


# --------------------------------------------------------------- Known limitations
# * The British word list is explicit rather than a dictionary diff, so unusual
#   forms are missed; the counts are lower bounds.
# * Identifier splitting treats digits and acronyms heuristically.
# * Output dataset names are collected from `var_str('...')` literals, which
#   misses names assembled at run time.  Where an extractor composes its name
#   from a prefix, the literal is reported under `outputNameComposedSuffix`
#   rather than as a style defect, since an initial capital is correct there.
# * `parameterBothOrders` and `booleanNotPredicate` are review aids: an
#   adjective-first name may be an established physics term, and a boolean named
#   for a noun may still read well.  See the "Naming conventions" section of the
#   Galacticus developer guide for the conventions and their exceptions.

if __name__ == '__main__':
    sys.exit(main())
