from pathlib import Path

import pytest
from openpyxl import Workbook

from parse_freetext import cli
from parse_freetext.extractor import ExtractionError, SheetInfo, extract_text_files, inspect_spreadsheet


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


def test_inspect_spreadsheet_returns_sheets_and_headers(tmp_path: Path) -> None:
    input_file = tmp_path / "input.xlsx"
    make_workbook(input_file)

    sheets = inspect_spreadsheet(input_file)

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


def test_extracts_text_files_from_csv_named_columns(tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    output_dir = tmp_path / "texts"
    input_file.write_text(
        "Record ID,Notes,Description\n"
        "A-001,First note,First description\n"
        "A-002,,Second description\n"
        "A-003,,\n"
        ",Missing id,Skipped\n",
        encoding="utf-8",
    )

    result = extract_text_files(
        input_file,
        output_dir,
        None,
        "Record ID",
        ["Notes", "Description"],
    )

    assert result.rows_seen == 4
    assert result.files_written == 2
    assert result.files_skipped == 2
    assert (output_dir / "A-001.txt").read_text(encoding="utf-8") == (
        "First note\n\nFirst description\n"
    )
    assert (output_dir / "A-002.txt").read_text(encoding="utf-8") == (
        "Second description\n"
    )


def test_extracts_text_files_from_tsv_numeric_columns(tmp_path: Path) -> None:
    input_file = tmp_path / "input.tsv"
    output_dir = tmp_path / "texts"
    input_file.write_text(
        "Record ID\tNotes\tDescription\n"
        "T-001\tFirst note\tFirst description\n",
        encoding="utf-8",
    )

    result = extract_text_files(input_file, output_dir, None, "1", ["2", "3"])

    assert result.files_written == 1
    assert (output_dir / "T-001.txt").read_text(encoding="utf-8") == (
        "First note\n\nFirst description\n"
    )


def test_extracts_text_files_from_csv_column_letters(tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    output_dir = tmp_path / "texts"
    input_file.write_text("Record ID,Notes\nC-001,CSV note\n", encoding="utf-8")

    result = extract_text_files(input_file, output_dir, None, "A", ["B"])

    assert result.files_written == 1
    assert (output_dir / "C-001.txt").read_text(encoding="utf-8") == "CSV note\n"


def test_raises_for_csv_sheet_option(tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("Record ID,Notes\nC-001,CSV note\n", encoding="utf-8")

    with pytest.raises(ExtractionError, match="--sheet is only supported"):
        extract_text_files(input_file, tmp_path / "texts", ["Sheet1"], "Record ID", ["Notes"])


def test_raises_for_csv_overwrite_collision(tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    output_dir = tmp_path / "texts"
    input_file.write_text("Record ID,Notes\nC-001,CSV note\n", encoding="utf-8")
    output_dir.mkdir()
    (output_dir / "C-001.txt").write_text("old\n", encoding="utf-8")

    with pytest.raises(ExtractionError, match="Output file already exists"):
        extract_text_files(input_file, output_dir, None, "Record ID", ["Notes"])


def test_inspect_csv_returns_table_headers(tmp_path: Path) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("Record ID,Notes\nC-001,CSV note\n", encoding="utf-8")

    sheets = inspect_spreadsheet(input_file)

    assert sheets == [SheetInfo(name="input", headers=["Record ID", "Notes"])]


def test_raises_for_unsupported_spreadsheet_suffix(tmp_path: Path) -> None:
    input_file = tmp_path / "input.ods"
    input_file.write_text("not supported", encoding="utf-8")

    with pytest.raises(ExtractionError, match=".xlsx, .csv, or .tsv"):
        inspect_spreadsheet(input_file)


def test_cli_reports_unsupported_suffix(tmp_path: Path, capsys) -> None:
    input_file = tmp_path / "input.ods"
    input_file.write_text("not supported", encoding="utf-8")

    assert cli.main([str(input_file), "--inspect"]) == 2
    captured = capsys.readouterr()
    assert "supported spreadsheet file" in captured.err


def test_cli_reports_csv_sheet_option(tmp_path: Path, capsys) -> None:
    input_file = tmp_path / "input.csv"
    input_file.write_text("Record ID,Notes\nC-001,CSV note\n", encoding="utf-8")

    assert cli.main(
        [
            str(input_file),
            "--sheet",
            "Sheet1",
            "--transaction-id-column",
            "Record ID",
            "--text-column",
            "Notes",
        ]
    ) == 2
    captured = capsys.readouterr()
    assert "--sheet is only supported" in captured.err


def test_cli_derives_default_prepared_text_output_dir(tmp_path: Path, monkeypatch, capsys) -> None:
    input_file = tmp_path / "raw_records.csv"
    input_file.write_text("Record ID,Notes\nC-001,CSV note\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert cli.main(
        [
            str(input_file),
            "--transaction-id-column",
            "Record ID",
            "--text-column",
            "Notes",
        ]
    ) == 0

    output_file = tmp_path / "input" / "texts" / "raw_records" / "C-001.txt"
    assert output_file.read_text(encoding="utf-8") == "CSV note\n"
    assert "input/texts/raw_records" in capsys.readouterr().out


def test_cli_accepts_explicit_text_output_dir(tmp_path: Path) -> None:
    input_file = tmp_path / "raw_records.csv"
    output_dir = tmp_path / "prepared_texts"
    input_file.write_text("Record ID,Notes\nC-001,CSV note\n", encoding="utf-8")

    assert cli.main(
        [
            str(input_file),
            "--transaction-id-column",
            "Record ID",
            "--text-column",
            "Notes",
            "--text-output-dir",
            str(output_dir),
        ]
    ) == 0

    assert (output_dir / "C-001.txt").read_text(encoding="utf-8") == "CSV note\n"


def test_cli_help_uses_prepared_text_output_wording(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "--text-output-dir" in output
    assert "--output-dir" not in output
    assert "prepared" in output
