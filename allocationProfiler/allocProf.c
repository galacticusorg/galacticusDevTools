/*
 * allocProf.c — a tiny LD_PRELOAD allocation profiler that aggregates allocations
 * by call-stack, so that memory use stays BOUNDED (one entry per unique backtrace)
 * no matter how many allocations the program makes.
 *
 * This is the key difference from tools such as heaptrack, which record every
 * individual allocation and so exhaust RAM on allocation-heavy codes (a single
 * Galacticus model can make billions of allocations). Because allocProf only keeps
 * aggregated per-stack counts, it can profile a full run to completion. It also
 * counts CUMULATIVE allocations — every malloc/calloc/realloc, including ones that
 * are later freed (i.e. temporaries) — which a live-heap profiler (e.g. jemalloc's)
 * cannot see.
 *
 * Build:
 *   gcc -O2 -fPIC -shared -o liballocProf.so allocProf.c -ldl -lpthread
 * Run:
 *   ALLOCPROF_OUT=alloc.out LD_PRELOAD=./liballocProf.so ./yourProgram args...
 * Analyse:
 *   ./analyzeAllocProf.py ./yourProgram alloc.out ['regex']
 *
 * Environment:
 *   ALLOCPROF_OUT     output file (default "allocProf.out")
 *   ALLOCPROF_DEPTH   max backtrace frames captured per allocation (default 32, max MAXD)
 *   ALLOCPROF_SAMPLE  record 1-in-N allocations (default 1 = all). N>1 unwinds the
 *                     stack only ~1/N of the time, for a large speed-up; recorded
 *                     counts are scaled by N so totals remain estimates of the true
 *                     totals, and any attribution RATIO is statistically unbiased.
 *
 * Notes:
 *  - Uses backtrace() (the libgcc .eh_frame unwinder), which is reliable even under
 *    -O3 without frame pointers. The cost is CPU (a stack unwind per recorded
 *    allocation), NOT memory — so prefer sampling and/or a single thread for speed.
 *  - Raw run-time PCs are written; the analyser converts main-executable PCs to
 *    static offsets (the executable's mapping base/end are written in a header line)
 *    so that addr2line can symbolise them, robustly with ASLR/PIE.
 *
 * Andrew Benson (03-June-2026).
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <execinfo.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>

#define MAXD     64
#define TABBITS  20            /* 2^20 = 1,048,576 slots */
#define TABSIZE  (1u << TABBITS)
#define TABMASK  (TABSIZE - 1u)

typedef struct {
    uint64_t hash;
    uint64_t count;
    uint64_t bytes;
    int      depth;
    void    *pc[MAXD];
} entry_t;

static entry_t *table;                 /* mmap-backed, zero-initialised */
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static __thread int in_hook = 0;       /* recursion guard (backtrace/dlsym alloc) */
static int   cfg_depth  = 32;
static int   cfg_sample = 1;           /* record 1-in-N allocations (1 = all) */
static int   ready = 0;

/* Per-thread xorshift32 PRNG for sampling decisions — cheap, lock-free, and
 * decorrelated across threads (seeded from the TLS address) so a fixed stride
 * cannot systematically over/under-sample bursty call sites. */
static __thread uint32_t rng_state = 0;
static inline uint32_t rng_next(void){
    uint32_t x = rng_state;
    if (x == 0) x = 0x9e3779b9u ^ (uint32_t)(uintptr_t)&rng_state;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    rng_state = x;
    return x;
}

static void *(*real_malloc)(size_t)         = NULL;
static void *(*real_calloc)(size_t, size_t) = NULL;
static void *(*real_realloc)(void *, size_t)= NULL;
static void  (*real_free)(void *)           = NULL;

/* Tiny static arena so dlsym()'s own early allocations don't recurse/segfault. */
static char  boot_arena[1 << 16];
static size_t boot_off = 0;
static void *boot_alloc(size_t n){
    n = (n + 15u) & ~((size_t)15u);
    if (boot_off + n > sizeof(boot_arena)) { _exit(77); }
    void *p = boot_arena + boot_off; boot_off += n; return p;
}
static int is_boot(void *p){ return (char*)p >= boot_arena && (char*)p < boot_arena + sizeof(boot_arena); }

static void init_real(void){
    real_malloc  = (void*(*)(size_t))         dlsym(RTLD_NEXT, "malloc");
    real_calloc  = (void*(*)(size_t,size_t))  dlsym(RTLD_NEXT, "calloc");
    real_realloc = (void*(*)(void*,size_t))   dlsym(RTLD_NEXT, "realloc");
    real_free    = (void(*)(void*))           dlsym(RTLD_NEXT, "free");
}

__attribute__((constructor))
static void allocprof_init(void){
    const char *d = getenv("ALLOCPROF_DEPTH");
    if (d) { int v = atoi(d); if (v > 0 && v <= MAXD) cfg_depth = v; }
    const char *s = getenv("ALLOCPROF_SAMPLE");
    if (s) { int v = atoi(s); if (v > 0) cfg_sample = v; }
    /* anonymous private mapping, pre-zeroed, never freed */
    extern void *mmap(void*, size_t, int, int, int, off_t);
    table = mmap(NULL, (size_t)TABSIZE * sizeof(entry_t),
                 0x1|0x2 /*READ|WRITE*/, 0x20|0x02 /*ANON|PRIVATE*/, -1, 0);
    if (table == (void*)-1) { table = NULL; }
    if (!real_malloc) init_real();
    ready = 1;
}

