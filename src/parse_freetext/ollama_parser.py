from __future__ import annotations

import argparse
import csv
import json
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

from . import __version__


DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_RULES_FILE = Path("rules/ollama_rulebook.txt")
DEFAULT_PROMPT_OUTPUT_DIR = Path("output/prompts")
DEFAULT_CALL_LOG_JSONL = Path("output/ollama_calls.jsonl")
DEFAULT_OUTPUT_BASENAME = "records_extracted"
DEFAULT_RUN_METADATA = "run_metadata.txt"

DEFAULT_FIELDS = [
    "record_id",
    "row_id",
    "clinical_item",
    "value",
    "unit",
    "qualitative_status",
    "event_date",
    "source_party",
    "source_context",
    "details",
    "quality_of_parsing",
]

DEFAULT_FIELD_TYPES = {
    "record_id": "string",
    "row_id": "integer",
    "clinical_item": "string",
    "value": "number",
    "unit": "string",
    "qualitative_status": "string",
    "event_date": "string",
    "source_party": "string",
    "source_context": "string",
    "details": "string",
    "quality_of_parsing": "string",
}

FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
OUTPUT_COLUMNS_HEADING_RE = re.compile(r"^\s*(output\s+(columns|fields)|columns|fields)\s*:\s*$", re.I)
INHERITED_FIELDS_HEADING_RE = re.compile(r"^\s*inherited\s+fields\s*:\s*$", re.I)
PYTHON_FILLED_FIELDS_HEADING_RE = re.compile(r"^\s*python-filled\s+fields\s*:\s*$", re.I)
SECTION_HEADING_RE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9 _/-]{0,80}:\s*$")
FIELD_LINE_RE = re.compile(
    r"^\s*[-*]\s*`?(?P<name>[A-Za-z_][A-Za-z0-9_]*)`?"
    r"(?:\s*\((?P<type>string|number|integer|boolean)\))?"
    r"(?:\s*:.*)?\s*$",
    re.I,
)
SUPPORTED_FIELD_TYPES = {"string", "number", "integer", "boolean"}
SHARED_CONTEXT_FIELDS = {"document_context"}
PYTHON_FILLED_FIELD_NAMES = {
    "transaction_id_parent",
    "parent_id",
    "record_id",
    "source_id",
    "sub_id",
    "row_id",
    "row_number",
    "item_index",
}
ROOT_KEY_ALIAS = "rs"
OLLAMA_USAGE_FIELDS = [
    "total_duration",
    "load_duration",
    "prompt_eval_count",
    "prompt_eval_duration",
    "eval_count",
    "eval_duration",
]

RULEBOOK_FORMAT_WALKTHROUGH = """Quick rulebook structural format walkthrough:

Output columns:
- column_name (string)
- amount (number)
- row_number (integer)
- flag (boolean)

Python-filled fields:
- record_id
- row_id

Inherited fields:
- event_date

Rules:
- Put field meanings, normalization, and extraction behavior here.

Notes:
- Keep structural sections as bullet lists of field names and optional types.
- Supported types: string, number, integer, boolean.
- Put descriptions and behavioral instructions in Rules, not Output columns."""


class OllamaParseError(RuntimeError):
    """Raised when text parsing through Ollama cannot complete."""


def root_key_for_fields(fields: list[str]) -> str:
    return "records"


def split_shared_fields(fields: list[str]) -> tuple[list[str], list[str]]:
    shared_fields = [field for field in fields if field in SHARED_CONTEXT_FIELDS]
    row_fields = [field for field in fields if field not in SHARED_CONTEXT_FIELDS]
    return row_fields, shared_fields


