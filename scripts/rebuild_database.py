from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").exists()
)

DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "rugby_league_pricing.db"


def run_module(module: str, *arguments: str) -> None:
    """Run a Python module and stop immediately if it fails."""
    command = [
        sys.executable,
        "-m",
        module,
        *arguments,
    ]

    print(f"\nRunning: {' '.join(command)}")

    subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=True,
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild the rugby league pricing database."
    )

    parser.add_argument(
        "--start-season",
        type=int,
        required=True,
        help="First season to ingest, for example 2025.",
    )

    parser.add_argument(
        "--end-season",
        type=int,
        required=True,
        help="Final season to ingest, for example 2026.",
    )

    parser.add_argument(
        "--database-path",
        type=Path,
        default=DEFAULT_DATABASE_PATH,
        help=f"Database path. Default: {DEFAULT_DATABASE_PATH}",
    )

    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing database before rebuilding it.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if args.start_season > args.end_season:
        raise ValueError("--start-season cannot be later than --end-season")

    database_path = args.database_path.resolve()

    if args.reset and database_path.exists():
        database_path.unlink()
        print(f"Deleted existing database: {database_path}")

    if database_path.exists():
        raise FileExistsError(
            f"Database already exists: {database_path}\n"
            "Use --reset to delete and recreate it."
        )

    run_module("scripts.initialise_database")

    run_module(
        "scripts.results.rugby_league_project.ingest_results",
        "--start-season",
        str(args.start_season),
        "--end-season",
        str(args.end_season),
        "--database-path",
        str(database_path),
    )

    run_module("scripts.features.rebuild_recent_form")
    run_module("scripts.features.rebuild_strength_multipliers")
    run_module("scripts.features.rebuild_expected_scores")
    run_module("scripts.pricing.rebuild_historical_matrix")

    print(f"\nDatabase rebuild complete: {database_path}")


if __name__ == "__main__":
    main()