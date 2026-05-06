import csv
import json
from pathlib import Path

from parse_freetext import ollama_parser
from parse_freetext.ollama_parser import (
    add_call_stats,
    build_run_summary,
    build_prompt,
    build_schema,
    call_ollama,
    compact_alias_response,
    derived_output_paths,
    extract_ollama_metadata,
    expand_alias_response,
    generate_alias_map,
    main,
    model_alias_fields,
    normalize_records,
    parse_rulebook_columns,
    parse_rulebook_inherited_fields,
    process_folder,
    rulebook_has_output_columns,
    strip_rulebook_structural_sections,
    validate_rulebook_structure,
    write_prompt_files,
)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_normalize_records_sets_record_and_row_ids() -> None:
    data = {
        "records": [
            {
                "record_id": "wrong",
                "row_id": 99,
                "clinical_item": "LDL",
                "value": "",
                "unit": "mmol/L",
                "quality_of_parsing": "high",
                "event_date": "",
                "details": None,
            }
        ]
    }

    rows = normalize_records(data, "MED-001")

    assert rows[0]["record_id"] == "MED-001"
    assert rows[0]["row_id"] == 1
    assert rows[0]["value"] is None
    assert rows[0]["event_date"] is None


def test_process_folder_writes_csv_and_jsonl(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "MED-001.txt").write_text("LDL 3.2 mmol/L", encoding="utf-8")

    def fake_call_ollama(**kwargs):
        return {
            "records": [
                {
                    "record_id": "wrong",
                    "row_id": 99,
                    "clinical_item": "LDL",
                    "value": 3.2,
                    "unit": "mmol/L",
                    "quality_of_parsing": "high",
                    "event_date": None,
                    "details": None,
                }
            ]
        }

    monkeypatch.setattr(ollama_parser, "call_ollama", fake_call_ollama)

    output_csv = tmp_path / "out" / "records.csv"
    output_jsonl = tmp_path / "out" / "records.jsonl"
    prompt_dir = tmp_path / "prompts"
    count = process_folder(
        input_dir,
        output_csv,
        output_jsonl,
        "test-model",
        prompt_output_dir=prompt_dir,
        rules_file=None,
    )

    assert count == 1
    with output_csv.open(encoding="utf-8", newline="") as csv_file:
        csv_rows = list(csv.DictReader(csv_file))
    assert csv_rows[0]["clinical_item"] == "LDL"
    assert csv_rows[0]["value"] == "3.2"

    jsonl_rows = [
        json.loads(line)
        for line in output_jsonl.read_text(encoding="utf-8").splitlines()
    ]
    assert jsonl_rows[0]["unit"] == "mmol/L"
    assert (prompt_dir / "MED-001_prompt.txt").exists()


def test_call_ollama_disables_thinking_by_default(monkeypatch) -> None:
    captured_payload = {}

    def fake_urlopen(req, timeout):
        captured_payload.update(json.loads(req.data.decode("utf-8")))
        return FakeResponse({"response": '{"records": []}'})

    monkeypatch.setattr(ollama_parser.request, "urlopen", fake_urlopen)

    assert call_ollama("prompt", "qwen3.5:9b") == {"records": []}
    assert captured_payload["think"] is False


def test_call_ollama_can_return_usage_metadata(monkeypatch) -> None:
    def fake_urlopen(req, timeout):
        return FakeResponse(
            {
                "response": '{"records": []}',
                "done": True,
                "done_reason": "stop",
                "total_duration": 1_000_000_000,
                "prompt_eval_count": 10,
                "prompt_eval_duration": 500_000_000,
                "eval_count": 20,
                "eval_duration": 1_000_000_000,
            }
        )

    monkeypatch.setattr(ollama_parser.request, "urlopen", fake_urlopen)

    data, metadata = call_ollama("prompt", "qwen3.5:9b", return_metadata=True)

    assert data == {"records": []}
    assert metadata["done_reason"] == "stop"
    assert metadata["prompt_eval_count"] == 10
    assert metadata["eval_tokens_per_second"] == 20


def test_extract_ollama_metadata_does_not_include_response_text() -> None:
    metadata = extract_ollama_metadata(
        {
            "response": "secret",
            "thinking": "private chain",
            "eval_count": 5,
            "eval_duration": 1_000_000_000,
        },
        "secret",
    )

    assert "response" not in metadata
    assert "thinking" not in metadata
    assert metadata["response_chars"] == 6
    assert metadata["thinking_chars"] == 13


