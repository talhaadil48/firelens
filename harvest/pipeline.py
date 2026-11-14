"""Explicit placeholders for the later data-processing phases."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["normalize", "precompute", "snapshot"])
    args = parser.parse_args()
    parser.exit(2, f"{args.stage} belongs to Phases 4–5 and is not implemented in Phase 2.\n")


if __name__ == "__main__":
    main()
