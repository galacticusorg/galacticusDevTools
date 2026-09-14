#!/usr/bin/env python3
"""Sweep Galacticus functionClass implementations for cross-class contract
inconsistencies (the issue #1441 archetypes).

Checks:
  C1  optional-argument contracts: base-class <code> constraints, per-implementation
      requirements (explicit or implicit), and consumer call sites that violate them.
  C2  capability stubs: method overrides that only raise "not supported"-style
      errors, versus consumers that call those methods on the generic class.
  C3  null-default hazards: consumers compositing a class whose default
      implementation is `null` and calling methods whose null body errors or
      returns a sentinel.
  C4  inherited base-class defaults: methods with base <code> and the
      implementations that inherit it.
  C5  parameter-convention drift within a class (from the parameter catalog).
"""
import json, os, re, sys, collections
sys.path.insert(0, os.path.join(os.environ['GALACTICUS_EXEC_PATH'], 'python'))
from Galacticus.Build.Directives import extract_directives

SRC = os.path.join(os.environ['GALACTICUS_EXEC_PATH'], 'source')

def listify(x):
    if x is None: return []
    return x if isinstance(x, list) else [x]

# ---------------------------------------------------------------- scan files
files = []
for root, _, names in os.walk(SRC):
    for n in names:
        if n.endswith('.F90'):
            files.append(os.path.join(root, n))
files.sort()

classes = {}          # className -> dict
directives_by_file = {}
for f in files:
    try:
        ds = extract_directives(f, '*', set_root_element_type=True)
    except Exception as e:
        ds = []
    directives_by_file[f] = ds
    for d in ds:
        if d.get('rootElementType') == 'functionClass':
            methods = {}
            for m in listify(d.get('method')):
                args = []
                for a in listify(m.get('argument')):
                    if '::' not in a: continue
                    decl, names = a.split('::', 1)
                    optional = 'optional' in decl
                    for nm in names.split(','):
                        nm = nm.strip()
                        if nm: args.append((nm, optional))
                methods[m['name']] = {'args': args, 'code': m.get('code'), 'type': m.get('type'), 'description': (m.get('description') or '').strip()}
            classes[d['name']] = {'file': f, 'default': d.get('default'), 'methods': methods, 'implementations': {}}

class_names = set(classes)
lower_class = {c.lower(): c for c in class_names}

# ---------------------------------------------------------------- implementations
type_re = re.compile(r'^\s*type\s*,\s*extends\s*\(\s*(\w+)\s*\)\s*(?:,\s*\w+\s*)*::\s*(\w+)', re.I)
proc_re = re.compile(r'^\s*procedure\s*(?:,\s*[\w ]+)?\s*::\s*(\w+)\s*(?:=>\s*(\w+))?', re.I)
end_type_re = re.compile(r'^\s*end\s+type', re.I)
impls = {}   # implName -> dict(class, parent, file, overrides{method: proc}, ...)
file_text = {}
for f in files:
    with open(f, errors='replace') as fh:
        lines = fh.read().split('\n')
    file_text[f] = lines
    impl_names = {d['name']: d['rootElementType'] for d in directives_by_file[f] if d.get('rootElementType') in class_names and d.get('name')}
    i = 0
    while i < len(lines):
        m = type_re.match(lines[i])
        if m:
            parent, name = m.group(1), m.group(2)
            overrides = {}
            j = i + 1
            while j < len(lines) and not end_type_re.match(lines[j]):
                pm = proc_re.match(lines[j])
                if pm:
                    overrides[pm.group(1)] = pm.group(2) or pm.group(1)
                j += 1
            if name in impl_names:
                impls[name] = {'class': impl_names[name], 'parent': parent, 'file': f, 'overrides': overrides}
            i = j
        i += 1