def test_build_run_summary_includes_ollama_api_stats() -> None:
    stats = ollama_parser.new_run_stats(2)
    stats["successful_files"] = 2
    add_call_stats(
        stats,
        success=True,
        records=3,
        elapsed_ns=2_000_000_000,
        ollama_metadata={
            "prompt_eval_count": 100,
            "prompt_eval_duration": 2_000_000_000,
            "eval_count": 50,
            "eval_duration": 1_000_000_000,
            "total_duration": 3_000_000_000,
            "load_duration": 500_000_000,
        },
    )

    summary = "\n".join(build_run_summary(stats, wall_seconds=3.5))

    assert "Files: 2 total, 2 succeeded, 0 failed" in summary
    assert "Records: 3" in summary
    assert "Ollama tokens: 100 prompt, 50 generated" in summary
    assert "Ollama generation: 1.00s (50.00 tok/s)" in summary


def test_call_ollama_uses_dynamic_schema(monkeypatch) -> None:
    captured_payload = {}
    schema = build_schema(["record_id", "finding"], {"record_id": "string", "finding": "string"}, "records")

    def fake_urlopen(req, timeout):
        captured_payload.update(json.loads(req.data.decode("utf-8")))
        return FakeResponse({"response": '{"records": []}'})

    monkeypatch.setattr(ollama_parser.request, "urlopen", fake_urlopen)

    assert call_ollama("prompt", "test-model", schema=schema) == {"records": []}
    assert "rs" in captured_payload["format"]["properties"]


def test_build_prompt_omits_rules_without_rulebook() -> None:
    prompt = build_prompt("TX-001.txt", "Client receives EUR 50")

    assert "User-provided extraction rulebook" not in prompt
    assert "Local rule" not in prompt


def test_build_prompt_includes_rules_from_rulebook() -> None:
    prompt = build_prompt(
        "TX-001.txt",
        "Client receives EUR 50",
        "Local rule",
        ["record_id", "finding"],
        "records",
    )

    assert "Domain rules" in prompt
    assert "Local rule" in prompt
    assert "Rows key: rs" in prompt
    assert "- record_id ->" not in prompt
    assert "aa=finding" in prompt


def test_build_prompt_does_not_repeat_columns_when_rulebook_declares_them() -> None:
    prompt = build_prompt(
        "TX-001.txt",
        "Client receives EUR 50",
        "Output columns:\n- record_id (string): filename stem.",
        ["record_id", "document_context", "finding"],
        "records",
        rulebook_declares_columns=True,
    )

    assert "The final CSV/JSONL output must use these columns" not in prompt
    assert "Top-level only: aa=document_context." in prompt
    assert "Row fields: ab=finding." in prompt
    assert "row-specific columns" not in prompt


def test_generate_alias_map_is_deterministic_and_unique() -> None:
    fields = [f"field_{i}" for i in range(30)]
    alias_map = generate_alias_map(fields)

    assert alias_map["field_0"] == "aa"
    assert alias_map["field_1"] == "ab"
    assert alias_map["field_25"] == "az"
    assert alias_map["field_26"] == "ba"
    assert len(set(alias_map.values())) == len(fields)


def test_parse_rulebook_columns_reads_structured_output_columns() -> None:
    fields, field_types = parse_rulebook_columns(
        """
Output columns:
- record_id (string): filename stem.
- row_id (integer): row number.
- finding (string): clinical finding.
- value (number): numeric measurement.

Goal:
- Extract medical observations.
"""
    )

    assert fields == ["record_id", "row_id", "finding", "value"]
    assert field_types["row_id"] == "integer"
    assert field_types["value"] == "number"


def test_parse_rulebook_columns_accepts_descriptionless_columns() -> None:
    fields, field_types = parse_rulebook_columns(
        """
Output columns:
- record_id (string): filename stem.
- bank_name (string)
- bank_details (string)
"""
    )

    assert fields == ["record_id", "bank_name", "bank_details"]
    assert field_types["bank_name"] == "string"


def test_strip_rulebook_structural_sections_keeps_domain_rules() -> None:
    stripped = strip_rulebook_structural_sections(
        """
Output columns:
- record_id (string): filename stem.
- finding (string): clinical finding.

Python-filled fields:
- record_id

Inherited fields:
- event_date (string): shared date.

Rules:
- Extract rows.

Examples:
- LDL -> finding LDL.
"""
    )

    assert "Output columns" not in stripped
    assert "Python-filled fields" not in stripped
    assert "Inherited fields" not in stripped
    assert "Rules:" in stripped
    assert "Examples:" in stripped


