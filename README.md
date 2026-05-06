# parse-freetext

`parse-freetext` is a Python CLI toolkit for turning spreadsheet free-text fields into plain text files, ready-to-submit prompts, and structured records.

It is designed for repeatable local workflows:

1. Inspect an `.xlsx` workbook to find sheet names and headers.
2. Extract selected free-text columns into one `.txt` file per source row or record id.
3. Generate prompt files for manual submission to cloud model services.
4. Optionally parse those text files through a local Ollama model into CSV and JSONL.

## Full Setup Walkthrough

These steps are written to be safe across macOS, Linux, and Windows. Commands are shown for a normal terminal. On Windows, use PowerShell unless noted otherwise.

### 1. Install Prerequisites

Install Git:

- macOS: install Xcode Command Line Tools with `xcode-select --install`, or install Git from <https://git-scm.com/downloads>.
- Windows: install Git for Windows from <https://git-scm.com/downloads>.
- Linux: install Git with your package manager, for example `sudo apt install git` on Debian/Ubuntu.

Install `uv`, the Python environment and package runner used by this project:

macOS/Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen your terminal after installing `uv`, then check:

```bash
git --version
uv --version
```

### 2. Clone The Repository

Using SSH:

```bash
git clone git@github.com:noordenbos/parse_freetext.git
cd parse_freetext
```

If SSH is not configured for GitHub, use HTTPS instead:

```bash
git clone https://github.com/noordenbos/parse_freetext.git
cd parse_freetext
```

### 3. Install The Python Environment

Install the project and its development/test dependencies:

```bash
uv sync --extra dev
```

Check that the CLIs are available:

```bash
uv run parse-freetext --help
uv run parse-freetext-ollama --help
```

Run the test suite:

```bash
uv run pytest
```

### 4. Create Text Files From A Workbook

First inspect the example workbook:

```bash
uv run parse-freetext examples/sample_transactions.xlsx --inspect
```

Then extract selected free-text columns:

```bash
uv run parse-freetext examples/sample_transactions.xlsx \
  --transaction-id-column "Transaction ID" \
  --text-column Notes \
  --text-column Description \
  --output-dir output/example_texts \
  --overwrite
```

On Windows PowerShell, use backticks for line continuation:

```powershell
uv run parse-freetext examples/sample_transactions.xlsx `
  --transaction-id-column "Transaction ID" `
  --text-column Notes `
  --text-column Description `
  --output-dir output/example_texts `
  --overwrite
```

You should now have `.txt` files under:

```text
output/example_texts/
```

### 5. Add A Local Rulebook

Create a local rulebook from the non-sensitive example:

macOS/Linux:

```bash
mkdir -p rules
cp examples/rulebook.example.txt rules/ollama_rulebook.txt
```

If your clone does not contain `examples/rulebook.example.txt`, update to the latest repository version. As a temporary fallback, create `rules/ollama_rulebook.txt` from the rulebook format example below and then run `--prompts-only` to validate it.

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force rules
Copy-Item examples/rulebook.example.txt rules/ollama_rulebook.txt
```

Edit `rules/ollama_rulebook.txt` for your own use case. This file is ignored by Git and should be treated as local/private.

### 6. Generate Prompts Without Calling A Model

Always do this first after changing a rulebook:

```bash
uv run parse-freetext-ollama output/example_texts \
  --prompts-only \
  --prompt-output-dir output/example_prompts
```

Inspect a few generated prompt files:

```text
output/example_prompts/
```

If the rulebook structural sections are malformed, the CLI stops here with a `Rulebook structural format warning` and a short formatting walkthrough.

### 7. Optional: Install And Run Ollama Locally

Install Ollama from <https://ollama.com/download>. On Linux, the installer command published by Ollama is:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Start Ollama. Depending on your platform, this may happen automatically after installing the desktop app. If not, run this in a separate terminal and keep it open:

```bash
ollama serve
```

Pull a model:

```bash
ollama pull qwen3.5:9b
```

### 8. Run A Local Extraction

This calls the local Ollama API, so it can use CPU/GPU resources. Start with a small input folder.

```bash
uv run parse-freetext-ollama output/example_texts \
  --model qwen3.5:9b \
  --output example_records
```

This writes:

```text
output/example_records.csv
output/example_records.jsonl
output/example_records.compact.jsonl
output/example_records.ollama_calls.jsonl
output/example_records_prompts/
```

The regular CSV and JSONL use readable column names. The compact JSONL is mostly for debugging the alias-shaped model output.

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

## Add A Local Rulebook

The Ollama parser can add a user-provided rulebook to every prompt. By default it looks for:

```text
rules/ollama_rulebook.txt
```

That local path is ignored by Git, so it is a good place for project-specific rules that should not be committed. The included example uses synthetic medical dossier parsing to show qualitative, discrete, and continuous field extraction without exposing real sensitive content.

Start from the non-sensitive example:

```bash
mkdir -p rules
cp examples/rulebook.example.txt rules/ollama_rulebook.txt
```

You can also point to another file:

```bash
uv run parse-freetext-ollama output/texts \
  --rules-file path/to/your_rulebook.txt \
  --prompt-output-dir output/prompts \
  --prompts-only
```

Rulebook format:

