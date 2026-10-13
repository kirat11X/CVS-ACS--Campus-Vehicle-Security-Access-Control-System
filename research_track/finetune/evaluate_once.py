"""Placeholder evaluator contract for approved runs; intentionally does not execute training."""

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--track", required=True, choices=("A", "B", "C"))
    parser.add_argument("--test-manifest", required=True)
    args = parser.parse_args()
    raise SystemExit(
        f"G3 STOP: evaluation is prepared for Track {args.track}; "
        "an approved run implementation must enforce one test-split evaluation."
    )


if __name__ == "__main__":
    main()
