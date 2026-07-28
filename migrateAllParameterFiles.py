#!/usr/bin/env python3
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from lxml import etree

# Script used to automate migration of all parameter files.
# Andrew Benson (23-May-2025).

# Simply run the script from a Galacticus directory.

# Get a timestamp for the update.
time_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

# Cache of revisions already looked up in the git history.
known_revisions = {}


def revision_exists(revision, repo_path):
    """Determine if the given revision is a commit present in the git history of the repository."""
    if revision not in known_revisions:
        result = subprocess.run(
            ["git", "cat-file", "-e", revision + "^{commit}"],
            cwd=repo_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        known_revisions[revision] = result.returncode == 0
    return known_revisions[revision]


def check_revisions(tree, filepath, repo_path):
    """Report and exit if any `lastModified` revision in the file is absent from the git history."""
    for element in tree.xpath("//lastModified[@revision]"):
        revision = element.get("revision")
        if revision_exists(revision, repo_path):
            continue
        sys.exit(
            f'ERROR: parameter file "{filepath}" records a last modified revision, '
            f'"{revision}", which is not present in the git history of the repository at '
            f'"{repo_path}".\n'
            "       Migration can not determine which migrations to apply without this "
            "revision. Possible causes are:\n"
            "         * the repository is a shallow clone (try `git fetch --unshallow`);\n"
            "         * the revision exists only in a branch or fork which has not been "
            "fetched (try `git fetch --all`);\n"
            "         * the revision was removed from the history by a rebase or force-push, "
            "or is simply invalid.\n"
            "       If the revision is genuinely unavailable, edit the `lastModified` element "
            "in the parameter file to reference a valid ancestor commit."
        )

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
                parser = etree.XMLParser(resolve_entities=False, no_network=True)
                tree = etree.parse(filepath, parser)
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
            # Ensure that any revision recorded in the file is known to git, so that migration can
            # determine the ancestry of the file.
            check_revisions(tree, filepath, exec_path)
            tmp_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, dir=Path(filepath).parent)
            try:
                subprocess.run(
                    [
                        "./scripts/aux/parametersMigrate.py",
                        filepath,
                        tmp_file.name,
                        "--ignoreWhiteSpaceChanges", "yes",
                        "--validate", "no",
                        "--timeStamp", time_stamp,
                    ],
                    cwd=exec_path,
                    check=True,
                )
            except subprocess.CalledProcessError as e:
                os.unlink(tmp_file.name)
                sys.exit(
                    f'ERROR: migration of parameter file "{filepath}" failed '
                    f"(parametersMigrate.py exited with status {e.returncode}) - see the output "
                    "above for details."
                )
            os.replace(tmp_file.name, filepath)

# Reset an outdated revision in test suite parameter files that explicitly probe this issue.
for filename in ("strictOutdated.xml", "unstrictOutdated.xml"):
    filepath = os.path.join("testSuite", "parameters", filename)
    with open(filepath, 'r') as f:
        content = f.read()
    new_content = re.sub(r'lastModified\s+revision="[a-f0-9]+"', 'lastModified revision="262562000c251ee5b935019673f606a8a8c47c10"', content)
    with open(filepath, 'w') as f:
        f.write(new_content)