- Keep private client, dossier, investigation, and internal methodology details out of committed files.
- Write plain text or Markdown-style bullets with clear section headings.
- Add an `Output columns:` section near the top so the CLI can build the Ollama JSON schema and CSV headers.
- Keep `Output columns:` structural: declare only `- column_name (type)` so the parser can build columns, aliases, and schema.
- Use only `string`, `number`, `integer`, or `boolean` as column types.
- Use snake_case column names, such as `record_id`, `row_id`, `clinical_item`, and `event_date`.
- Put behavioral instructions in `Rules:`, including field meanings, row splitting, normalization, and what to do when information is missing.
- Put one instruction per rule bullet.
- Fields such as `transaction_id_parent`, `record_id`, `sub_id`, and `row_id` are filled by Python after extraction and are omitted from the model-facing aliases/schema.
- Add an optional `Inherited fields:` section for columns that are often shared by many rows, such as a global date period. Keep it structural too.
- Name schema fields directly when a rule applies to a field, such as `value`, `unit`, or `details`.
- Include normalization rules for dates, units, numeric values, qualitative labels, and null values.
- Prefer source-grounded instructions over broad judgment calls.
- Tell the model not to invent missing values, diagnoses, conclusions, intent, or unsupported calculations.
- Keep examples synthetic and non-sensitive.
- Test changes with `--prompts-only` first, then inspect a few generated prompts before running a model.

The CLI validates the structural sections before generating prompts. If a field bullet is malformed, uses an unsupported type, duplicates a column, or references an inherited/Python-filled field that is not an output column, it stops with a `Rulebook structural format warning` and prints a short format walkthrough.

Example column declaration:

```text
Output columns:
- record_id (string)
- row_id (integer)
- clinical_item (string)
- value (number)
- unit (string)
- qualitative_status (string)
- event_date (string)
- details (string)

Python-filled fields:
- record_id
- row_id

Inherited fields:
- event_date (string)

Rules:
- clinical_item: extracted medical item.
- value: numeric value when present.
- unit: measurement unit or coding label.
- qualitative_status: present, absent, improved, worsened, stable, or omitted.
- event_date: shared dates or periods top-level; row value only for a specific item date.
- details: concise source-grounded summary.
```

Python reads this section before calling Ollama. The parsed column names become:

- the required fields in the Ollama structured-output JSON schema
- the column order in the CSV
- the keys written to each JSONL row

To reduce prompt and response size, the Ollama request uses compact JSON aliases internally, skips Python-filled fields, and asks the model to omit unknown/null properties. The regular CSV and JSONL outputs still use the readable column names from the rulebook, with missing values filled as null/empty cells by Python.

Inherited fields may appear once as top-level JSON values in the model response. Python copies that top-level value into each row that omitted the field, while preserving row-specific overrides.

If no `Output columns:` section is found, the CLI falls back to the neutral medical-example columns shown below.

The rulebook's structural sections are parsed by Python and converted into a compact JSON-shape block. Only the remaining domain rules and examples are inserted into the prompt before the source free text:

```text
User-provided extraction rulebook:
<<<
...your rulebook text...
>>>
```

The prompt still contains the filename, the parent id, the output schema requirement, and then the free-text document. The rulebook is therefore best used for domain-specific extraction policy, not for private source data itself.

## Parse With Ollama

Make sure Ollama is running locally and the model is available:

```bash
ollama serve
ollama pull qwen3.5:9b
```

Then parse the extracted text files:

```bash
uv run parse-freetext-ollama output/texts \
  --model qwen3.5:9b \
  --output records_extracted
```

Relative `--output` values are written under `output/`. The command above creates:

```text
output/records_extracted.csv
output/records_extracted.jsonl
output/records_extracted.compact.jsonl
output/records_extracted.ollama_calls.jsonl
output/records_extracted_prompts/
```

An absolute `--output` path is used as-is.

Prompts are saved by default during extraction. You can choose a different prompt folder:

```bash
uv run parse-freetext-ollama output/texts \
  --model qwen3.5:9b \
  --prompt-output-dir output/prompts
```

Ollama options:

- `--ollama-url`: generate endpoint. Defaults to `http://localhost:11434/api/generate`.
- `--retries`: retries per text file. Defaults to `2`.
- `--temperature`: model temperature. Defaults to `0.0` (maximal deterministic).
- `--num-ctx`: context window. Defaults to `8192`.
- `--timeout`: HTTP timeout in seconds. Defaults to `300`.
- `--rules-file`: local extraction rulebook. Defaults to `rules/ollama_rulebook.txt` when that file exists.
- `--think`: enable Ollama thinking mode. Defaults to off for structured extraction. Costly.
- `--output`: base output name or path. Derives CSV, JSONL, compact JSONL, call-log JSONL, and prompt folder paths.
- `--prompt-output-dir`: override the derived prompt folder.
- `--output-csv`, `--output-jsonl`, `--output-compact-jsonl`, `--call-log-jsonl`: override individual derived paths when needed.
- `--no-call-log`: disable Ollama call logging.

If parsing fails for a file after all retries, the CSV and JSONL include a failure row. For custom schemas, the error is written to `details`, `notes`, or another available detail field when one exists.

The command also prints a Python-side run summary with file counts, attempts, records, wall time, and aggregated Ollama token/timing stats when the API returns them. The call log writes one JSON object per Ollama attempt with model settings, timing, token counts, response sizes, record counts, and errors. It does not store prompts, source text, or model response text. Ollama reports usage metrics such as `total_duration`, `prompt_eval_count`, and `eval_count` in non-streaming generate responses; durations are in nanoseconds.

## Structured Output Schema

Without an `Output columns:` section in the rulebook, the Ollama parser writes CSV and JSONL with these fallback fields:

```text
record_id
row_id
clinical_item
value
unit
qualitative_status
event_date
source_party
source_context
details
quality_of_parsing
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
- Local extraction rules under `rules/ollama_rulebook.txt`
- Virtual environments, caches, build metadata, and operating-system files

Do not commit real client, dossier, or investigation data.

## License

MIT. See [LICENSE](LICENSE).
