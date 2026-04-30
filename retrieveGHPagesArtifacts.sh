#!/usr/bin/env bash

# Retrieves artifacts from a Galacticus CI/CD run that would be pushed to GitHub pages, and moves them into the correct
# directories. This is useful to allow these to be explored before a PR is merged and deployed. This script should be run from a
# directory with the gh-pages branch of the repo checked out.
#
# The set of metrics to update is read from `scripts/build/ghPagesMetricsManifest.yml` -- the same manifest used by the CI
# regenerator -- so adding a new metric requires no change here. If the environment variable GALACTICUS_EXEC_PATH points to a
# checkout of the master branch of galacticus, the manifest, threshold sidecar, and `buildGhPagesIndex.py` indexer are taken from
# there and the indexer is run automatically so the dashboard, group pages, and per-metric `_data` reflect the local artifact
# data. Otherwise the manifest is fetched from upstream master, the indexer is skipped, and a prompt is printed telling the user
# how to regenerate the index manually.
#
# Andrew Benson (19-August-2025)

# If no argument is provided, show a list of recent IDs.
if [[ $# -eq 0 || $# -gt 1 ]]; then
    echo "Usage: ./retrieveGHPagesArtifacts.sh <runID>"
    echo
    echo "Recent runs are:"
    gh run list --repo galacticusorg/galacticus --workflow "CI/CD"
    exit
fi
runID=$1

# Locate the metrics manifest, threshold sidecar, and indexer script. Prefer a local Galacticus master checkout if the user has
# pointed GALACTICUS_EXEC_PATH at one; otherwise fetch the manifest from upstream master (the indexer needs a real master checkout
# and is skipped if we have to fall back).
manifest=""
manifestIsTemp=0
thresholds=""
indexer=""
if [[ -n "${GALACTICUS_EXEC_PATH}" && -d "${GALACTICUS_EXEC_PATH}" ]]; then
    if [[ -f "${GALACTICUS_EXEC_PATH}/scripts/build/ghPagesMetricsManifest.yml" ]]; then
        manifest="${GALACTICUS_EXEC_PATH}/scripts/build/ghPagesMetricsManifest.yml"
    fi
    if [[ -f "${GALACTICUS_EXEC_PATH}/scripts/build/ghPagesAnalysisThresholds.yml" ]]; then
        thresholds="${GALACTICUS_EXEC_PATH}/scripts/build/ghPagesAnalysisThresholds.yml"
    fi
    if [[ -f "${GALACTICUS_EXEC_PATH}/scripts/build/buildGhPagesIndex.py" ]]; then
        indexer="${GALACTICUS_EXEC_PATH}/scripts/build/buildGhPagesIndex.py"
    fi
fi
if [[ -z "${manifest}" ]]; then
    manifest=$(mktemp --suffix=.yml)
    manifestIsTemp=1
    if ! curl -sSfL https://raw.githubusercontent.com/galacticusorg/galacticus/master/scripts/build/ghPagesMetricsManifest.yml -o "${manifest}"; then
        echo "ERROR: GALACTICUS_EXEC_PATH is not set (or does not contain scripts/build/ghPagesMetricsManifest.yml)"
        echo "       and the manifest could not be fetched from upstream master."
        exit 1
    fi
fi

# Download artifacts. The validation, benchmark, and build-profile artifacts collectively cover every metric the manifest can
# update. Missing artifacts are tolerated (the per-metric loop below skips entries with no data).
mkdir -p artifacts
gh run download ${runID} --repo galacticusorg/galacticus --pattern "benchmark-*"  --dir artifacts || true
gh run download ${runID} --repo galacticusorg/galacticus --pattern "validate-*"   --dir artifacts || true
gh run download ${runID} --repo galacticusorg/galacticus --name    "build-profile" --dir artifacts/build-profile || true

# Locate a file by basename anywhere under `artifacts/`. Returns the first match, empty string if none.
findArtifact() {
    find artifacts -type f -name "$1" -print -quit 2>/dev/null
}

# Emit the synthetic "local" commit prologue/epilogue for the github-action-benchmark `data.js` schema. The `head -n -3` upstream
# strips the three closing lines that close the entries array, entries object, and root object; the epilogue closes the new
# commit's benches array plus those same three structural levels.
synthCommitPrologue() {
    cat <<EOF
      ,{
        "commit": {
          "author": {
            "email": "abensonca@gmail.com",
            "name": "Andrew Benson",
            "username": "abensonca"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "dummy",
          "message": "local",
          "timestamp": "???",
          "tree_id": "???",
          "url": "https://github.com/galacticusorg/galacticus/actions/runs/${runID}"
        },
        "date": 0,
        "tool": "customSmallerIsBetter",
        "benches": [
EOF
}
synthCommitEpilogue() {
    cat <<EOF
        ]
      }
    ]
  }
}
EOF
}