def test_validate_rulebook_structure_reports_malformed_structural_sections() -> None:
    try:
        validate_rulebook_structure(
            """
Output columns:
- record_id (str)
- finding (string)

Inherited fields:
- missing_date
"""
        )
    except ollama_parser.OllamaParseError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected malformed rulebook to fail validation")

    assert "Rulebook structural format warning" in message
    assert "line 3: malformed bullet in Output columns" in message
    assert "Inherited field is not an output column: missing_date" in message
    assert "Quick rulebook structural format walkthrough" in message


def test_rulebook_has_output_columns_detects_heading() -> None:
    assert rulebook_has_output_columns("Output columns:\n- value (number): amount.")
    assert rulebook_has_output_columns("Fields:\n- value (number): amount.")
    assert not rulebook_has_output_columns("Rules:\n- Extract values.")


def test_parse_rulebook_inherited_fields_reads_declared_fields() -> None:
    inherited_fields = parse_rulebook_inherited_fields(
        """
Output columns:
- record_id (string): filename stem.
- transaction_date (string): date.

Inherited fields:
- transaction_date (string): shared date or period.

Rules:
- Extract rows.
""",
        ["record_id", "transaction_date"],
    )

    assert inherited_fields == ["transaction_date"]


def test_python_filled_fields_are_not_model_aliases_or_schema_fields() -> None:
    fields = ["transaction_id_parent", "sub_id", "document_context", "transaction_date", "party"]
    alias_map = generate_alias_map(model_alias_fields(fields, ["transaction_date"]))
    schema = build_schema(
        fields,
        {
            "transaction_id_parent": "string",
            "sub_id": "integer",
            "document_context": "string",
            "transaction_date": "string",
            "party": "string",
        },
        "records",
        alias_map,
        inherited_fields=["transaction_date"],
    )

    assert "transaction_id_parent" not in alias_map
    assert "sub_id" not in alias_map
    assert alias_map == {"document_context": "aa", "transaction_date": "ab", "party": "ac"}
    assert "aa" in schema["properties"]
    assert "ab" in schema["properties"]
    assert "ac" in schema["properties"]["rs"]["items"]["properties"]


def test_normalize_records_uses_dynamic_fields_and_record_ids() -> None:
    rows = normalize_records(
        {"records": [{"record_id": "wrong", "row_id": 99, "finding": "LDL", "value": ""}]},
        "TX-001",
        ["record_id", "row_id", "finding", "value"],
        "records",
    )

    assert rows == [
        {
            "record_id": "TX-001",
            "row_id": 1,
            "finding": "LDL",
            "value": None,
        }
    ]


def test_process_folder_writes_dynamic_columns_from_rulebook(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "MED-001.txt").write_text("LDL 3.2 mmol/L", encoding="utf-8")
    rules_file = tmp_path / "rulebook.txt"
    rules_file.write_text(
        """
Output columns:
- record_id (string): filename stem.
- row_id (integer): row number.
- finding (string): clinical finding.
- value (number): numeric measurement.
- unit (string): measurement unit.
""",
        encoding="utf-8",
    )

    def fake_call_ollama(**kwargs):
        assert "rs" in kwargs["schema"]["properties"]
        return {
            "rs": [
                {
                    "aa": "LDL",
                    "ab": 3.2,
                    "ac": "mmol/L",
                }
            ]
        }

    monkeypatch.setattr(ollama_parser, "call_ollama", fake_call_ollama)

    output_csv = tmp_path / "out" / "medical.csv"
    output_jsonl = tmp_path / "out" / "medical.jsonl"
    count = process_folder(input_dir, output_csv, output_jsonl, "test-model", rules_file=rules_file)

    assert count == 1
    with output_csv.open(encoding="utf-8", newline="") as csv_file:
        csv_rows = list(csv.DictReader(csv_file))
    assert csv_rows[0] == {
        "record_id": "MED-001",
        "row_id": "1",
        "finding": "LDL",
        "value": "3.2",
        "unit": "mmol/L",
    }


