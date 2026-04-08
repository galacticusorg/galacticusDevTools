#!/usr/bin/env python3
import os
import shutil
import subprocess
from datetime import datetime, timezone
from lxml import etree

# Script used to automate migration of all parameter files.
# Andrew Benson (23-May-2025).

# Simply run the script from a Galacticus directory.

# Get a timestamp for the update.
time_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

# Migrate all files.
parameter_paths = ["parameters", "constraints", "testSuite"]
excluded_paths = {
    os.path.normpath(os.path.join("constraints", "parameters")),
    os.path.normpath(os.path.join("constraints", "dataAnalysis")),
    os.path.normpath(os.path.join("testSuite", "outputs")),
}

for base_path in parameter_paths:
    for dirpath, dirnames, filenames in os.walk(base_path):
        norm_dirpath = os.path.normpath(dirpath)
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if os.path.normpath(os.path.join(dirpath, dirname)) not in excluded_paths
        ]
        # Ignore certain paths.
        if any(
            norm_dirpath == excluded_path
            or norm_dirpath.startswith(excluded_path + os.sep)
            for excluded_path in excluded_paths
        ):
            continue
        for filename in filenames:
            if not filename.endswith(".xml"):
                continue
            filepath = os.path.join(dirpath, filename)
            # Parse XML and ignore any non-parameter files.
            try:
                tree = etree.parse(filepath)
            except etree.XMLSyntaxError:
                continue
            if not tree.xpath("//parameters"):
                continue
            # Migrate the parameter file.
            exec_path = os.environ.get("GALACTICUS_EXEC_PATH")
            if not exec_path:
                raise RuntimeError(
                    "GALACTICUS_EXEC_PATH is not set; set this environment variable "
                    "to the Galacticus executable directory before running "
                    "migrateAllParameterFiles.py."
                )
            tmp_file = os.path.join(exec_path, "migration__.xml.tmp")
            subprocess.run(
                [
                    "./scripts/aux/parametersMigrate.py",
                    filepath,
                    tmp_file,
                    "--ignoreWhiteSpaceChanges", "yes",
                    "--validate", "no",
                    "--timeStamp", time_stamp,
                ],
                cwd=exec_path,
                check=True,
            )
            shutil.move(tmp_file, filepath)

# Reset an outdated revision in test suite parameter files that explicitly probe this issue.
for filename in ("strictOutdated.xml", "unstrictOutdated.xml"):
    filepath = os.path.join("testSuite", "parameters", filename)
    subprocess.run(
        [
            "sed", "-i~", "-r",
            r's/lastModified\s+revision="[a-f0-9]+"/lastModified revision="262562000c251ee5b935019673f606a8a8c47c10"/',
            filepath,
        ],
        check=True,
    )