# resolve inherited overrides through implementation chains
def resolved_overrides(name, seen=None):
    seen = seen or set()
    if name in seen or name not in impls: return {}
    seen.add(name)
    d = impls[name]
    parent = d['parent']
    base = {}
    if parent in impls:
        base = dict(resolved_overrides(parent, seen))
    base.update({k: (v, name) for k, v in d['overrides'].items()} if False else {k: (v, d['file']) for k, v in d['overrides'].items()})
    return base
for name, d in impls.items():
    d['resolved'] = resolved_overrides(name)
    classes[d['class']]['implementations'][name] = d

# ---------------------------------------------------------------- procedure bodies
body_cache = {}
def procedure_body(f, proc):
    key = (f, proc.lower())
    if key in body_cache: return body_cache[key]
    lines = file_text[f]
    start = re.compile(r'^\s*(?:[\w\s\(\),:=]*?\b)?(function|subroutine)\s+' + re.escape(proc) + r'\s*\(', re.I)
    end = re.compile(r'^\s*end\s+(function|subroutine)\s+' + re.escape(proc) + r'\b', re.I)
    body = None
    for i, l in enumerate(lines):
        if start.match(l):
            for j in range(i + 1, len(lines)):
                if end.match(lines[j]):
                    body = lines[i:j + 1]; break
            break
    body_cache[key] = body
    return body

def code_lines(body):
    """Strip comments, declarations, and the signature; join continuation lines
    into logical statements."""
    stmts, buf = [], ''
    for l in body[1:]:
        s = l.split('!')[0].rstrip() if not l.strip().startswith('!$') else ''
        s = s.strip()
        if not s: continue
        if buf:
            s = s.lstrip('&').strip()
        if s.endswith('&'):
            buf += ' ' + s.rstrip('&').strip(); continue
        stmt = (buf + ' ' + s).strip() if buf else s
        buf = ''
        if re.match(r'^(use|implicit)\b', stmt, re.I): continue
        if re.match(r'^(class|type|integer|double|logical|character|real|complex|procedure)\b', stmt, re.I) and '::' in stmt: continue
        if re.match(r'^end\s+(function|subroutine)', stmt, re.I): continue
        stmts.append(stmt)
    return stmts

def strip_call_args(s):
    """Remove the argument lists of type-bound and plain procedure calls (but
    not of intrinsics), so positional pass-through is not counted as a use."""
    out, i = '', 0
    intrinsics = {'size','allocated','associated','abs','log','log10','exp','sqrt','dble','int','max','min','sum','maxval','minval','trim','char','len','present','huge','sign','mod','nint','floor','ceiling','real','merge','any','all','count'}
    while i < len(s):
        m = re.match(r'(%\s*\w+|(?<![\w%])\w+)\s*\(', s[i:])
        if m and (m.group(1).startswith('%') or m.group(1).lower() not in intrinsics) and not re.match(r'^(if|else\s*if|do|select|where|while)\b', m.group(1), re.I):
            # skip balanced parentheses
            j = i + m.end() - 1; depth = 0
            while j < len(s):
                if s[j] == '(': depth += 1
                elif s[j] == ')':
                    depth -= 1
                    if depth == 0: break
                j += 1
            out += s[i:i + m.end() - 1] + '()'
            i = j + 1
        else:
            out += s[i]; i += 1
    return out

def uses_in_expression(stmts, nm):
    """True if optional argument `nm` is used where absence would be an error
    (component access, indexing, intrinsic query, condition, assignment RHS),
    as opposed to being passed through to another optional dummy."""
    pat = re.escape(nm)
    for st in stmts:
        s = re.sub(r'\bpresent\s*\(\s*' + pat + r'\s*\)', '', st, flags=re.I)
        if not re.search(r'(?<![\w%])' + pat + r'\b', s, re.I): continue
        if re.search(r'(?<![\w%])' + pat + r'\s*[%(]', s, re.I): return True
        if re.search(r'\b(size|allocated|associated|abs|log|log10|exp|sqrt|dble|int|max|min|sum|maxval|minval|trim|char|len)\s*\(\s*' + pat + r'\b', s, re.I): return True
        if re.match(r'^\s*(if|else\s*if|do|select\s+case|where)\b', s, re.I) and re.search(r'(?<![\w%])' + pat + r'\b', strip_call_args(s), re.I): return True
        if re.match(r'^\s*(?!call\b)[\w%()\s,]+=(?!=)', s):
            # assignment whose RHS mentions the name outside any procedure-call argument list
            rhs = strip_call_args(s.split('=', 1)[1])
            if re.search(r'(?<![\w%])' + pat + r'\b', rhs, re.I): return True
    return False