def split_model_fields(
    fields: list[str],
    inherited_fields: list[str] | None = None,
    python_filled_fields: list[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    inherited_fields = inherited_fields or []
    python_filled_fields = python_filled_fields or infer_python_filled_fields(fields)
    shared_fields = [
        field for field in fields
        if field in SHARED_CONTEXT_FIELDS and field not in python_filled_fields
    ]
    row_fields = [
        field for field in fields
        if field not in shared_fields and field not in python_filled_fields
    ]
    top_level_fields = shared_fields + [
        field for field in inherited_fields
        if field in fields and field not in shared_fields and field not in python_filled_fields
    ]
    return row_fields, shared_fields, top_level_fields


def infer_python_filled_fields(fields: list[str]) -> list[str]:
    return [field for field in fields if field in PYTHON_FILLED_FIELD_NAMES]


def model_alias_fields(
    fields: list[str],
    inherited_fields: list[str] | None = None,
    python_filled_fields: list[str] | None = None,
) -> list[str]:
    python_filled_fields = python_filled_fields or infer_python_filled_fields(fields)
    row_fields, _shared_fields, top_level_fields = split_model_fields(
        fields,
        inherited_fields,
        python_filled_fields,
    )
    model_fields = set(row_fields) | set(top_level_fields)
    return [field for field in fields if field in model_fields]


def alias_for_index(index: int) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    if index < 0:
        raise ValueError("index must be non-negative")
    if index < 26 * 26:
        return alphabet[index // 26] + alphabet[index % 26]

    index -= 26 * 26
    return (
        alphabet[index // (26 * 26)]
        + alphabet[(index // 26) % 26]
        + alphabet[index % 26]
    )


def generate_alias_map(fields: list[str]) -> dict[str, str]:
    alias_map = {}
    alias_index = 0
    for field in fields:
        alias = alias_for_index(alias_index)
        while alias == ROOT_KEY_ALIAS:
            alias_index += 1
            alias = alias_for_index(alias_index)
        alias_map[field] = alias
        alias_index += 1
    return alias_map


def expand_alias_response(
    data: dict[str, Any],
    fields: list[str],
    root_key: str,
    alias_map: dict[str, str],
    root_alias: str = ROOT_KEY_ALIAS,
) -> dict[str, Any]:
    reverse_aliases = {alias: field for field, alias in alias_map.items()}
    expanded: dict[str, Any] = {}

    for field in fields:
        alias = alias_map.get(field)
        if alias is not None and alias in data:
            expanded[field] = data[alias]
        elif field in data:
            expanded[field] = data[field]

    rows = data.get(root_alias)
    if rows is None:
        rows = data.get(root_key) or data.get("transactions") or data.get("records") or []

    expanded_rows = []
    for row in rows:
        expanded_row = {}
        for key, value in row.items():
            expanded_row[reverse_aliases.get(key, key)] = value
        expanded_rows.append(expanded_row)

    expanded[root_key] = expanded_rows
    return expanded


def compact_alias_response(
    data: dict[str, Any],
    fields: list[str],
    root_key: str,
    alias_map: dict[str, str],
    root_alias: str = ROOT_KEY_ALIAS,
    inherited_fields: list[str] | None = None,
) -> dict[str, Any]:
    row_fields, _shared_fields, top_level_fields = split_model_fields(fields, inherited_fields)
    compact: dict[str, Any] = {}

    for field in top_level_fields:
        if field in alias_map and field in data and data[field] is not None:
            compact[alias_map[field]] = data[field]

    rows = data.get(root_key) or data.get("transactions") or data.get("records") or []
    compact[root_alias] = [
        {
            alias_map[field]: row.get(field)
            for field in row_fields
            if field in alias_map and row.get(field) is not None
        }
        for row in rows
    ]
    return compact


def extract_ollama_metadata(outer: dict[str, Any], response_text: str) -> dict[str, Any]:
    usage = {field: outer.get(field) for field in OLLAMA_USAGE_FIELDS if field in outer}
    metadata = {
        "model": outer.get("model"),
        "created_at": outer.get("created_at"),
        "done": outer.get("done"),
        "done_reason": outer.get("done_reason"),
        "response_chars": len(response_text),
    }
    if outer.get("thinking"):
        metadata["thinking_chars"] = len(outer["thinking"])
    metadata.update(usage)
    if usage.get("eval_count") and usage.get("eval_duration"):
        eval_seconds = usage["eval_duration"] / 1_000_000_000
        if eval_seconds > 0:
            metadata["eval_tokens_per_second"] = usage["eval_count"] / eval_seconds
    if usage.get("prompt_eval_count") and usage.get("prompt_eval_duration"):
        prompt_seconds = usage["prompt_eval_duration"] / 1_000_000_000
        if prompt_seconds > 0:
            metadata["prompt_tokens_per_second"] = usage["prompt_eval_count"] / prompt_seconds
    return metadata


def write_call_log(log_path: Path | None, entry: dict[str, Any]) -> None:
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def new_run_stats(file_count: int) -> dict[str, Any]:
    return {
        "file_count": file_count,
        "successful_files": 0,
        "failed_files": 0,
        "attempts": 0,
        "failed_attempts": 0,
        "records": 0,
        "attempt_elapsed_seconds": 0.0,
        "prompt_eval_count": 0,
        "eval_count": 0,
        "total_duration": 0,
        "load_duration": 0,
        "prompt_eval_duration": 0,
        "eval_duration": 0,
    }


def add_call_stats(
    stats: dict[str, Any],
    *,
    success: bool,
    records: int,
    elapsed_ns: int,
    ollama_metadata: dict[str, Any] | None = None,
) -> None:
    stats["attempts"] += 1
    stats["attempt_elapsed_seconds"] += elapsed_ns / 1_000_000_000
    if success:
        stats["records"] += records
    else:
        stats["failed_attempts"] += 1

    if not ollama_metadata:
        return
    for field in OLLAMA_USAGE_FIELDS:
        value = ollama_metadata.get(field)
        if isinstance(value, int | float):
            stats[field] += value


def format_seconds(seconds: float) -> str:
    return f"{seconds:.2f}s"


def build_run_summary(stats: dict[str, Any], wall_seconds: float) -> list[str]:
    lines = [
        f"Files: {stats['file_count']} total, {stats['successful_files']} succeeded, {stats['failed_files']} failed",
        f"Attempts: {stats['attempts']} total, {stats['failed_attempts']} failed",
        f"Records: {stats['records']}",
        f"Wall time: {format_seconds(wall_seconds)}",
        f"Attempt time: {format_seconds(stats['attempt_elapsed_seconds'])}",
    ]

    prompt_tokens = stats["prompt_eval_count"]
    eval_tokens = stats["eval_count"]
    if prompt_tokens or eval_tokens:
        lines.append(f"Ollama tokens: {prompt_tokens} prompt, {eval_tokens} generated")
    if stats["prompt_eval_duration"]:
        prompt_seconds = stats["prompt_eval_duration"] / 1_000_000_000
        lines.append(
            f"Ollama prompt eval: {format_seconds(prompt_seconds)}"
            f" ({prompt_tokens / prompt_seconds:.2f} tok/s)"
        )
    if stats["eval_duration"]:
        eval_seconds = stats["eval_duration"] / 1_000_000_000
        lines.append(
            f"Ollama generation: {format_seconds(eval_seconds)}"
            f" ({eval_tokens / eval_seconds:.2f} tok/s)"
        )
    if stats["total_duration"]:
        lines.append(f"Ollama total API duration: {format_seconds(stats['total_duration'] / 1_000_000_000)}")
    if stats["load_duration"]:
        lines.append(f"Ollama model load: {format_seconds(stats['load_duration'] / 1_000_000_000)}")
    return lines


def output_base_path(output: Path) -> Path:
    if output.is_absolute():
        return output
    if output.parts and output.parts[0] == "output":
        return output
    return Path("output") / output


def strip_known_output_suffix(path: Path) -> Path:
    name = path.name
    for suffix in (".compact.jsonl", ".ollama_calls.jsonl", ".jsonl", ".csv"):
        if name.endswith(suffix):
            return path.with_name(name[: -len(suffix)])
    return path


def derived_output_paths(output: Path) -> dict[str, Path]:
    base = strip_known_output_suffix(output_base_path(output))
    run_dir = base
    stem = run_dir.name
    return {
        "run_dir": run_dir,
        "csv": run_dir / f"{stem}.csv",
        "jsonl": run_dir / f"{stem}.jsonl",
        "compact_jsonl": run_dir / f"{stem}.compact.jsonl",
        "call_log_jsonl": run_dir / f"{stem}.ollama_calls.jsonl",
        "prompt_output_dir": run_dir / "prompts",
        "run_metadata": run_dir / DEFAULT_RUN_METADATA,
    }


def run_git_command(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return f"unavailable: {exc}"
    output = completed.stdout.strip()
    if completed.returncode != 0:
        error_text = completed.stderr.strip()
        return f"unavailable: {error_text or completed.returncode}"
    return output


def build_run_metadata(
    *,
    run_id: str,
    started_at: str,
    finished_at: str,
    status: str,
    command: list[str],
    input_dir: Path,
    output_csv: Path,
    output_jsonl: Path,
    output_compact_jsonl: Path | None,
    call_log_jsonl: Path | None,
    prompt_output_dir: Path | None,
    model: str,
    ollama_url: str,
    retries: int,
    temperature: float,
    num_ctx: int,
    timeout: int,
    think: bool,
    rules_file: Path | None,
    rows_written: int,
    run_stats: dict[str, Any],
) -> str:
    git_status = run_git_command(["status", "--short"])
    git_exact_tag = run_git_command(["describe", "--tags", "--exact-match"])
    if git_exact_tag.startswith("unavailable:"):
        git_exact_tag = "(none)"
    lines = [
        "parse-freetext run metadata",
        "",
        f"run_id: {run_id}",
        f"started_at_utc: {started_at}",
        f"finished_at_utc: {finished_at}",
        f"status: {status}",
        f"package_version: {__version__}",
        f"git_branch: {run_git_command(['rev-parse', '--abbrev-ref', 'HEAD'])}",
        f"git_commit: {run_git_command(['rev-parse', 'HEAD'])}",
        f"git_exact_tag: {git_exact_tag}",
        f"git_dirty: {'yes' if git_status else 'no'}",
        "",
        "command:",
        shlex.join(command),
        "",
        "settings:",
        f"input_dir: {input_dir}",
        f"rules_file: {rules_file}",
        f"model: {model}",
        f"ollama_url: {ollama_url}",
        f"retries: {retries}",
        f"temperature: {temperature}",
        f"num_ctx: {num_ctx}",
        f"timeout: {timeout}",
        f"think: {think}",
        "",
        "outputs:",
        f"csv: {output_csv}",
        f"jsonl: {output_jsonl}",
        f"compact_jsonl: {output_compact_jsonl}",
        f"call_log_jsonl: {call_log_jsonl}",
        f"prompts: {prompt_output_dir}",
        "",
        "summary:",
        f"rows_written: {rows_written}",
        f"files_total: {run_stats['file_count']}",
        f"files_successful: {run_stats['successful_files']}",
        f"files_failed: {run_stats['failed_files']}",
        f"attempts_total: {run_stats['attempts']}",
        f"attempts_failed: {run_stats['failed_attempts']}",
        "",
        "git_status_short:",
        git_status or "(clean)",
        "",
    ]
    return "\n".join(lines)


def rulebook_has_output_columns(rules_text: str | None) -> bool:
    if not rules_text:
        return False
    return any(OUTPUT_COLUMNS_HEADING_RE.match(line) for line in rules_text.splitlines())


def rulebook_structure_error(problems: list[str]) -> OllamaParseError:
    problem_lines = "\n".join(f"- {problem}" for problem in problems)
    return OllamaParseError(
        "Rulebook structural format warning:\n"
        f"{problem_lines}\n\n"
        f"{RULEBOOK_FORMAT_WALKTHROUGH}"
    )


def validate_rulebook_structure(rules_text: str | None) -> None:
    if not rules_text:
        return

    problems: list[str] = []
    output_fields: list[str] = []
    python_filled_fields: list[str] = []
    inherited_fields: list[str] = []
    current_section: str | None = None
    current_section_line = 0
    section_had_fields = False

    def close_section() -> None:
        nonlocal current_section, current_section_line, section_had_fields
        if current_section and not section_had_fields:
            problems.append(f"line {current_section_line}: {current_section} has no field bullets")
        current_section = None
        current_section_line = 0
        section_had_fields = False

    def start_section(section: str, line_number: int) -> None:
        nonlocal current_section, current_section_line, section_had_fields
        close_section()
        current_section = section
        current_section_line = line_number
        section_had_fields = False

    for line_number, line in enumerate(rules_text.splitlines(), start=1):
        if OUTPUT_COLUMNS_HEADING_RE.match(line):
            start_section("Output columns", line_number)
            continue
        if PYTHON_FILLED_FIELDS_HEADING_RE.match(line):
            start_section("Python-filled fields", line_number)
            continue
        if INHERITED_FIELDS_HEADING_RE.match(line):
            start_section("Inherited fields", line_number)
            continue

        if current_section is None:
            continue

        stripped = line.strip()
        if not stripped:
            if section_had_fields:
                close_section()
            continue
        if SECTION_HEADING_RE.match(line):
            close_section()
            continue

        match = FIELD_LINE_RE.match(line)
        if not match:
            problems.append(
                f"line {line_number}: malformed bullet in {current_section}: {stripped}"
            )
            continue

        name = match.group("name")
        if current_section == "Output columns":
            if name in output_fields:
                problems.append(f"line {line_number}: duplicate output column: {name}")
            output_fields.append(name)
        elif current_section == "Python-filled fields":
            python_filled_fields.append(name)
        elif current_section == "Inherited fields":
            inherited_fields.append(name)
        section_had_fields = True

    close_section()

    output_field_set = set(output_fields)
    if (python_filled_fields or inherited_fields) and not output_fields:
        problems.append("Python-filled or inherited fields require an Output columns section")
    for field in python_filled_fields:
        if field not in output_field_set:
            problems.append(f"Python-filled field is not an output column: {field}")
        if field not in PYTHON_FILLED_FIELD_NAMES:
            problems.append(f"Python cannot auto-fill this field name: {field}")
    for field in inherited_fields:
        if field not in output_field_set:
            problems.append(f"Inherited field is not an output column: {field}")
        if field in SHARED_CONTEXT_FIELDS:
            problems.append(f"Shared-only field cannot also be inherited: {field}")

    if problems:
        raise rulebook_structure_error(problems)


def parse_rulebook_columns(rules_text: str | None) -> tuple[list[str], dict[str, str]]:
    if not rules_text:
        return DEFAULT_FIELDS, DEFAULT_FIELD_TYPES.copy()

    validate_rulebook_structure(rules_text)

    lines = rules_text.splitlines()
    in_columns = False
    fields: list[str] = []
    field_types: dict[str, str] = {}

    for line in lines:
        if not in_columns:
            if OUTPUT_COLUMNS_HEADING_RE.match(line):
                in_columns = True
            continue

        stripped = line.strip()
        if not stripped:
            if fields:
                break
            continue
        if fields and SECTION_HEADING_RE.match(line):
            break

        match = FIELD_LINE_RE.match(line)
        if not match:
            continue

        name = match.group("name")
        if name in fields:
            raise OllamaParseError(f"Duplicate output column in rulebook: {name}")
        if not FIELD_NAME_RE.match(name):
            raise OllamaParseError(f"Invalid output column name in rulebook: {name}")

        field_type = (match.group("type") or DEFAULT_FIELD_TYPES.get(name) or "string").lower()
        if field_type not in SUPPORTED_FIELD_TYPES:
            raise OllamaParseError(f"Unsupported type for output column {name}: {field_type}")

        fields.append(name)
        field_types[name] = field_type

    if not fields:
        return DEFAULT_FIELDS, DEFAULT_FIELD_TYPES.copy()

    return fields, field_types


def parse_rulebook_inherited_fields(rules_text: str | None, fields: list[str]) -> list[str]:
    if not rules_text:
        return []

    inherited_fields: list[str] = []
    in_inherited_fields = False
    valid_fields = set(fields)

    for line in rules_text.splitlines():
        if not in_inherited_fields:
            if INHERITED_FIELDS_HEADING_RE.match(line):
                in_inherited_fields = True
            continue

        stripped = line.strip()
        if not stripped:
            if inherited_fields:
                break
            continue
        if inherited_fields and SECTION_HEADING_RE.match(line):
            break

        match = FIELD_LINE_RE.match(line)
        if not match:
            continue

        name = match.group("name")
        if name not in valid_fields:
            raise OllamaParseError(f"Inherited field is not an output column: {name}")
        if name in SHARED_CONTEXT_FIELDS:
            raise OllamaParseError(f"Shared-only field cannot also be inherited: {name}")
        if name not in inherited_fields:
            inherited_fields.append(name)

    return inherited_fields


def is_structural_rulebook_heading(line: str) -> bool:
    return bool(
        OUTPUT_COLUMNS_HEADING_RE.match(line)
        or PYTHON_FILLED_FIELDS_HEADING_RE.match(line)
        or INHERITED_FIELDS_HEADING_RE.match(line)
    )


def strip_rulebook_structural_sections(rules_text: str | None) -> str | None:
    if not rules_text:
        return None

    kept_lines: list[str] = []
    skipping = False

    for line in rules_text.splitlines():
        if is_structural_rulebook_heading(line):
            skipping = True
            continue
        if skipping and SECTION_HEADING_RE.match(line):
            skipping = False
        if not skipping:
            kept_lines.append(line)

    stripped = "\n".join(kept_lines).strip()
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped or None


def json_schema_type(field_type: str) -> dict[str, Any]:
    if field_type == "boolean":
        return {"type": "boolean"}
    if field_type == "integer":
        return {"type": "integer"}
    if field_type == "number":
        return {"type": "number"}
    return {"type": "string"}


def build_schema(
    fields: list[str],
    field_types: dict[str, str],
    root_key: str,
    alias_map: dict[str, str] | None = None,
    root_alias: str = ROOT_KEY_ALIAS,
    inherited_fields: list[str] | None = None,
) -> dict[str, Any]:
    alias_map = alias_map or generate_alias_map(model_alias_fields(fields, inherited_fields))
    row_fields, _shared_fields, top_level_fields = split_model_fields(fields, inherited_fields)
    properties = {
        alias_map[field]: json_schema_type(field_types.get(field, DEFAULT_FIELD_TYPES.get(field, "string")))
        for field in row_fields
        if field in alias_map
    }
    if "quality_of_parsing" in row_fields:
        properties[alias_map["quality_of_parsing"]] = {
            "type": "string",
            "enum": ["high", "medium", "low"],
        }

    schema = {
        "type": "object",
        "properties": {
            root_alias: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": [],
                    "additionalProperties": False,
                },
            }
        },
        "required": [root_alias],
        "additionalProperties": False,
    }
    for field in top_level_fields:
        if field not in alias_map:
            continue
        schema["properties"][alias_map[field]] = json_schema_type(
            field_types.get(field, DEFAULT_FIELD_TYPES.get(field, "string"))
        )

    return schema


SCHEMA = build_schema(DEFAULT_FIELDS, DEFAULT_FIELD_TYPES, "records")


def aliases_for(fields: list[str], alias_map: dict[str, str]) -> str:
    return ", ".join(
        f"{alias_map[field]}={field}"
        for field in fields
        if field in alias_map
    )


def build_json_shape_block(
    fields: list[str],
    alias_map: dict[str, str],
    root_alias: str,
    inherited_fields: list[str],
) -> str:
    python_filled_fields = infer_python_filled_fields(fields)
    row_fields, shared_fields, _top_level_fields = split_model_fields(fields, inherited_fields)
    row_only_fields = [field for field in row_fields if field not in inherited_fields]

    lines = [
        "JSON shape:",
        f"- Return only JSON. Use compact aliases only. Rows key: {root_alias}.",
        "- Omit unknown fields.",
    ]
    if python_filled_fields:
        lines.append(f"- Python fills; do not output: {', '.join(python_filled_fields)}.")
    if shared_fields:
        lines.append(f"- Top-level only: {aliases_for(shared_fields, alias_map)}.")
    if inherited_fields:
        lines.append(
            f"- Inherited: {aliases_for(inherited_fields, alias_map)}. "
            "Put once top-level when shared; row overrides allowed."
        )
    lines.append(f"- Row fields: {aliases_for(row_only_fields, alias_map)}.")
    lines.append("- Free-text detail fields must not repeat context, inherited values, or dedicated field values.")
    return "\n".join(lines)


def build_prompt(
    filename: str,
    text: str,
    rules_text: str | None = None,
    fields: list[str] | None = None,
    root_key: str | None = None,
    rulebook_declares_columns: bool = False,
    alias_map: dict[str, str] | None = None,
    root_alias: str = ROOT_KEY_ALIAS,
    inherited_fields: list[str] | None = None,
) -> str:
    transaction_id_parent = Path(filename).stem
    fields = fields or DEFAULT_FIELDS
    root_key = root_key or root_key_for_fields(fields)
    python_filled_fields = infer_python_filled_fields(fields)
    _row_fields, shared_fields, _top_level_fields = split_model_fields(fields, inherited_fields)
    inherited_fields = inherited_fields or []
    alias_map = alias_map or generate_alias_map(
        model_alias_fields(fields, inherited_fields, python_filled_fields)
    )
    json_shape_block = build_json_shape_block(fields, alias_map, root_alias, inherited_fields)
    final_columns_section = ""
    if not rulebook_declares_columns:
        final_columns_section = "Final columns: " + ", ".join(fields) + "\n\n"

    prompt_rules_text = strip_rulebook_structural_sections(rules_text)
    rulebook_section = ""
    if prompt_rules_text:
        rulebook_section = f"""

Domain rules:
<<<
{prompt_rules_text}
>>>
"""

    return f"""
Extract structured rows from the free text.
Filename: {filename}
{final_columns_section}{json_shape_block}
{rulebook_section}

Free text:
<<<
{text}
>>>
""".strip()


def call_ollama(
    prompt: str,
    model: str,
    *,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    temperature: float = 0.0,
    num_ctx: int = 8192,
    timeout: int = 300,
    think: bool = False,
    schema: dict[str, Any] | None = None,
    return_metadata: bool = False,
) -> dict[str, Any] | tuple[dict[str, Any], dict[str, Any]]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "format": schema or SCHEMA,
        "options": {
            "temperature": temperature,
            "num_ctx": num_ctx,
        },
    }

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        ollama_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            outer = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise OllamaParseError(f"Ollama returned HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise OllamaParseError(f"Could not connect to Ollama at {ollama_url}: {exc}") from exc

    response_text = outer.get("response", "")
    metadata = extract_ollama_metadata(outer, response_text)

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", response_text, flags=re.S)
        if not match:
            details = [f"response={response_text[:1000]!r}"]
            if outer.get("thinking"):
                details.append(f"thinking={outer['thinking'][:1000]!r}")
            if outer.get("done_reason"):
                details.append(f"done_reason={outer['done_reason']!r}")
            raise OllamaParseError(
                "No JSON object found in Ollama response:\n" + "\n".join(details)
            )
        parsed = json.loads(match.group(0))

    if return_metadata:
        return parsed, metadata
    return parsed


def load_rules_file(rules_file: Path | None) -> str | None:
    if rules_file is None:
        return None
    if not rules_file.exists():
        if rules_file == DEFAULT_RULES_FILE:
            return None
        raise OllamaParseError(f"Rules file does not exist: {rules_file}")
    if not rules_file.is_file():
        raise OllamaParseError(f"Rules path is not a file: {rules_file}")
    return rules_file.read_text(encoding="utf-8", errors="replace")


def remove_redundant_detail(clean: dict[str, Any]) -> None:
    detail = clean.get("transaction_details")
    direction = clean.get("direction")
    if not isinstance(detail, str) or not isinstance(direction, str):
        return

    normalized_detail = re.sub(r"[^a-z]+", " ", detail.lower()).strip()
    normalized_direction = direction.lower().strip()
    redundant_details = {
        normalized_direction,
        f"{normalized_direction} transfer",
        f"{normalized_direction} transaction",
        f"{normalized_direction} payment",
    }
    if normalized_detail in redundant_details:
        clean["transaction_details"] = None


def is_missing_value(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def normalize_records(
    data: dict[str, Any],
    transaction_id_parent: str,
    fields: list[str] | None = None,
    root_key: str = "records",
    inherited_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    fields = fields or DEFAULT_FIELDS
    _row_fields, shared_fields, top_level_fields = split_model_fields(fields, inherited_fields)
    inherited_fields = inherited_fields or []
    rows = data.get(root_key) or data.get("transactions") or data.get("records") or []
    top_level_values = {field: data.get(field) for field in top_level_fields}
    clean_rows = []

    for i, row in enumerate(rows, start=1):
        clean = {}
        for field in fields:
            if field in shared_fields:
                clean[field] = top_level_values.get(field)
            elif field in inherited_fields:
                row_value = row.get(field)
                clean[field] = top_level_values.get(field) if is_missing_value(row_value) else row_value
            else:
                clean[field] = row.get(field)
        for parent_field in ("transaction_id_parent", "parent_id", "record_id", "source_id"):
            if parent_field in clean:
                clean[parent_field] = transaction_id_parent
        for index_field in ("sub_id", "row_id", "row_number", "item_index"):
            if index_field in clean:
                clean[index_field] = i

        for key, value in clean.items():
            if is_missing_value(value):
                clean[key] = None

        remove_redundant_detail(clean)
        clean_rows.append(clean)

    return clean_rows


def write_prompt_files(
    input_dir: Path,
    output_dir: Path,
    rules_file: Path | None = DEFAULT_RULES_FILE,
) -> int:
    if not input_dir.exists():
        raise OllamaParseError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise OllamaParseError(f"Input path is not a directory: {input_dir}")

    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        raise OllamaParseError(f"No .txt files found in {input_dir}")

    rules_text = load_rules_file(rules_file)
    fields, _field_types = parse_rulebook_columns(rules_text)
    inherited_fields = parse_rulebook_inherited_fields(rules_text, fields)
    root_key = root_key_for_fields(fields)
    alias_map = generate_alias_map(model_alias_fields(fields, inherited_fields))
    rulebook_declares_columns = rulebook_has_output_columns(rules_text)
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in txt_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        prompt = build_prompt(
            path.name,
            text,
            rules_text,
            fields,
            root_key,
            rulebook_declares_columns,
            alias_map,
            ROOT_KEY_ALIAS,
            inherited_fields=inherited_fields,
        )
        (output_dir / f"{path.stem}_prompt.txt").write_text(prompt + "\n", encoding="utf-8")

    return len(txt_files)


def process_folder(
    input_dir: Path,
    output_csv: Path,
    output_jsonl: Path,
    model: str,
    *,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    retries: int = 2,
    temperature: float = 0.0,
    num_ctx: int = 8192,
    timeout: int = 300,
    prompt_output_dir: Path | None = None,
    think: bool = False,
    rules_file: Path | None = DEFAULT_RULES_FILE,
    output_compact_jsonl: Path | None = None,
    call_log_jsonl: Path | None = DEFAULT_CALL_LOG_JSONL,
    run_metadata: Path | None = None,
    command: list[str] | None = None,
) -> int:
    if not input_dir.exists():
        raise OllamaParseError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise OllamaParseError(f"Input path is not a directory: {input_dir}")

    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        raise OllamaParseError(f"No .txt files found in {input_dir}")

    rules_text = load_rules_file(rules_file)
    fields, field_types = parse_rulebook_columns(rules_text)
    inherited_fields = parse_rulebook_inherited_fields(rules_text, fields)
    root_key = root_key_for_fields(fields)
    alias_map = generate_alias_map(model_alias_fields(fields, inherited_fields))
    schema = build_schema(
        fields,
        field_types,
        root_key,
        alias_map,
        ROOT_KEY_ALIAS,
        inherited_fields,
    )
    rulebook_declares_columns = rulebook_has_output_columns(rules_text)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if output_compact_jsonl is not None:
        output_compact_jsonl.parent.mkdir(parents=True, exist_ok=True)
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    if call_log_jsonl is not None:
        call_log_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if prompt_output_dir is not None:
        prompt_output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []
    process_started = time.perf_counter_ns()
    run_stats = new_run_stats(len(txt_files))

    compact_file = (
        output_compact_jsonl.open("w", encoding="utf-8")
        if output_compact_jsonl is not None
        else None
    )
    try:
        with output_jsonl.open("w", encoding="utf-8") as jf:
            for path in txt_files:
                transaction_id_parent = path.stem
                text = path.read_text(encoding="utf-8", errors="replace")
                prompt = build_prompt(
                    path.name,
                    text,
                    rules_text,
                    fields,
                    root_key,
                    rulebook_declares_columns,
                    alias_map,
                    ROOT_KEY_ALIAS,
                    inherited_fields,
                )
                if prompt_output_dir is not None:
                    prompt_file = prompt_output_dir / f"{transaction_id_parent}_prompt.txt"
                    prompt_file.write_text(prompt + "\n", encoding="utf-8")

                print(f"Processing {path.name} ...")

                last_error: Exception | None = None
                for attempt in range(1, retries + 2):
                    attempt_started = time.perf_counter_ns()
                    try:
                        call_result = call_ollama(
                            prompt=prompt,
                            model=model,
                            ollama_url=ollama_url,
                            temperature=temperature,
                            num_ctx=num_ctx,
                            timeout=timeout,
                            think=think,
                            schema=schema,
                            return_metadata=True,
                        )
                        if isinstance(call_result, tuple):
                            compact_data, call_metadata = call_result
                        else:
                            compact_data = call_result
                            call_metadata = {}
                        data = expand_alias_response(
                            compact_data,
                            fields,
                            root_key,
                            alias_map,
                            ROOT_KEY_ALIAS,
                        )
                        if compact_file is not None:
                            compact_file.write(
                                json.dumps(compact_data, ensure_ascii=False) + "\n"
                            )
                        rows = normalize_records(
                            data,
                            transaction_id_parent,
                            fields,
                            root_key,
                            inherited_fields,
                        )

                        for row in rows:
                            jf.write(json.dumps(row, ensure_ascii=False) + "\n")

                        elapsed_ns = time.perf_counter_ns() - attempt_started
                        compact_response_chars = len(json.dumps(compact_data, ensure_ascii=False))
                        add_call_stats(
                            run_stats,
                            success=True,
                            records=len(rows),
                            elapsed_ns=elapsed_ns,
                            ollama_metadata=call_metadata,
                        )
                        write_call_log(
                            call_log_jsonl,
                            {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "run_id": run_id,
                                "input_file": path.name,
                                "attempt": attempt,
                                "success": True,
                                "model": model,
                                "ollama_url": ollama_url,
                                "temperature": temperature,
                                "num_ctx": num_ctx,
                                "timeout": timeout,
                                "think": think,
                                "prompt_chars": len(prompt),
                                "schema_chars": len(json.dumps(schema, ensure_ascii=False)),
                                "compact_response_chars": compact_response_chars,
                                "records_extracted": len(rows),
                                "elapsed_ns": elapsed_ns,
                                "elapsed_seconds": elapsed_ns / 1_000_000_000,
                                "root_alias": ROOT_KEY_ALIAS,
                                "field_count": len(fields),
                                "ollama": call_metadata,
                            },
                        )
                        all_rows.extend(rows)
                        run_stats["successful_files"] += 1
                        print(f"  extracted {len(rows)} record(s)")
                        break

                    except Exception as exc:
                        last_error = exc
                        elapsed_ns = time.perf_counter_ns() - attempt_started
                        add_call_stats(
                            run_stats,
                            success=False,
                            records=0,
                            elapsed_ns=elapsed_ns,
                        )
                        write_call_log(
                            call_log_jsonl,
                            {
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "run_id": run_id,
                                "input_file": path.name,
                                "attempt": attempt,
                                "success": False,
                                "model": model,
                                "ollama_url": ollama_url,
                                "temperature": temperature,
                                "num_ctx": num_ctx,
                                "timeout": timeout,
                                "think": think,
                                "prompt_chars": len(prompt),
                                "schema_chars": len(json.dumps(schema, ensure_ascii=False)),
                                "elapsed_ns": elapsed_ns,
                                "elapsed_seconds": elapsed_ns / 1_000_000_000,
                                "root_alias": ROOT_KEY_ALIAS,
                                "field_count": len(fields),
                                "error": str(exc),
                            },
                        )
                        print(f"  attempt {attempt} failed: {exc}")
                        if attempt <= retries:
                            time.sleep(1)

                else:
                    print(f"  FAILED: {path.name}")
                    run_stats["failed_files"] += 1
                    fail_row = {field: None for field in fields}
                    for parent_field in ("transaction_id_parent", "parent_id", "record_id", "source_id"):
                        if parent_field in fail_row:
                            fail_row[parent_field] = transaction_id_parent
                    for index_field in ("sub_id", "row_id", "row_number", "item_index"):
                        if index_field in fail_row:
                            fail_row[index_field] = 1
                    if "quality_of_parsing" in fail_row:
                        fail_row["quality_of_parsing"] = "low"
                    detail_field = "transaction_details" if "transaction_details" in fail_row else None
                    if detail_field is None:
                        detail_field = "details" if "details" in fail_row else None
                    if detail_field is None:
                        detail_field = "notes" if "notes" in fail_row else None
                    if detail_field is not None:
                        fail_row[detail_field] = f"PARSING_FAILED: {last_error}"
                    all_rows.append(fail_row)
                    jf.write(json.dumps(fail_row, ensure_ascii=False) + "\n")
    finally:
        if compact_file is not None:
            compact_file.close()

    with output_csv.open("w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=fields, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(all_rows)

    if run_metadata is not None:
        run_metadata.parent.mkdir(parents=True, exist_ok=True)
        run_metadata.write_text(
            build_run_metadata(
                run_id=run_id,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc).isoformat(),
                status="completed",
                command=command or sys.argv,
                input_dir=input_dir,
                output_csv=output_csv,
                output_jsonl=output_jsonl,
                output_compact_jsonl=output_compact_jsonl,
                call_log_jsonl=call_log_jsonl,
                prompt_output_dir=prompt_output_dir,
                model=model,
                ollama_url=ollama_url,
                retries=retries,
                temperature=temperature,
                num_ctx=num_ctx,
                timeout=timeout,
                think=think,
                rules_file=rules_file,
                rows_written=len(all_rows),
                run_stats=run_stats,
            ),
            encoding="utf-8",
        )

    print()
    print("Done.")
    print("Summary:")
    for summary_line in build_run_summary(
        run_stats,
        (time.perf_counter_ns() - process_started) / 1_000_000_000,
    ):
        print(f"  {summary_line}")
    print(f"CSV:   {output_csv}")
    print(f"JSONL: {output_jsonl}")
    if output_compact_jsonl is not None:
        print(f"Compact JSONL: {output_compact_jsonl}")
    if call_log_jsonl is not None:
        print(f"Call log: {call_log_jsonl}")
    if prompt_output_dir is not None:
        print(f"Prompts: {prompt_output_dir}")
    if run_metadata is not None:
        print(f"Run metadata: {run_metadata}")
    return len(all_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parse-freetext-ollama",
        description="Parse prepared text input files into structured records with Ollama.",
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        help="Prepared text input folder containing {id}.txt files.",
    )
    parser.add_argument(
        "--input-dir",
        "--input_dir",
        dest="input_dir_flag",
        type=Path,
        help="Prepared text input folder containing {id}.txt files.",
    )
    parser.add_argument("--model", default="qwen2.5:14b", help="Ollama model name.")
    parser.add_argument(
        "--ollama-url",
        default=DEFAULT_OLLAMA_URL,
        help=f"Ollama generate endpoint. Default: {DEFAULT_OLLAMA_URL}",
    )
    parser.add_argument(
        "--output",
        "--output-name",
        "--output_name",
        dest="output",
        type=Path,
        help=(
            "Base run folder name or path. Relative values are written under output/. "
            "Derives CSV, JSONL, compact JSONL, call log, prompt, and metadata paths inside it."
        ),
    )
    parser.add_argument(
        "--output-csv",
        "--output_csv",
        type=Path,
        help="Override CSV output path.",
    )
    parser.add_argument(
        "--output-jsonl",
        "--output_jsonl",
        type=Path,
        help="Override JSONL output path.",
    )
    parser.add_argument(
        "--output-compact-jsonl",
        "--output_compact_jsonl",
        type=Path,
        help="Override compact alias-shaped JSONL output path.",
    )
    parser.add_argument(
        "--call-log-jsonl",
        "--call_log_jsonl",
        type=Path,
        help="Override Ollama call log JSONL path.",
    )
    parser.add_argument(
        "--run-metadata",
        "--run_metadata",
        type=Path,
        help="Override run metadata text file path.",
    )
    parser.add_argument(
        "--no-call-log",
        action="store_true",
        help="Disable Ollama call logging.",
    )
    parser.add_argument("--retries", type=int, default=2, help="Retries per text file.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Ollama temperature.")
    parser.add_argument("--num-ctx", type=int, default=8192, help="Ollama context window.")
    parser.add_argument("--timeout", type=int, default=300, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--rules-file",
        "--rules_file",
        type=Path,
        default=DEFAULT_RULES_FILE,
        help=f"Optional local extraction rulebook. Default: {DEFAULT_RULES_FILE}",
    )
    parser.add_argument(
        "--think",
        action="store_true",
        help="Enable Ollama thinking mode. Defaults to off for structured extraction.",
    )
    parser.add_argument(
        "--prompt-output-dir",
        "--prompt_output_dir",
        type=Path,
        help=(
            "Write ready-to-submit prompt .txt files to this folder. "
            "Defaults to a folder inside the output run folder during extraction, "
            f"or {DEFAULT_PROMPT_OUTPUT_DIR} with --prompts-only."
        ),
    )
    parser.add_argument(
        "--prompts-only",
        action="store_true",
        help="Write prompt .txt files and skip the Ollama API call.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    input_dir = args.input_dir_flag or args.input_dir
    if input_dir is None:
        parser.error("input_dir is required")
    outputs = derived_output_paths(args.output or Path(DEFAULT_OUTPUT_BASENAME))
    prompt_output_dir = args.prompt_output_dir
    if prompt_output_dir is None:
        if args.prompts_only and args.output is None:
            prompt_output_dir = DEFAULT_PROMPT_OUTPUT_DIR
        else:
            prompt_output_dir = outputs["prompt_output_dir"]
    output_csv = args.output_csv or outputs["csv"]
    output_jsonl = args.output_jsonl or outputs["jsonl"]
    output_compact_jsonl = args.output_compact_jsonl or (
        outputs["compact_jsonl"] if args.output is not None else None
    )
    default_call_log_jsonl = outputs["call_log_jsonl"]
    call_log_jsonl = None if args.no_call_log else (args.call_log_jsonl or default_call_log_jsonl)
    run_metadata = args.run_metadata or outputs["run_metadata"]

    try:
        if args.prompts_only:
            count = write_prompt_files(input_dir, prompt_output_dir, args.rules_file)
            print(f"Wrote {count} prompt file(s) to {prompt_output_dir}")
        else:
            process_folder(
                input_dir=input_dir,
                output_csv=output_csv,
                output_jsonl=output_jsonl,
                model=args.model,
                ollama_url=args.ollama_url,
                retries=args.retries,
                temperature=args.temperature,
                num_ctx=args.num_ctx,
                timeout=args.timeout,
                prompt_output_dir=prompt_output_dir,
                think=args.think,
                rules_file=args.rules_file,
                output_compact_jsonl=output_compact_jsonl,
                call_log_jsonl=call_log_jsonl,
                run_metadata=run_metadata,
                command=["parse-freetext-ollama", *(argv if argv is not None else sys.argv[1:])],
            )
    except OllamaParseError as exc:
        message = str(exc)
        if message.startswith("Rulebook structural format warning:"):
            print(message)
        else:
            print(f"error: {exc}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
