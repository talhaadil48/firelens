"""Data pipeline orchestration for harvesting, normalization, precomputation, and snapshots."""

import argparse
import sys

from harvest.crawler import main as harvest_main


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["harvest", "normalize", "precompute", "snapshot"])
    args, unknown = parser.parse_known_args()
    if args.stage == "harvest":
        sys.argv = [sys.argv[0]] + unknown
        harvest_main()
    else:
        parser.exit(2, f"{args.stage} belongs to Phases 4–5 and is not implemented yet.\n")


if __name__ == "__main__":
    main()