UNSUPPORTED_RE = re.compile(r"Error_Report\s*\(\s*['\"]([^'\"]*(?:not (?:implemented|supported|available|defined|applicable|possible)|unsupported|does not support|can ?not (?:be|use|compute)|only .* (?:is|are) supported|is not supported|no .* is available)[^'\"]*)", re.I)

def analyze_body(body, args):
    """Return constraints for a method body given its argument list."""
    info = {'requires': set(), 'ignores': set(), 'forbids': [], 'stub': None, 'errors': [], 'sentinel': False, 'explicit': set()}
    if body is None: return info
    text = '\n'.join(body)
    cl = code_lines(body)
    unused = set()
    for l in body:
        mu = re.search(r'!\$GLC attributes unused\s*::\s*(.*)', l)
        if mu:
            unused.update(x.strip() for x in mu.group(1).split(','))
    joined = '\n'.join(cl)
    info['explicit'] = set()
    guarded = set(m.group(1) for m in re.finditer(r'<optionalArgument\s+name\s*=\s*"(\w+)"', text, re.I))
    for nm, optional in args:
        if not optional: continue
        present_used = nm in guarded or re.search(r'\bpresent\s*\(\s*' + re.escape(nm) + r'\s*\)', joined, re.I)
        referenced = re.search(r'(?<![\w%])' + re.escape(nm) + r'\b', re.sub(r'\bpresent\s*\(\s*' + re.escape(nm) + r'\s*\)', '', joined, flags=re.I), re.I)
        if nm in unused or not referenced:
            info['ignores'].add(nm)
        elif not present_used and uses_in_expression(cl, nm):
            info['requires'].add(nm)
    for m in re.finditer(r'if\s*\(\s*\.not\.\s*present\s*\(\s*(\w+)\s*\)\s*\)\s*call\s+Error_Report', joined, re.I):
        info['requires'].add(m.group(1)); info['explicit'].add(m.group(1)); info['ignores'].discard(m.group(1))
    for m in re.finditer(r'if\s*\(\s*present\s*\(\s*(\w+)\s*\)\s*\.and\.\s*present\s*\(\s*(\w+)\s*\)\s*\)\s*call\s+Error_Report', joined, re.I):
        info['forbids'].append((m.group(1), m.group(2)))
    for m in re.finditer(r'if\s*\(\s*\.not\.\s*present\s*\(\s*(\w+)\s*\)\s*\.and\.\s*\.not\.\s*present\s*\(\s*(\w+)\s*\)\s*\)\s*call\s+Error_Report', joined, re.I):
        info['forbids'].append(('neither', m.group(1), m.group(2)))
    for m in UNSUPPORTED_RE.finditer(joined):
        info['errors'].append(m.group(1).strip())
    if info['errors'] and len(cl) <= 8:
        info['stub'] = info['errors'][0]
    if re.search(r'=\s*[+-]?\s*huge\s*\(', joined, re.I):
        info['sentinel'] = True
    return info

# ---------------------------------------------------------------- consumers (call sites)
decl_re = re.compile(r'^\s*class\s*\(\s*(\w+)Class\s*\)[^:!]*::\s*(.+)$', re.I)
call_re = re.compile(r'(?<![\w%])(?:self\s*%\s*)?(\w+)\s*%\s*(\w+)\s*\(', re.I)

