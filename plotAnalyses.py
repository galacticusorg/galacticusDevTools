#!/usr/bin/env python3
import argparse
from pathlib import Path
from dendros import list_analyses, open_outputs, plot_analyses

# Overlay the `analyses` group results from pairs of Galacticus HDF5 files, writing one PDF per analysis.
# Andrew Benson (03-June-2026).

# Given a test path and a reference path, every Galacticus HDF5 file present in *both* locations (matched by file name) has its
# `function1D` analyses under `/analyses` overlaid (test curve versus reference curve, plus any target/observational overlay) and
# saved as PDFs into a per-model subdirectory `analyses_<model>/` under the output directory. Each path may be a directory (searched
# for HDF5 files) or a single HDF5 file. Requires the `dendros` package.


def find_models(path, pattern):
    """Return a mapping of file name -> path for HDF5 files at `path`, which may be a single HDF5 file or a directory to search."""
    if path.is_file():
        return {path.name: path}
    if path.is_dir():
        return {p.name: p for p in sorted(path.glob(pattern))}
    raise SystemExit(f"Path does not exist: {path}")


def main():
    parser = argparse.ArgumentParser(description="Overlay Galacticus `analyses` results for HDF5 files found in both of two paths.")
    parser.add_argument("test_path", type=Path, help="test HDF5 file or directory of HDF5 files")
    parser.add_argument("reference_path", type=Path, help="reference HDF5 file or directory of HDF5 files")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path.cwd(),
                        help="directory to write analyses_<model>/ subdirectories into (default: current directory)")
    parser.add_argument("-g", "--glob", default="*.hdf5",
                        help="glob pattern used to find HDF5 files within a directory (default: *.hdf5)")
    args = parser.parse_args()

    test_models = find_models(args.test_path.resolve(), args.glob)
    reference_models = find_models(args.reference_path.resolve(), args.glob)

    # Plot only models that appear in both locations, matched by file name.
    common = sorted(set(test_models) & set(reference_models))
    if not common:
        raise SystemExit(
            f"No HDF5 files common to both paths.\n"
            f"  test ({args.test_path}): {sorted(test_models) or 'none'}\n"
            f"  reference ({args.reference_path}): {sorted(reference_models) or 'none'}"
        )

    only_test = sorted(set(test_models) - set(reference_models))
    only_reference = sorted(set(reference_models) - set(test_models))
    if only_test:
        print(f"Skipping (only in test): {', '.join(only_test)}")
    if only_reference:
        print(f"Skipping (only in reference): {', '.join(only_reference)}")

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for name in common:
        stem = Path(name).stem
        out_dir = args.output_dir / f"analyses_{stem}"

        # Overlay the test model against the reference model of the same name. The dict keys become the legend labels.
        collections = {
            "test": open_outputs(test_models[name]),
            "reference": open_outputs(reference_models[name]),
        }

        print(f"\n=== {name} ===")
        print(list_analyses(collections["test"], format="tabulate"))

        figs = plot_analyses(collections, output_directory=out_dir, file_format="pdf")
        print(f"Wrote {len(figs)} PDF(s) to {out_dir}/")
        for fig_name in sorted(figs):
            print(f"  - {fig_name}.pdf")


if __name__ == "__main__":
    main()
