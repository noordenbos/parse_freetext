from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .extractor import ExtractionError, extract_text_files, inspect_spreadsheet


DEFAULT_TEXT_INPUT_ROOT = Path("input/texts")


def default_text_output_dir(input_file: Path) -> Path:
    return DEFAULT_TEXT_INPUT_ROOT / input_file.stem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spreadsheet-helper",
        description=(
            "Extract free-text columns from raw XLSX/CSV/TSV data into prepared "
            "{record_id}.txt input files for parse-freetext-ollama."
        ),
    )
    parser.add_argument("input_file", type=Path, help="Path to the raw .xlsx, .csv, or .tsv input file.")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Print sheet/table names and first-row headers, then exit.",
    )
    parser.add_argument(
        "-o",
        "--text-output-dir",
        type=Path,
        dest="text_output_dir",
        help=(
            "Directory where prepared .txt input files are written. "
            "Default: input/texts/<input_file_stem>"
        ),
    )
    parser.add_argument(
        "-s",
        "--sheet",
        action="append",
        dest="sheets",
        help="Worksheet tab to process for .xlsx files. Repeat to use multiple tabs. Default: all tabs.",
    )
    parser.add_argument(
        "-i",
        "--transaction-id-column",
        required=False,
        help="Column containing record ids. Accepts a header name, number, or letter.",
    )
    parser.add_argument(
        "-t",
        "--text-column",
        action="append",
        required=False,
        dest="text_columns",
        help="Column containing free text. Repeat to extract multiple text columns.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing output files.",
    )
    parser.add_argument(
        "--append-sheet-name",
        action="store_true",
        help="Append the worksheet name to each filename to avoid cross-sheet collisions for .xlsx files.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.inspect:
            for sheet in inspect_spreadsheet(args.input_file):
                headers = ", ".join(sheet.headers) if sheet.headers else "(no headers found)"
                print(f"{sheet.name}: {headers}")
            return 0

        if not args.transaction_id_column:
            parser.error("--transaction-id-column is required unless --inspect is used")
        if not args.text_columns:
            parser.error("--text-column is required unless --inspect is used")

        result = extract_text_files(
            input_file=args.input_file,
            output_dir=args.text_output_dir or default_text_output_dir(args.input_file),
            sheets=args.sheets,
            transaction_id_column=args.transaction_id_column,
            text_columns=args.text_columns,
            overwrite=args.overwrite,
            append_sheet_name=args.append_sheet_name,
        )
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"Wrote {result.files_written} file(s) to {result.output_dir} "
        f"from {result.rows_seen} row(s); skipped {result.files_skipped} row(s)."
    )
    return 0
