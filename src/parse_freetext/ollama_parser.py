from __future__ import annotations

import argparse
import csv
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_RULES_FILE = Path("rules/ollama_rulebook.txt")

FIELDS = [
    "transaction_id_parent",
    "sub_id",
    "secondary_party",
    "value",
    "currency",
    "eur_equivalent",
    "quality_of_parsing",
    "transaction_date",
    "bank_details",
    "account_details",
    "transaction_details",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "transaction_id_parent": {"type": "string"},
                    "sub_id": {"type": "integer"},
                    "secondary_party": {"type": ["string", "null"]},
                    "value": {"type": ["number", "null"]},
                    "currency": {"type": ["string", "null"]},
                    "eur_equivalent": {"type": ["number", "null"]},
                    "quality_of_parsing": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                    },
                    "transaction_date": {"type": ["string", "null"]},
                    "bank_details": {"type": ["string", "null"]},
                    "account_details": {"type": ["string", "null"]},
                    "transaction_details": {"type": ["string", "null"]},
                },
                "required": FIELDS,
            },
        }
    },
    "required": ["transactions"],
}


class OllamaParseError(RuntimeError):
    """Raised when text parsing through Ollama cannot complete."""


def build_prompt(filename: str, text: str, rules_text: str | None = None) -> str:
    transaction_id_parent = Path(filename).stem
    rulebook_section = ""
    if rules_text and rules_text.strip():
        rulebook_section = f"""

User-provided extraction rulebook:
<<<
{rules_text.strip()}
>>>
"""

    return f"""
You are a careful AML/KYC transaction extraction engine.

Extract every individual transaction mentioned in the free text.

The filename is:
{filename}

The transaction_id_parent is:
{transaction_id_parent}

Return ONLY JSON matching the provided schema.
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
) -> dict[str, Any]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": think,
        "format": SCHEMA,
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

    try:
        return json.loads(response_text)
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
        return json.loads(match.group(0))


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


def normalize_records(data: dict[str, Any], transaction_id_parent: str) -> list[dict[str, Any]]:
    rows = data.get("transactions", [])
    clean_rows = []

    for i, row in enumerate(rows, start=1):
        clean = {field: row.get(field) for field in FIELDS}
        clean["transaction_id_parent"] = transaction_id_parent
        clean["sub_id"] = i

        for key, value in clean.items():
            if isinstance(value, str) and value.strip() == "":
                clean[key] = None

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
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in txt_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        prompt = build_prompt(path.name, text, rules_text)
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
) -> int:
    if not input_dir.exists():
        raise OllamaParseError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise OllamaParseError(f"Input path is not a directory: {input_dir}")

    txt_files = sorted(input_dir.glob("*.txt"))
    if not txt_files:
        raise OllamaParseError(f"No .txt files found in {input_dir}")

    rules_text = load_rules_file(rules_file)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    if prompt_output_dir is not None:
        prompt_output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []

    with output_jsonl.open("w", encoding="utf-8") as jf:
        for path in txt_files:
            transaction_id_parent = path.stem
            text = path.read_text(encoding="utf-8", errors="replace")
            prompt = build_prompt(path.name, text, rules_text)
            if prompt_output_dir is not None:
                prompt_file = prompt_output_dir / f"{transaction_id_parent}_prompt.txt"
                prompt_file.write_text(prompt + "\n", encoding="utf-8")

            print(f"Processing {path.name} ...")

            last_error: Exception | None = None
            for attempt in range(1, retries + 2):
                try:
                    data = call_ollama(
                        prompt=prompt,
                        model=model,
                        ollama_url=ollama_url,
                        temperature=temperature,
                        num_ctx=num_ctx,
                        timeout=timeout,
                        think=think,
                    )
                    rows = normalize_records(data, transaction_id_parent)

                    for row in rows:
                        jf.write(json.dumps(row, ensure_ascii=False) + "\n")

                    all_rows.extend(rows)
                    print(f"  extracted {len(rows)} transaction(s)")
                    break

                except Exception as exc:
                    last_error = exc
                    print(f"  attempt {attempt} failed: {exc}")
                    if attempt <= retries:
                        time.sleep(1)

            else:
                print(f"  FAILED: {path.name}")
                fail_row = {field: None for field in FIELDS}
                fail_row["transaction_id_parent"] = transaction_id_parent
                fail_row["sub_id"] = 1
                fail_row["quality_of_parsing"] = "low"
                fail_row["transaction_details"] = f"PARSING_FAILED: {last_error}"
                all_rows.append(fail_row)
                jf.write(json.dumps(fail_row, ensure_ascii=False) + "\n")

    with output_csv.open("w", encoding="utf-8", newline="") as cf:
        writer = csv.DictWriter(cf, fieldnames=FIELDS, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(all_rows)

    print()
    print("Done.")
    print(f"CSV:   {output_csv}")
    print(f"JSONL: {output_jsonl}")
    if prompt_output_dir is not None:
        print(f"Prompts: {prompt_output_dir}")
    return len(all_rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="parse-freetext-ollama",
        description="Parse extracted text files into structured transactions with Ollama.",
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        type=Path,
        help="Folder containing extracted *.txt files.",
    )
    parser.add_argument(
        "--input-dir",
        "--input_dir",
        dest="input_dir_flag",
        type=Path,
        help="Folder containing extracted *.txt files.",
    )
    parser.add_argument("--model", default="qwen2.5:14b", help="Ollama model name.")
    parser.add_argument(
        "--ollama-url",
        default=DEFAULT_OLLAMA_URL,
        help=f"Ollama generate endpoint. Default: {DEFAULT_OLLAMA_URL}",
    )
    parser.add_argument(
        "--output-csv",
        "--output_csv",
        type=Path,
        default=Path("output/transactions_extracted.csv"),
        help="CSV output path. Default: output/transactions_extracted.csv",
    )
    parser.add_argument(
        "--output-jsonl",
        "--output_jsonl",
        type=Path,
        default=Path("output/transactions_extracted.jsonl"),
        help="JSONL output path. Default: output/transactions_extracted.jsonl",
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
        help="Write ready-to-submit prompt .txt files to this folder.",
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
    if args.prompts_only and args.prompt_output_dir is None:
        parser.error("--prompts-only requires --prompt-output-dir")

    try:
        if args.prompts_only:
            count = write_prompt_files(input_dir, args.prompt_output_dir, args.rules_file)
            print(f"Wrote {count} prompt file(s) to {args.prompt_output_dir}")
        else:
            process_folder(
                input_dir=input_dir,
                output_csv=args.output_csv,
                output_jsonl=args.output_jsonl,
                model=args.model,
                ollama_url=args.ollama_url,
                retries=args.retries,
                temperature=args.temperature,
                num_ctx=args.num_ctx,
                timeout=args.timeout,
                prompt_output_dir=args.prompt_output_dir,
                think=args.think,
                rules_file=args.rules_file,
            )
    except OllamaParseError as exc:
        print(f"error: {exc}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