# Walk every metric in the manifest. The Python helper emits one tab-separated line per metric; the bash loop then dispatches to
# the bench/valid handlers. We use process substitution so the loop runs in the parent shell and `opens` accumulates correctly.
opens=()
processed=0
while IFS=$'\t' read -r suffix hasBench hasValid validFile; do
    [[ -z "${suffix}" ]] && continue
    processed=$((processed+1))

    # Bench: prepend a synthetic commit to dev/bench/<suffix>/data.js carrying the validate JSON (always present when the metric
    # has a bench tab) and the benchmark JSON (only the standalone perf-timing metrics ship one).
    if [[ "${hasBench}" == "1" ]]; then
        validateJson=$(findArtifact "validate_${suffix}.json")
        benchmarkJson=$(findArtifact "benchmark_${suffix}.json")
        dataJs="dev/bench/${suffix}/data.js"
        if [[ -f "${dataJs}" && ( -n "${validateJson}" || -n "${benchmarkJson}" ) ]]; then
            head -n -3 "${dataJs}" > tmp.js
            synthCommitPrologue >> tmp.js
            if [[ -n "${validateJson}" ]]; then
                sed '1d;$d' "${validateJson}" >> tmp.js
            fi
            if [[ -n "${benchmarkJson}" ]]; then
                [[ -n "${validateJson}" ]] && echo "," >> tmp.js
                sed '1d;$d' "${benchmarkJson}" >> tmp.js
            fi
            synthCommitEpilogue >> tmp.js
            mv tmp.js "${dataJs}"
            echo "bench: updated ${dataJs}"
            opens+=("dev/bench/${suffix}/index.html")
        else
            echo "bench: skipped ${suffix} (no artifact data or no existing data.js)"
        fi
    fi

    # Valid: copy the results JSON into place. For metrics whose manifest entry specifies a custom `valid_results_file` (PonosV,
    # baryonicSuppression) the artifact ships that exact filename; otherwise the source is `results_<suffix>.json` and the
    # destination is the conventional `results.json`.
    if [[ "${hasValid}" == "1" ]]; then
        if [[ "${validFile}" != "results.json" ]]; then
            srcName="${validFile}"
        else
            srcName="results_${suffix}.json"
        fi
        srcFile=$(findArtifact "${srcName}")
        destDir="dev/valid/${suffix}"
        if [[ -n "${srcFile}" && -d "${destDir}" ]]; then
            cp "${srcFile}" "${destDir}/${validFile}"
            echo "valid: updated ${destDir}/${validFile}"
            opens+=("dev/valid/${suffix}/index.html")
        else
            echo "valid: skipped ${suffix} (no artifact data or destination missing)"
        fi
    fi
done < <(python3 - "${manifest}" <<'PY'
import sys, yaml
with open(sys.argv[1]) as f:
    manifest = yaml.safe_load(f)
for suffix, entry in manifest.get('metrics', {}).items():
    # Bespoke entries with a `direct_path` (currently only buildProfile) are handled separately below.
    if entry.get('direct_path'):
        continue
    has_bench = '1' if entry.get('has_bench') else '0'
    has_valid = '1' if entry.get('has_valid') else '0'
    valid_file = entry.get('valid_results_file', 'results.json')
    print(f"{suffix}\t{has_bench}\t{has_valid}\t{valid_file}")
PY
)

# Build profile (manifest entry has only direct_path).
buildProfile=$(findArtifact "buildProfile.html")
if [[ -n "${buildProfile}" ]]; then
    mkdir -p dev/bench/meta
    cp "${buildProfile}" dev/bench/meta/buildProfile.html
    echo "meta:  updated dev/bench/meta/buildProfile.html"
fi

echo "Processed ${processed} manifest entries; touched ${#opens[@]} per-metric pages."

# Regenerate the gh-pages landing pages (index, dashboard, group pages, _data/metrics.yml) so they reflect the local artifact
# data instead of master. The indexer lives on master, not on gh-pages, so we need a Galacticus master checkout to find it.
if [[ -n "${indexer}" ]]; then
    indexerArgs=(--manifest "${manifest}")
    [[ -n "${thresholds}" ]] && indexerArgs+=(--thresholds "${thresholds}")
    indexerArgs+=(.)
    echo "Regenerating gh-pages index via ${indexer}"
    python3 "${indexer}" "${indexerArgs[@]}"
else
    cat <<MSG

NOTE: skipping gh-pages index regeneration -- GALACTICUS_EXEC_PATH is not set, or
      does not point at a checkout of Galacticus master containing
      scripts/build/buildGhPagesIndex.py. The dashboard, group pages, and per-metric
      timestamps will continue to reflect master until you run, from this directory:

          python3 \${GALACTICUS_EXEC_PATH}/scripts/build/buildGhPagesIndex.py \\
              --manifest   \${GALACTICUS_EXEC_PATH}/scripts/build/ghPagesMetricsManifest.yml \\
              --thresholds \${GALACTICUS_EXEC_PATH}/scripts/build/ghPagesAnalysisThresholds.yml \\
              .

MSG
fi

# Open every per-metric page that we touched. (The dashboard and group pages live at the gh-pages root and are reachable via
# Jekyll only, so we keep opening the per-metric `index.html` files directly via file:// like the previous version of this
# script.)
for page in "${opens[@]}"; do
    [[ -f "${page}" ]] && xdg-open "${page}"
done

# Tidy up the temporary manifest copy if we fetched it from upstream.
if [[ "${manifestIsTemp}" == "1" ]]; then
    rm -f "${manifest}"
fi

exit