def split_args(s):
    out, depth, cur = [], 0, ''
    for ch in s:
        if ch in '([': depth += 1
        elif ch in ')]': depth -= 1
        if ch == ',' and depth == 0:
            out.append(cur); cur = ''
        else:
            cur += ch
    if cur.strip(): out.append(cur)
    return [a.strip() for a in out]

def extract_call_args(line, pos):
    depth, i = 0, pos
    while i < len(line):
        if line[i] == '(': depth += 1
        elif line[i] == ')':
            depth -= 1
            if depth == 0: return line[pos + 1:i]
        i += 1
    return line[pos + 1:]

calls = collections.defaultdict(list)   # (class, method) -> [(file, lineno, kwargs set, npositional, caller_impl)]
for f in files:
    lines = file_text[f]
    varclass = {}
    for d in directives_by_file[f]:
        if d.get('rootElementType') == 'objectBuilder' and d.get('class') in class_names and d.get('name'):
            varclass[d['name'].lower()] = d['class']
    for l in lines:
        m = decl_re.match(l.split('!')[0])
        if m and m.group(1) in class_names:
            for v in m.group(2).split(','):
                v = v.split('=>')[0].strip()
                if re.match(r'^\w+$', v): varclass[v.lower()] = m.group(1)
    # continuation-line joining for calls
    joined_lines = []
    buf, start = '', 0
    for i, l in enumerate(lines):
        code = l.split('!')[0] if not l.strip().startswith('!$') else ''
        if buf == '': start = i
        # Both continuation markers must be dropped. Leaving the leading `&` of a continued line in place
        # prefixes the first argument after the break, so that `field = field` reads as `& field = field`
        # and fails to parse as a keyword argument - hiding every keyword argument written after a break.
        piece = code.rstrip().rstrip('&')
        buf   = piece if buf == '' else buf + ' ' + piece.strip().lstrip('&')
        if code.rstrip().endswith('&'):
            continue
        joined_lines.append((start + 1, buf)); buf = ''
    proc_re    = re.compile(r'^\s{0,6}(?:recursive\s+)?(?:\S[^!]*?\s+)?(?:function|subroutine)\s+\w+\s*\(', re.I)
    optdecl_re = re.compile(r'^\s*[^!]*?,\s*optional\b[^:]*::\s*(.+)$', re.I)
    optionals_at, current = {}, set()
    for lineno, l in joined_lines:
        if proc_re.match(l): current = set()
        om = optdecl_re.match(l.split('!')[0])
        if om:
            for v in om.group(1).split(','):
                v = v.split('=')[0].strip()
                if re.match(r'^\w+$', v): current.add(v.lower())
        optionals_at[lineno] = set(current)
    for lineno, l in joined_lines:
        optionals = optionals_at.get(lineno, set())
        for cm in call_re.finditer(l):
            var, meth = cm.group(1).lower(), cm.group(2)
            if var not in varclass: continue
            cls = varclass[var]
            if meth not in classes[cls]['methods']: continue
            argstr = extract_call_args(l, cm.end() - 1)
            args = split_args(argstr)
            kw = set(); npos = 0; maybe = set()
            declared = classes[cls]['methods'][meth]['args']
            for a in args:
                km = re.match(r'^(\w+)\s*=(?!=)', a)
                if km:
                    kw.add(km.group(1))
                    if a.split('=', 1)[1].strip().lower() in optionals: maybe.add(km.group(1))
                else:
                    if a.strip().lower() in optionals and npos < len(declared): maybe.add(declared[npos][0])
                    npos += 1
            calls[(cls, meth)].append((os.path.relpath(f, SRC), lineno, kw, npos, maybe))