def test_shared_document_context_is_top_level_and_copied_to_rows() -> None:
    fields = ["transaction_id_parent", "sub_id", "document_context", "transaction_details"]
    alias_map = generate_alias_map(fields)
    schema = build_schema(
        fields,
        {
            "transaction_id_parent": "string",
            "sub_id": "integer",
            "document_context": "string",
            "transaction_details": "string",
        },
        "records",
        alias_map,
    )

    assert "ac" in schema["properties"]
    assert "ac" not in schema["required"]
    assert schema["additionalProperties"] is False
    row_schema = schema["properties"]["rs"]["items"]
    assert "ac" not in row_schema["properties"]
    assert "ac" not in row_schema["required"]
    assert row_schema["required"] == []
    assert row_schema["additionalProperties"] is False

    rows = normalize_records(
        {
            "document_context": "Shared dossier context.",
            "records": [
                {
                    "transaction_id_parent": "wrong",
                    "sub_id": 99,
                    "transaction_details": "Row-only detail.",
                }
            ],
        },
        "1",
        fields,
        "records",
    )

    assert rows == [
        {
            "transaction_id_parent": "1",
            "sub_id": 1,
            "document_context": "Shared dossier context.",
            "transaction_details": "Row-only detail.",
        }
    ]


def test_inherited_field_can_be_top_level_or_row_override() -> None:
    fields = [
        "transaction_id_parent",
        "sub_id",
        "document_context",
        "transaction_date",
        "transaction_details",
    ]
    alias_map = generate_alias_map(fields)
    schema = build_schema(
        fields,
        {
            "transaction_id_parent": "string",
            "sub_id": "integer",
            "document_context": "string",
            "transaction_date": "string",
            "transaction_details": "string",
        },
        "records",
        alias_map,
        inherited_fields=["transaction_date"],
    )

    assert "ac" in schema["properties"]
    assert "ad" in schema["properties"]
    row_schema = schema["properties"]["rs"]["items"]
    assert "ac" not in row_schema["properties"]
    assert "ad" in row_schema["properties"]

    rows = normalize_records(
        {
            "document_context": "Shared dossier context.",
            "transaction_date": "2025-01-01 to 2025-07-01",
            "records": [
                {"transaction_id_parent": "wrong", "sub_id": 99},
                {
                    "transaction_id_parent": "wrong",
                    "sub_id": 99,
                    "transaction_date": "2025-03-01",
                },
            ],
        },
        "1",
        fields,
        "records",
        inherited_fields=["transaction_date"],
    )

    assert rows[0]["transaction_date"] == "2025-01-01 to 2025-07-01"
    assert rows[1]["transaction_date"] == "2025-03-01"


def test_alias_response_expands_to_canonical_fields() -> None:
    fields = ["transaction_id_parent", "sub_id", "document_context", "transaction_details"]
    alias_map = generate_alias_map(fields)

    expanded = expand_alias_response(
        {
            "ac": "Shared dossier context.",
            "rs": [
                {
                    "aa": "wrong",
                    "ab": 99,
                    "ad": "Row-only detail.",
                }
            ],
        },
        fields,
        "records",
        alias_map,
    )

    assert expanded == {
        "document_context": "Shared dossier context.",
        "records": [
            {
                "transaction_id_parent": "wrong",
                "sub_id": 99,
                "transaction_details": "Row-only detail.",
            }
        ],
    }


def test_schema_omits_null_types_and_optional_row_fields() -> None:
    fields = ["record_id", "value", "notes"]
    schema = build_schema(
        fields,
        {"record_id": "string", "value": "number", "notes": "string"},
        "records",
    )
    row_schema = schema["properties"]["rs"]["items"]

    assert row_schema["required"] == []
    assert row_schema["properties"]["aa"] == {"type": "number"}
    assert row_schema["properties"]["ab"] == {"type": "string"}
    assert "record_id" not in row_schema["properties"]


def test_compact_alias_response_omits_none_values() -> None:
    fields = ["record_id", "document_context", "finding", "notes"]
    alias_map = generate_alias_map(model_alias_fields(fields))

    compact = compact_alias_response(
        {
            "document_context": None,
            "records": [
                {
                    "record_id": "MED-001",
                    "finding": "LDL",
                    "notes": None,
                }
            ],
        },
        fields,
        "records",
        alias_map,
    )

    assert compact == {"rs": [{"ab": "LDL"}]}


def test_derived_output_paths_nest_relative_names_under_output() -> None:
    paths = derived_output_paths(Path("final_test_qwen35"))

    assert paths["run_dir"] == Path("output/final_test_qwen35")
    assert paths["csv"] == Path("output/final_test_qwen35/final_test_qwen35.csv")
    assert paths["jsonl"] == Path("output/final_test_qwen35/final_test_qwen35.jsonl")
    assert paths["compact_jsonl"] == Path("output/final_test_qwen35/final_test_qwen35.compact.jsonl")
    assert paths["call_log_jsonl"] == Path("output/final_test_qwen35/final_test_qwen35.ollama_calls.jsonl")
    assert paths["prompt_output_dir"] == Path("output/final_test_qwen35/prompts")
    assert paths["run_metadata"] == Path("output/final_test_qwen35/run_metadata.txt")


