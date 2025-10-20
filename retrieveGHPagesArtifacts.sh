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
runID=$1

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

## DMO Symphony benchmarks.
for resolution in X1 X8 X64
do
    head -n -3 dev/bench/darkMatterOnlySubhalosSymphonyCDMMilkyWay${resolution}/data.js > tmp.js
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
    sed '1d;$d' artifacts/validate-darkMatterOnlySubhalosSymphonyCDMMilkyWay${resolution}/validate_darkMatterOnlySubhalosSymphonyCDMMilkyWay${resolution}.json >> tmp.js
    cat <<EOF >> tmp.js
        ]
      }
    ]
  }
}
EOF
    mv tmp.js dev/bench/darkMatterOnlySubhalosSymphonyCDMMilkyWay${resolution}/data.js
done

## DMO COZMIC WDM benchmarks.
for mass in 3keV 4keV 5keV 6keV 6.5keV 10keV
do
    for resolution in X1 X8
    do
	head -n -3 dev/bench/darkMatterOnlySubhalosCOZMICWDM${mass}MilkyWay${resolution}/data.js > tmp.js
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
	sed '1d;$d' artifacts/validate-darkMatterOnlySubhalosCOZMICWDM${mass}MilkyWay${resolution}/validate_darkMatterOnlySubhalosCOZMICWDM${mass}MilkyWay${resolution}.json >> tmp.js
	cat <<EOF >> tmp.js
        ]
      }
    ]
  }
}
EOF
	mv tmp.js dev/bench/darkMatterOnlySubhalosCOZMICWDM${mass}MilkyWay${resolution}/data.js
    done
done

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
cp artifacts/validate-darkMatterOnlySubhalos/results_darkMatterOnlySubhalos.json                                                   dev/valid/darkMatterOnlySubhalos/results.json
cp artifacts/validate-milkyWayModel/results_milkyWayModel.json                                                                     dev/valid/milkyWayModel/results.json
cp artifacts/validate-darkMatterOnlySubhalosSymphonyCDMMilkyWayX1/results_darkMatterOnlySubhalosSymphonyCDMMilkyWayX1.json         dev/valid/darkMatterOnlySubhalosSymphonyCDMMilkyWayX1/results.json
cp artifacts/validate-darkMatterOnlySubhalosSymphonyCDMMilkyWayX8/results_darkMatterOnlySubhalosSymphonyCDMMilkyWayX8.json         dev/valid/darkMatterOnlySubhalosSymphonyCDMMilkyWayX8/results.json
cp artifacts/validate-darkMatterOnlySubhalosSymphonyCDMMilkyWayX64/results_darkMatterOnlySubhalosSymphonyCDMMilkyWayX64.json       dev/valid/darkMatterOnlySubhalosSymphonyCDMMilkyWayX64/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX1/results_darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX1.json     dev/valid/darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX1/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX1/results_darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX1.json     dev/valid/darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX1/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX1/results_darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX1.json     dev/valid/darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX1/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX1/results_darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX1.json     dev/valid/darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX1/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX1/results_darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX1.json dev/valid/darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX1/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX1/results_darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX1.json   dev/valid/darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX1/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX8/results_darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX8.json     dev/valid/darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX8/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX8/results_darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX8.json     dev/valid/darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX8/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX8/results_darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX8.json     dev/valid/darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX8/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX8/results_darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX8.json     dev/valid/darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX8/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX8/results_darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX8.json dev/valid/darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX8/results.json
cp artifacts/validate-darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX8/results_darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX8.json   dev/valid/darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX8/results.json

## NOTE: There are many other validation and benchmark datasets that could be included here. Add them as needed.

# Open the web pages.
xdg-open dev/bench/darkMatterOnlySubhalos/index.html
xdg-open dev/bench/milkyWayModel/index.html
xdg-open dev/bench/darkMatterOnlySubhalosSymphonyCDMMilkyWayX1/index.html
xdg-open dev/bench/darkMatterOnlySubhalosSymphonyCDMMilkyWayX8/index.html
xdg-open dev/bench/darkMatterOnlySubhalosSymphonyCDMMilkyWayX64/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX1/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX1/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX1/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX1/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX1/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX1/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX8/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX8/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX8/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX8/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX8/index.html
xdg-open dev/bench/darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX8/index.html
xdg-open dev/valid/darkMatterOnlySubhalos/index.html
xdg-open dev/valid/milkyWayModel/index.html
xdg-open dev/valid/darkMatterOnlySubhalosSymphonyCDMMilkyWayX1/index.html
xdg-open dev/valid/darkMatterOnlySubhalosSymphonyCDMMilkyWayX8/index.html
xdg-open dev/valid/darkMatterOnlySubhalosSymphonyCDMMilkyWayX64/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX1/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX1/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX1/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX1/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX1/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX1/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM3keVMilkyWayX8/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM4keVMilkyWayX8/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM5keVMilkyWayX8/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM6keVMilkyWayX8/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM6.5keVMilkyWayX8/index.html
xdg-open dev/valid/darkMatterOnlySubhalosCOZMICWDM10keVMilkyWayX8/index.html

exit
