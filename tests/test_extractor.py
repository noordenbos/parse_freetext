from pathlib import Path

import pytest
from openpyxl import Workbook

from parse_freetext.extractor import ExtractionError, extract_text_files, inspect_workbook


def make_workbook(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Transactions"
    sheet.append(["Transaction ID", "Notes", "Description"])
    sheet.append(["A-001", "First note", "First description"])
    sheet.append(["A-002", "", "Second description"])
    sheet.append(["A-003", None, None])

    archive = workbook.create_sheet("Archive")
    archive.append(["Transaction ID", "Notes", "Description"])
    archive.append(["B-001", "Archived note", "Archived description"])

    workbook.save(path)


def test_extracts_text_files_from_named_columns(tmp_path: Path) -> None:
    input_file = tmp_path / "input.xlsx"
    output_dir = tmp_path / "texts"
    make_workbook(input_file)

    result = extract_text_files(
        input_file,
        output_dir,
        ["Transactions"],
        "Transaction ID",
        ["Notes", "Description"],
    )

    assert result.rows_seen == 3
    assert result.files_written == 2
    assert result.files_skipped == 1
    assert (output_dir / "A-001.txt").read_text(encoding="utf-8") == (
        "First note\n\nFirst description\n"
    )
    assert (output_dir / "A-002.txt").read_text(encoding="utf-8") == (
        "Second description\n"
    )


def test_inspect_workbook_returns_sheets_and_headers(tmp_path: Path) -> None:
    input_file = tmp_path / "input.xlsx"
    make_workbook(input_file)

    sheets = inspect_workbook(input_file)

    assert sheets[0].name == "Transactions"
    assert sheets[0].headers == ["Transaction ID", "Notes", "Description"]
    assert sheets[1].name == "Archive"


def test_extracts_from_column_letters_and_appends_sheet_name(tmp_path: Path) -> None:
    input_file = tmp_path / "input.xlsx"
    output_dir = tmp_path / "texts"
    make_workbook(input_file)

    result = extract_text_files(
        input_file,
        output_dir,
        ["Transactions", "Archive"],
        "A",
        ["B"],
        append_sheet_name=True,
    )

    assert result.files_written == 2
    assert (output_dir / "A-001_Transactions.txt").exists()
    assert not (output_dir / "A-002_Transactions.txt").exists()
    assert (output_dir / "B-001_Archive.txt").exists()


def test_raises_for_unknown_sheet(tmp_path: Path) -> None:
    input_file = tmp_path / "input.xlsx"
    make_workbook(input_file)

    with pytest.raises(ExtractionError, match="Unknown sheet"):
        extract_text_files(input_file, tmp_path / "texts", ["Missing"], "A", ["B"])
