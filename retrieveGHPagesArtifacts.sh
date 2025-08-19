#!/usr/bin/env bash

# Retrieves artifacts from a Galacticus CI/CD run that would be pushed to GitHub pages, and moves them into the correct
# directories. This is useful to allow these to be explored before a PR is merged and deployed. This script should be run from a
# directory with the gh-pages branch of the repo checked out.
# Andrew Benson (19-August-2025)

# If no argument is provided, show a list of recent IDs.
if [[ $# -eq 0 || $# -gt 1 ]]; then
    echo "Usage: ./retrieveGHPagesArtifacts.sh <runID>"
    echo
    echo "Recent runs are:"
    gh run list --repo galacticusorg/galacticus --workflow "CI/CD"
    exit
fi
runID = $1

# Download artifacts.
mkdir -p artifacts
gh run download ${runID} --repo galacticusorg/galacticus --pattern "benchmark-*" --dir artifacts
gh run download ${runID} --repo galacticusorg/galacticus --pattern "validate-*" --dir artifacts

# Relocate files.
## DMO benchmarks.
head -n -3 dev/bench/darkMatterOnlySubhalos/data.js > tmp.js
cat <<EOF >> tmp.js
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
sed '1d;$d' artifacts/validate-darkMatterOnlySubhalos/validate_darkMatterOnlySubhalos.json >> tmp.js
echo "," >> tmp.js
sed '1d;$d' artifacts/benchmark-darkMatterOnlySubhalos/benchmark_darkMatterOnlySubhalos.json >> tmp.js
cat <<EOF >> tmp.js
        ]
      }
    ]
  }
}
EOF
mv tmp.js dev/bench/darkMatterOnlySubhalos/data.js

## MW benchmarks.
head -n -3 dev/bench/milkyWayModel/data.js > tmp.js
cat <<EOF >> tmp.js
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
sed '1d;$d' artifacts/validate-milkyWayModel/validate_milkyWayModel.json >> tmp.js
echo "," >> tmp.js
sed '1d;$d' artifacts/benchmark-milkyWayModel/benchmark_milkyWayModel.json >> tmp.js
cat <<EOF >> tmp.js
        ]
      }
    ]
  }
}
EOF
mv tmp.js dev/bench/milkyWayModel/data.js

## Validation plots.
cp artifacts/validate-darkMatterOnlySubhalos/results_darkMatterOnlySubhalos.json                                           dev/valid/darkMatterOnlySubhalos/results.json
cp artifacts/validate-milkyWayModel/results_milkyWayModel.json                                                             dev/valid/milkyWayModel/results.json
cp artifacts/validate-darkMatterOnlySubhalosSymphonyMilkyWay/results_darkMatterOnlySubhalosSymphonyMilkyWay.json           dev/valid/darkMatterOnlySubhalosSymphonyMilkyWay/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM3keVMilkyWay/results_darkMatterOnlySubhalosCOZMICWDM3keVMilkyWay.json dev/valid/darkMatterOnlySubhalosCOZMICWDM3keVMilkyWay/results.json

## NOTE: There are many other validation and benchmark datasets that could be included here. Add them as needed.

# Open the web pages.
xdg-open dev/bench/darkMatterOnlySubhalos/index.html
xdg-open dev/bench/milkyWayModel/index.html
xdg-open dev/valid/darkMatterOnlySubhalos/index.html
xdg-open dev/valid/milkyWayModel/index.html
xdg-open dev/valid/darkMatterOnlySubhalosSymphonyMilkyWay/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM3keVMilkyWay/index.html

exit
