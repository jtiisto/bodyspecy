"""CLI for importing BodySpec PDF reports."""

import argparse
import sys
from pathlib import Path

from ..parser.pdf_parser import parse_pdf
from .db import BodyspecDB


DEFAULT_DB_PATH = Path.home() / ".bodyspecy" / "bodyspec.db"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bodyspecy-import",
        description="Import BodySpec DEXA PDF reports into local database",
        epilog="""
Examples:
  %(prog)s ~/diagnostics/bodyspec-results_01-23-2026.pdf
  %(prog)s ~/diagnostics/bodyspec-results_*.pdf
  %(prog)s --database ~/custom/path.db report.pdf
        """,
    )
    parser.add_argument(
        "pdf_files",
        nargs="+",
        type=Path,
        help="PDF report file(s) to import",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})",
    )
    return parser


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()

    db = BodyspecDB(args.database)

    success = 0
    failed = 0

    for pdf_path in args.pdf_files:
        if not pdf_path.exists():
            print(f"File not found: {pdf_path}")
            failed += 1
            continue

        try:
            parsed = parse_pdf(pdf_path)
            db.import_scan(parsed)
            print(f"Imported: {pdf_path.name} (scan date: {parsed.scan_date})")
            success += 1
        except Exception as e:
            print(f"Failed: {pdf_path.name}: {e}")
            failed += 1

    print(f"\nDone: {success} imported, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