def test_derived_output_paths_keep_absolute_paths() -> None:
    paths = derived_output_paths(Path("/tmp/final_test_qwen35.csv"))

    assert paths["run_dir"] == Path("/tmp/final_test_qwen35")
    assert paths["csv"] == Path("/tmp/final_test_qwen35/final_test_qwen35.csv")
    assert paths["jsonl"] == Path("/tmp/final_test_qwen35/final_test_qwen35.jsonl")


def test_process_folder_writes_optional_compact_jsonl(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "MED-001.txt").write_text("LDL 3.2 mmol/L", encoding="utf-8")
    rules_file = tmp_path / "rulebook.txt"
    rules_file.write_text(
        """
Output columns:
- record_id (string): filename stem.
- row_id (integer): row number.
- finding (string): clinical finding.
""",
        encoding="utf-8",
    )

    compact_response = {"rs": [{"aa": "LDL"}]}

    def fake_call_ollama(**kwargs):
        return compact_response

    monkeypatch.setattr(ollama_parser, "call_ollama", fake_call_ollama)

    output_csv = tmp_path / "out" / "medical.csv"
    output_jsonl = tmp_path / "out" / "medical.jsonl"
    output_compact_jsonl = tmp_path / "out" / "medical.compact.jsonl"
    process_folder(
        input_dir,
        output_csv,
        output_jsonl,
        "test-model",
        rules_file=rules_file,
        output_compact_jsonl=output_compact_jsonl,
    )

    assert json.loads(output_jsonl.read_text(encoding="utf-8")) == {
        "record_id": "MED-001",
        "row_id": 1,
        "finding": "LDL",
    }
    assert json.loads(output_compact_jsonl.read_text(encoding="utf-8")) == compact_response


def test_process_folder_writes_call_log(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "MED-001.txt").write_text("LDL 3.2 mmol/L", encoding="utf-8")
    rules_file = tmp_path / "rulebook.txt"
    rules_file.write_text(
        """
Output columns:
- record_id (string): filename stem.
- row_id (integer): row number.
- finding (string): clinical finding.
""",
        encoding="utf-8",
    )

    def fake_call_ollama(**kwargs):
        return (
            {"rs": [{"aa": "LDL"}]},
            {
                "done_reason": "stop",
                "prompt_eval_count": 10,
                "eval_count": 5,
                "response_chars": 100,
            },
        )

    monkeypatch.setattr(ollama_parser, "call_ollama", fake_call_ollama)

    output_csv = tmp_path / "out" / "medical.csv"
    output_jsonl = tmp_path / "out" / "medical.jsonl"
    call_log = tmp_path / "out" / "calls.jsonl"
    process_folder(
        input_dir,
        output_csv,
        output_jsonl,
        "test-model",
        rules_file=rules_file,
        call_log_jsonl=call_log,
    )

    entry = json.loads(call_log.read_text(encoding="utf-8"))
    assert entry["success"] is True
    assert entry["input_file"] == "MED-001.txt"
    assert entry["records_extracted"] == 1
    assert entry["ollama"]["prompt_eval_count"] == 10
    assert "prompt" not in entry


def test_process_folder_writes_run_metadata(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "MED-001.txt").write_text("LDL 3.2 mmol/L", encoding="utf-8")
    rules_file = tmp_path / "rulebook.txt"
    rules_file.write_text(
        """
Output columns:
- record_id (string): filename stem.
- row_id (integer): row number.
- finding (string): clinical finding.
""",
        encoding="utf-8",
    )

    def fake_call_ollama(**kwargs):
        return {"rs": [{"aa": "LDL"}]}

    def fake_run_git_command(args):
        if args == ["status", "--short"]:
            return " M README.md"
        if args == ["describe", "--tags", "--exact-match"]:
            return "1.0.0"
        if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return "main"
        if args == ["rev-parse", "HEAD"]:
            return "abc123"
        return ""

    monkeypatch.setattr(ollama_parser, "call_ollama", fake_call_ollama)
    monkeypatch.setattr(ollama_parser, "run_git_command", fake_run_git_command)

    output_csv = tmp_path / "out" / "medical.csv"
    output_jsonl = tmp_path / "out" / "medical.jsonl"
    run_metadata = tmp_path / "out" / "run_metadata.txt"
    process_folder(
        input_dir,
        output_csv,
        output_jsonl,
        "test-model",
        rules_file=rules_file,
        run_metadata=run_metadata,
        command=["parse-freetext-ollama", "texts", "--output", "medical"],
    )

    metadata = run_metadata.read_text(encoding="utf-8")
    assert "package_version: 1.0.0" in metadata
    assert "status: completed" in metadata
    assert "git_exact_tag: 1.0.0" in metadata
    assert "git_dirty: yes" in metadata
    assert "parse-freetext-ollama texts --output medical" in metadata
    assert "rows_written: 1" in metadata
    assert "LDL 3.2" not in metadata