# ---------------------------------------------------------------- analysis
report = {'C1': [], 'C2': [], 'C3': [], 'C4': [], 'C5': []}
method_info = {}   # (class, method) -> {'base': info, 'impls': {impl: info}}
for cls, c in classes.items():
    for meth, md in c['methods'].items():
        base = analyze_body(md['code'].split('\n') if md.get('code') else None, md['args'])
        per = {}
        for iname, idata in c['implementations'].items():
            ov = idata['resolved'].get(meth)
            if ov:
                body = procedure_body(ov[1], ov[0])
                per[iname] = analyze_body(body, md['args'])
        method_info[(cls, meth)] = {'base': base, 'impls': per, 'args': md['args'], 'has_code': bool(md.get('code'))}

def arg_names_positional(args, npos):
    return set(a[0] for a in args[:npos])

# C1: optional-argument contracts
for (cls, meth), mi in method_info.items():
    args = mi['args']
    optional = [a for a, o in args if o]
    if not optional: continue
    sites = calls.get((cls, meth), [])
    base = mi['base']
    # implementations that require an optional argument (explicitly or implicitly)
    req_by_impl = collections.defaultdict(set)
    for iname, info in mi['impls'].items():
        for a in info['requires']:
            if a in optional: req_by_impl[a].add(iname + ('' if a in info.get('explicit', ()) else '*'))
    for a in base['requires']:
        if a in optional: req_by_impl[a].add('(base default)')
    for site in sites:
        f, ln, kw, npos, maybe = site
        provided = kw | arg_names_positional(args, npos)
        # base constraints
        for fb in base['forbids']:
            if fb[0] == 'neither':
                if fb[1] not in provided and fb[2] not in provided and not ({fb[1], fb[2]} & maybe):
                    report['C1'].append({'kind': 'call violates base contract', 'class': cls, 'method': meth, 'site': f'{f}:{ln}', 'detail': f'neither `{fb[1]}` nor `{fb[2]}` provided'})
            elif fb[0] in provided and fb[1] in provided and not ({fb[0], fb[1]} & maybe):
                report['C1'].append({'kind': 'call violates base contract', 'class': cls, 'method': meth, 'site': f'{f}:{ln}', 'detail': f'both `{fb[0]}` and `{fb[1]}` provided'})
        for a, who in req_by_impl.items():
            if a not in provided and a not in maybe:
                report['C1'].append({'kind': 'call omits argument required by some implementations', 'class': cls, 'method': meth, 'site': f'{f}:{ln}', 'detail': f'`{a}` omitted; required by ' + ', '.join(sorted(who)) + f' ({len(who)}/{len(mi["impls"]) or 1} implementations)'})
    # implementations that require args the base allows to be absent, and ignore args the base treats as meaningful
    for a, who in req_by_impl.items():
        if len(mi['impls']) > 1 and len(who) < len(mi['impls']):
            report['C1'].append({'kind': 'implementations diverge on optional argument', 'class': cls, 'method': meth, 'site': '', 'detail': f'`{a}` required by {", ".join(sorted(who))}; optional for the other {len(mi["impls"]) - len([w for w in who if w != "(base default)"])} implementations'})

# C2: capability stubs vs consumers
for (cls, meth), mi in method_info.items():
    stubs = {i: info['stub'] for i, info in mi['impls'].items() if info['stub']}
    base_stub = mi['base']['stub']
    n = len(classes[cls]['implementations'])
    inheriting = [i for i in classes[cls]['implementations'] if meth not in classes[cls]['implementations'][i]['resolved']]
    unsupported = dict(stubs)
    if base_stub:
        for i in inheriting: unsupported[i] = base_stub + ' (inherited)'
    if not unsupported: continue
    sites = calls.get((cls, meth), [])
    report['C2'].append({'class': cls, 'method': meth, 'unsupported': unsupported, 'count': n, 'sites': sorted(set(f'{s[0]}:{s[1]}' for s in sites))})

