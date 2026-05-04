import csv
import json
from pathlib import Path

from parse_freetext import ollama_parser
from parse_freetext.ollama_parser import (
    build_prompt,
    call_ollama,
    normalize_records,
    process_folder,
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


def test_normalize_records_sets_parent_and_sub_ids() -> None:
    data = {
        "transactions": [
            {
                "transaction_id_parent": "wrong",
                "sub_id": 99,
                "secondary_party": "Partij A",
                "value": 100,
                "currency": "EUR",
                "eur_equivalent": "",
                "quality_of_parsing": "high",
                "transaction_date": "",
                "bank_details": None,
                "account_details": None,
                "transaction_details": "outgoing",
            }
        ]
    }

    rows = normalize_records(data, "1")

    assert rows[0]["transaction_id_parent"] == "1"
    assert rows[0]["sub_id"] == 1
    assert rows[0]["eur_equivalent"] is None
    assert rows[0]["transaction_date"] is None


def test_process_folder_writes_csv_and_jsonl(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_dir = tmp_path / "texts"
    input_dir.mkdir()
    (input_dir / "1.txt").write_text("Client pays Partij A EUR 100", encoding="utf-8")

    def fake_call_ollama(**kwargs):
        return {
            "transactions": [
                {
                    "transaction_id_parent": "1",
                    "sub_id": 1,
                    "secondary_party": "Partij A",
                    "value": 100,
                    "currency": "EUR",
                    "eur_equivalent": 100,
                    "quality_of_parsing": "high",
                    "transaction_date": None,
                    "bank_details": None,
                    "account_details": None,
                    "transaction_details": "outgoing payment",
                }
            ]
        }

    monkeypatch.setattr(ollama_parser, "call_ollama", fake_call_ollama)

    output_csv = tmp_path / "out" / "transactions.csv"
    output_jsonl = tmp_path / "out" / "transactions.jsonl"
    prompt_dir = tmp_path / "prompts"
    count = process_folder(
        input_dir,
        output_csv,
        output_jsonl,
        "test-model",
        prompt_output_dir=prompt_dir,
    )

    assert count == 1
    with output_csv.open(encoding="utf-8", newline="") as csv_file:
        csv_rows = list(csv.DictReader(csv_file))
    assert csv_rows[0]["secondary_party"] == "Partij A"
    assert csv_rows[0]["value"] == "100"

    jsonl_rows = [
        json.loads(line)
        for line in output_jsonl.read_text(encoding="utf-8").splitlines()
    ]
    assert jsonl_rows[0]["currency"] == "EUR"
    assert (prompt_dir / "1_prompt.txt").exists()


def test_call_ollama_disables_thinking_by_default(monkeypatch) -> None:
    captured_payload = {}

    def fake_urlopen(req, timeout):
        captured_payload.update(json.loads(req.data.decode("utf-8")))
        return FakeResponse({"response": '{"transactions": []}'})

    monkeypatch.setattr(ollama_parser.request, "urlopen", fake_urlopen)

    assert call_ollama("prompt", "qwen3.5:9b") == {"transactions": []}
    assert captured_payload["think"] is False


def test_build_prompt_omits_rules_without_rulebook() -> None:
    prompt = build_prompt("TX-001.txt", "Client receives EUR 50")

    assert "User-provided extraction rulebook" not in prompt
    assert "Local rule" not in prompt


def test_build_prompt_includes_rules_from_rulebook() -> None:
    prompt = build_prompt("TX-001.txt", "Client receives EUR 50", "Local rule")

    assert "User-provided extraction rulebook" in prompt
    assert "Local rule" in prompt


def test_write_prompt_files_without_calling_model(tmp_path: Path) -> None:
    input_dir = tmp_path / "texts"
    output_dir = tmp_path / "prompts"
    input_dir.mkdir()
    (input_dir / "TX-001.txt").write_text("Client receives EUR 50", encoding="utf-8")

    count = write_prompt_files(input_dir, output_dir, rules_file=None)

    prompt = (output_dir / "TX-001_prompt.txt").read_text(encoding="utf-8")
    assert count == 1
    assert "Return ONLY JSON matching the provided schema." in prompt
    assert "Client receives EUR 50" in prompt
