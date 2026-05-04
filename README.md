# parse-freetext

`parse-freetext` is a Python CLI toolkit for turning spreadsheet free-text fields into plain text files, ready-to-submit prompts, and structured transaction records.

It is designed for repeatable local workflows:

1. Inspect an `.xlsx` workbook to find sheet names and headers.
2. Extract selected free-text columns into `{transaction_id}.txt` files.
3. Generate prompt files for manual submission to cloud model services.
4. Optionally parse those text files through a local Ollama model into CSV and JSONL.

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

For development and tests:

```bash
uv sync --extra dev
```

## CLI Commands

The package installs two commands:

```bash
uv run parse-freetext --help
uv run parse-freetext-ollama --help
```

## Inspect A Workbook

Use `--inspect` to print worksheet tabs and first-row headers before choosing extraction flags:

```bash
uv run parse-freetext examples/sample_transactions.xlsx --inspect
```

Example output:

```text
Transactions: Transaction ID, Notes, Description
Archive: Transaction ID, Notes, Description
```

## Extract Free Text From Excel

Extract `Notes` and `Description` from selected sheets, using `Transaction ID` for output filenames:

```bash
uv run parse-freetext examples/sample_transactions.xlsx \
  --sheet Transactions \
  --sheet Archive \
  --transaction-id-column "Transaction ID" \
  --text-column Notes \
  --text-column Description \
  --output-dir output/texts
```

This creates files such as:

```text
output/texts/TX-001.txt
output/texts/TX-002.txt
```

Column references can be:

- Header names: `--transaction-id-column "Transaction ID"`
- Excel letters: `--text-column C`
- 1-based numbers: `--text-column 3`

Useful extraction options:

- `--sheet`: worksheet tab to process. Repeat it for multiple tabs. If omitted, all sheets are processed.
- `--text-column`: free-text column to extract. Repeat it to combine multiple columns into one text file.
- `--output-dir`: output folder. Defaults to `output/texts`.
- `--overwrite`: replace existing output files.
- `--append-sheet-name`: append the sheet name to filenames to avoid cross-sheet transaction id collisions.

Rows without a transaction id or without text in the selected columns are skipped and counted in the command summary.

## Generate Prompt Files

To manually submit prompts to a cloud model service, generate prompt files without calling Ollama:

```bash
uv run parse-freetext-ollama output/texts \
  --prompt-output-dir output/prompts \
  --prompts-only
```

This creates one ready-to-submit prompt per input text file:

```text
output/prompts/TX-001_prompt.txt
output/prompts/TX-002_prompt.txt
```

## Parse With Ollama

Make sure Ollama is running locally and the model is available:

```bash
ollama serve
ollama pull qwen2.5:14b
```

Then parse the extracted text files:

```bash
uv run parse-freetext-ollama output/texts \
  --model qwen2.5:14b \
  --output-csv output/transactions_extracted.csv \
  --output-jsonl output/transactions_extracted.jsonl
```

You can also save prompts during the Ollama run:

```bash
uv run parse-freetext-ollama output/texts \
  --model qwen2.5:14b \
  --prompt-output-dir output/prompts
```

Ollama options:

- `--ollama-url`: generate endpoint. Defaults to `http://localhost:11434/api/generate`.
- `--retries`: retries per text file. Defaults to `2`.
- `--temperature`: model temperature. Defaults to `0.0`.
- `--num-ctx`: context window. Defaults to `8192`.
- `--timeout`: HTTP timeout in seconds. Defaults to `300`.

If parsing fails for a file after all retries, the CSV and JSONL include a low-quality failure row with the error in `transaction_details`.

## Structured Output Schema

The Ollama parser writes CSV and JSONL with these fields:

```text
transaction_id_parent
sub_id
secondary_party
value
currency
eur_equivalent
quality_of_parsing
transaction_date
bank_details
account_details
transaction_details
```

## Examples

The repository includes a sanitized workbook and expected extracted text files:

```text
examples/sample_transactions.xlsx
examples/expected_texts/TX-001.txt
examples/expected_texts/TX-002.txt
examples/expected_texts/TX-003.txt
```

Try the full local extraction flow:

```bash
uv run parse-freetext examples/sample_transactions.xlsx \
  --transaction-id-column "Transaction ID" \
  --text-column Notes \
  --text-column Description \
  --output-dir output/example_texts \
  --overwrite

uv run parse-freetext-ollama output/example_texts \
  --prompt-output-dir output/example_prompts \
  --prompts-only
```

## Development

```bash
uv sync --extra dev
uv run pytest
uv run parse-freetext --help
uv run parse-freetext-ollama --help
```

## Artifact Policy

Committed:

- Source code under `src/`
- Tests under `tests/`
- Sanitized examples under `examples/`
- `README.md`, `LICENSE`, `pyproject.toml`, `uv.lock`, and `.gitignore`

Ignored:

- Local input workbooks under `input/`
- Generated text, prompt, CSV, and JSONL outputs under `output/`
- Virtual environments, caches, build metadata, and operating-system files

Do not commit real client, dossier, or investigation data.

## License

MIT. See [LICENSE](LICENSE).
