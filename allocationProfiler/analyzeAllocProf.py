#!/usr/bin/env python3

# Symbolise and summarise an allocation profile written by `liballocProf.so` (see `allocProf.c`).
# Andrew Benson (03-June-2026).

# Reads the per-call-stack allocation profile, symbolises the stacks with addr2line (inlining-aware),
# and reports the total allocation count and bytes, the busiest allocation call sites, and -- if a
# target regular expression is supplied -- the INCLUSIVE share of allocations whose stack passes
# through any frame matching that expression. The latter is how you attribute allocation churn to a
# particular routine or subsystem (e.g. a specific object's construct/destroy lifecycle).
#
# Usage:
#   ./analyzeAllocProf.py <executable> <profileFile> [targetRegex]
#
# <executable>   the program that produced the profile (used for symbolisation; must match the run).
# <profileFile>  the profile written by liballocProf.so (ALLOCPROF_OUT, default "allocProf.out").
# [targetRegex]  optional case-insensitive regex; allocations whose stack passes through a matching
#                (demangled) frame are summed and reported as a fraction of the total.

import re, subprocess, sys
from collections import defaultdict

def main():
    if len(sys.argv) < 3:
        sys.exit("usage: analyzeAllocProf.py <executable> <profileFile> [targetRegex]")
    exe, out = sys.argv[1], sys.argv[2]
    target = re.compile(sys.argv[3], re.I) if len(sys.argv) > 3 else None

    exe_lo = exe_hi = None
    sample = 1
    stacks = []          # (count, bytes, [pc,...])
    tot_c = tot_b = 0
    with open(out) as f:
        for line in f:
            if line.startswith("#exe"):
                _, _path, lo, hi = line.rstrip("\n").split("\t")
                exe_lo, exe_hi = int(lo, 16), int(hi, 16)
            elif line.startswith("#sample"):
                sample = int(line.rstrip("\n").split("\t")[1])
            elif line.startswith("#total"):
                _, tc, tb, _s = line.rstrip("\n").split("\t")
                tot_c, tot_b = int(tc), int(tb)
            elif not line.startswith("#"):
                p = line.rstrip("\n").split("\t")
                cnt, byts = int(p[0]), int(p[1])
                pcs = [int(x, 16) for x in p[2:]]
                stacks.append((cnt, byts, pcs))
    if exe_lo is None:
        sys.exit("no #exe header in %s" % out)

    # Collect unique static offsets for executable-range PCs and batch-symbolise.
    offs = set()
    for _c, _b, pcs in stacks:
        for pc in pcs:
            if exe_lo <= pc < exe_hi:
                offs.add(pc - exe_lo)
    offs = sorted(offs)
    sym = {}             # static_off -> [func, func(inlined parent), ...]
    if offs:
        addrs = "\n".join("0x%x" % o for o in offs).encode()
        r = subprocess.run(["addr2line", "-a", "-f", "-C", "-i", "-e", exe],
                           input=addrs, capture_output=True)
        cur = None
        for ln in r.stdout.decode(errors="replace").splitlines():
            if ln.startswith("0x"):
                cur = int(ln, 16); sym[cur] = []
            elif cur is not None:
                # addr2line -afi alternates function-name and file:line lines per address;
                # keep the function names, drop the file:line lines and unresolved markers.
                if not re.match(r"^(/|\.\.?/|\?\?:)", ln) and ln not in ("??",):
                    sym[cur].append(ln)

    def funcs_in(pcs):
        names = []
        for pc in pcs:
            if exe_lo <= pc < exe_hi:
                names.extend(sym.get(pc - exe_lo, []))
        return names

    incl_c = incl_b = 0
    leaf_counts = defaultdict(int)          # innermost executable frame -> allocations
    target_funcs = defaultdict(int)
    for cnt, byts, pcs in stacks:
        names = funcs_in(pcs)
        if target and any(target.search(n) for n in names):
            incl_c += cnt; incl_b += byts
            for n in names:
                if target.search(n):
                    target_funcs[n] += cnt
        if names:
            leaf_counts[names[0]] += cnt

    pct = lambda a, b: (100.0 * a / b) if b else 0.0
    est = "  (est.)" if sample > 1 else ""
    print("allocation profile: %s" % out)
    if sample > 1:
        nsamp = sum(c for c, _b, _p in stacks) // sample
        print("  sampling rate     : 1-in-%d  (~%d raw samples; counts are scaled estimates,"
              " ratios are unbiased)" % (sample, nsamp))
    print("  total allocations : %15d%s" % (tot_c, est))
    print("  total bytes       : %15d  (%.1f GB)%s" % (tot_b, tot_b / 1e9, est))
    if target:
        print()
        print("target (INCLUSIVE — any stack passing through a frame matching the regex):")
        print("  allocations       : %15d   = %6.2f%% of all allocations" % (incl_c, pct(incl_c, tot_c)))
        print("  bytes             : %15d   = %6.2f%% of all bytes" % (incl_b, pct(incl_b, tot_b)))
        print()
        print("  breakdown by matching frame (inclusive allocations through each):")
        for n, c in sorted(target_funcs.items(), key=lambda x: -x[1])[:12]:
            print("    %15d  %6.2f%%  %s" % (c, pct(c, tot_c), n))
    print()
    print("top allocation call sites (by innermost executable frame), for context:")
    for n, c in sorted(leaf_counts.items(), key=lambda x: -x[1])[:15]:
        print("    %15d  %6.2f%%  %s" % (c, pct(c, tot_c), n))

if __name__ == "__main__":
    main()