# C3: null-default hazards
for cls, c in classes.items():
    null_impl = next((i for i in c['implementations'] if i.lower() == (cls + 'Null').lower()), None)
    if not null_impl: continue
    default_null = (c['default'] or '').lower() == 'null'
    hazards = {}
    for meth in c['methods']:
        info = method_info[(cls, meth)]['impls'].get(null_impl)
        if info is None: continue
        if info['errors'] or info['sentinel']:
            hazards[meth] = 'errors: ' + info['errors'][0] if info['errors'] else 'returns huge() sentinel'
    if not hazards: continue
    for meth, why in hazards.items():
        sites = [s for s in calls.get((cls, meth), []) if not s[0].endswith('null.F90')]
        if sites:
            report['C3'].append({'class': cls, 'defaultNull': default_null, 'method': meth, 'null': why, 'sites': sorted(set(f'{s[0]}:{s[1]}' for s in sites))})

# C4: inherited base-class defaults
for (cls, meth), mi in method_info.items():
    if not mi['has_code'] or mi['base']['stub']: continue
    n = len(classes[cls]['implementations'])
    inheriting = [i for i in classes[cls]['implementations'] if meth not in classes[cls]['implementations'][i]['resolved']]
    overriding = n - len(inheriting)
    if n >= 2 and 0 < overriding < n:
        code = classes[cls]['methods'][meth]['code'] or ''
        report['C4'].append({'class': cls, 'method': meth, 'overriding': overriding, 'inheriting': len(inheriting), 'inheritors': inheriting[:12], 'baseSummary': ' '.join(code_lines(code.split('\n'))[:2])[:140]})

# C5: parameter-convention drift from the catalog
catalog_path = sys.argv[1] if len(sys.argv) > 1 else None
UNIT_RE = re.compile(r'\b(Mpc|kpc|pc|Gyr|Myr|yr|km/s|km\s*s|M_?☉|M⊙|solar mass|Solar mass|M_\\odot|Msun|K\b|erg|cm\^?-?3|h\^?-1|dex|radian|degree)', re.I)
if catalog_path:
    cat = json.load(open(catalog_path))
    byclass = collections.defaultdict(lambda: collections.defaultdict(list))
    for iname, rec in cat['implementations'].items():
        for p in rec['parameters']:
            if p.get('provenance') != 'default': continue
            byclass[rec['functionClass']][p['name']].append((iname, p.get('description') or '', p.get('type'), p.get('default')))
    for cls, params in byclass.items():
        # same name, different units in description
        for pname, uses in params.items():
            units = collections.defaultdict(set)
            for iname, desc, typ, default in uses:
                u = frozenset(x.lower() for x in UNIT_RE.findall(desc))
                if u: units[u].add(iname)
            if len(units) > 1:
                report['C5'].append({'kind': 'same parameter, different units in description', 'class': cls, 'parameter': pname, 'detail': '; '.join(f'{sorted(k)}: {sorted(v)[:3]}' for k, v in units.items())})
            types = collections.defaultdict(set)
            for iname, desc, typ, default in uses:
                types[typ].add(iname)
            if len(types) > 1:
                report['C5'].append({'kind': 'same parameter, different types', 'class': cls, 'parameter': pname, 'detail': '; '.join(f'{k}: {sorted(v)[:3]}' for k, v in types.items())})
        # near-duplicate names (same word multiset)
        norm = collections.defaultdict(set)
        for pname in params:
            words = tuple(sorted(w.lower() for w in re.findall(r'[A-Z]?[a-z0-9]+', pname)))
            norm[words].add(pname)
        for words, names in norm.items():
            if len(names) > 1:
                report['C5'].append({'kind': 'near-duplicate parameter names within a class', 'class': cls, 'parameter': '/'.join(sorted(names)), 'detail': '; '.join(f'{n}: {sorted(i for i, *_ in params[n])[:3]}' for n in sorted(names))})

# ---------------------------------------------------------------- output
summary = {'classes': len(classes), 'implementations': len(impls), 'methods': sum(len(c['methods']) for c in classes.values()), 'callSites': sum(len(v) for v in calls.values())}
json.dump({'summary': summary, 'report': report}, open('classContractSweep.json', 'w'), indent=1, default=list)
print(json.dumps(summary))
for k, v in report.items(): print(k, len(v))