static void record(size_t n){
    /* Sampling gate — decide BEFORE the expensive unwind. Each recorded sample
     * stands in for cfg_sample allocations, so counts/bytes are scaled to remain
     * estimates of the true totals; any target/total RATIO is unbiased either way. */
    uint64_t weight = 1;
    if (cfg_sample > 1) {
        if ((rng_next() % (uint32_t)cfg_sample) != 0u) return;
        weight = (uint64_t)cfg_sample;
    }
    void *bt[MAXD];
    int depth = backtrace(bt, cfg_depth);
    if (depth <= 1) return;
    /* drop frame 0 (this lib's hook) */
    int s = 1, d = depth - 1;
    uint64_t h = 1469598103934665603ULL;            /* FNV-1a */
    for (int i = 0; i < d; i++){
        uintptr_t v = (uintptr_t)bt[s+i];
        h ^= v; h *= 1099511628211ULL;
    }
    if (!table) return;
    pthread_mutex_lock(&lock);
    uint32_t idx = (uint32_t)(h & TABMASK);
    for (uint32_t probe = 0; probe < TABSIZE; probe++){
        entry_t *e = &table[idx];
        if (e->count == 0 && e->hash == 0){          /* empty slot -> new stack */
            e->hash = h; e->depth = d;
            for (int i = 0; i < d; i++) e->pc[i] = bt[s+i];
            e->count = weight; e->bytes = (uint64_t)n * weight;
            break;
        }
        if (e->hash == h && e->depth == d){           /* same stack -> accumulate */
            e->count += weight; e->bytes += (uint64_t)n * weight;
            break;
        }
        idx = (idx + 1u) & TABMASK;                   /* linear probe */
    }
    pthread_mutex_unlock(&lock);
}

void *malloc(size_t n){
    if (!real_malloc){ init_real(); if (!real_malloc) return boot_alloc(n); }
    if (in_hook || !ready) return real_malloc(n);
    in_hook = 1; void *p = real_malloc(n); if (p) record(n); in_hook = 0; return p;
}
void *calloc(size_t a, size_t b){
    if (!real_calloc){ init_real(); if (!real_calloc){ void*p=boot_alloc(a*b); if(p) memset(p,0,a*b); return p; } }
    if (in_hook || !ready) return real_calloc(a,b);
    in_hook = 1; void *p = real_calloc(a,b); if (p) record(a*b); in_hook = 0; return p;
}
void *realloc(void *q, size_t n){
    if (!real_realloc){ init_real(); }
    if (in_hook || !ready) return real_realloc(q,n);
    in_hook = 1; void *p = real_realloc(q,n); if (p) record(n); in_hook = 0; return p;
}
void free(void *p){
    if (is_boot(p)) return;
    if (!real_free){ init_real(); if(!real_free) return; }
    real_free(p);
}

/* Find the main executable's mapping range so the analyser can turn PCs into
 * static offsets for addr2line. */
static void write_exe_header(FILE *f){
    char path[4096]; ssize_t n = readlink("/proc/self/exe", path, sizeof(path)-1);
    if (n <= 0) return; path[n] = 0;
    FILE *m = fopen("/proc/self/maps", "r");
    if (!m) return;
    char line[8192]; unsigned long lo = 0, hi = 0; int found = 0;
    while (fgets(line, sizeof(line), m)){
        unsigned long a, b; char perms[8]; char p2[4096];
        if (sscanf(line, "%lx-%lx %7s %*x %*x:%*x %*u %4095s", &a, &b, perms, p2) >= 4){
            if (strcmp(p2, path) == 0){
                if (!found){ lo = a; found = 1; }
                hi = b;
            }
        }
    }
    fclose(m);
    fprintf(f, "#exe\t%s\t%lx\t%lx\n", path, lo, hi);
}

__attribute__((destructor))
static void allocprof_fini(void){
    ready = 0;
    const char *out = getenv("ALLOCPROF_OUT"); if (!out) out = "allocProf.out";
    FILE *f = fopen(out, "w"); if (!f) return;
    write_exe_header(f);
    fprintf(f, "#sample\t%d\n", cfg_sample);
    uint64_t tot_c = 0, tot_b = 0, stacks = 0;
    for (uint32_t i = 0; i < TABSIZE; i++){
        entry_t *e = &table[i];
        if (e->count == 0) continue;
        stacks++; tot_c += e->count; tot_b += e->bytes;
        fprintf(f, "%llu\t%llu", (unsigned long long)e->count, (unsigned long long)e->bytes);
        for (int j = 0; j < e->depth; j++) fprintf(f, "\t%p", e->pc[j]);
        fputc('\n', f);
    }
    fprintf(f, "#total\t%llu\t%llu\t%llu\n",
            (unsigned long long)tot_c, (unsigned long long)tot_b,
            (unsigned long long)stacks);
    fclose(f);
}