def test_normalize_records_removes_direction_only_transaction_details() -> None:
    rows = normalize_records(
        {
            "records": [
                {
                    "transaction_id_parent": "wrong",
                    "sub_id": 99,
                    "direction": "outgoing",
                    "transaction_details": "Outgoing transfer",
                }
            ]
        },
        "1",
        ["transaction_id_parent", "sub_id", "direction", "transaction_details"],
        "records",
    )

    assert rows[0]["transaction_details"] is None


def test_write_prompt_files_without_calling_model(tmp_path: Path) -> None:
    input_dir = tmp_path / "texts"
    output_dir = tmp_path / "prompts"
    input_dir.mkdir()
    (input_dir / "TX-001.txt").write_text("Client receives EUR 50", encoding="utf-8")

    count = write_prompt_files(input_dir, output_dir, rules_file=None)

    prompt = (output_dir / "TX-001_prompt.txt").read_text(encoding="utf-8")
    assert count == 1
    assert "JSON shape:" in prompt
    assert "Return only JSON" in prompt
    assert "Client receives EUR 50" in prompt


def test_prompts_only_uses_default_prompt_output_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "TX-001.txt").write_text("Client receives EUR 50", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main([str(input_dir), "--prompts-only", "--rules-file", "missing-default.txt"]) == 2
    assert not (tmp_path / "output" / "prompts" / "TX-001_prompt.txt").exists()

    assert main([str(input_dir), "--prompts-only", "--rules-file", "rules/ollama_rulebook.txt"]) == 0
    assert (tmp_path / "output" / "prompts" / "TX-001_prompt.txt").exists()


def test_prompts_only_with_output_uses_run_prompt_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "TX-001.txt").write_text("Client receives EUR 50", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main(
        [
            str(input_dir),
            "--prompts-only",
            "--rules-file",
            "rules/ollama_rulebook.txt",
            "--output",
            "prompt_check",
        ]
    ) == 0
    assert (tmp_path / "output" / "prompt_check" / "prompts" / "TX-001_prompt.txt").exists()


def test_main_derives_outputs_from_single_output_name(tmp_path: Path, monkeypatch) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "TX-001.txt").write_text("Client receives EUR 50", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    captured = {}

    def fake_process_folder(**kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(ollama_parser, "process_folder", fake_process_folder)

    assert main([str(input_dir), "--output", "final_test_qwen35"]) == 0
    assert captured["output_csv"] == Path("output/final_test_qwen35/final_test_qwen35.csv")
    assert captured["output_jsonl"] == Path("output/final_test_qwen35/final_test_qwen35.jsonl")
    assert captured["output_compact_jsonl"] == Path(
        "output/final_test_qwen35/final_test_qwen35.compact.jsonl"
    )
    assert captured["call_log_jsonl"] == Path(
        "output/final_test_qwen35/final_test_qwen35.ollama_calls.jsonl"
    )
    assert captured["prompt_output_dir"] == Path("output/final_test_qwen35/prompts")
    assert captured["run_metadata"] == Path("output/final_test_qwen35/run_metadata.txt")


def test_main_prints_rulebook_format_walkthrough(
    tmp_path: Path,
    capsys,
) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "TX-001.txt").write_text("Client receives EUR 50", encoding="utf-8")
    rules_file = tmp_path / "bad_rulebook.txt"
    rules_file.write_text(
        """
Output columns:
- record_id (str)
""",
        encoding="utf-8",
    )

    assert main([str(input_dir), "--prompts-only", "--rules-file", str(rules_file)]) == 2
    output = capsys.readouterr().out
    assert "Rulebook structural format warning" in output
    assert "Quick rulebook structural format walkthrough" in output
    assert "error:" not in output
