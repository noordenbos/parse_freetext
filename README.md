# parse-freetext

`parse-freetext` is a local-first Python toolkit for turning free text into structured records with Ollama. It is meant for sensitive workflows where prompts, model calls, and outputs should stay on your own machine.

The main workflow is:

1. Put source free text in a folder as `{id}.txt` files.
2. Write a local rulebook that defines output columns and extraction rules.
3. Generate compact prompts and inspect them before running a model.
4. Parse the text files through a local Ollama model.
5. Write readable CSV/JSONL plus optional compact/debug artifacts.

Helper tools can create the input `.txt` files from source formats. Today this repo includes `spreadsheet-helper` for `.xlsx`, `.csv`, and `.tsv`; future helpers may support other text sources.

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
uv run parse-freetext-ollama --help
uv run spreadsheet-helper --help
```

Run the test suite:

```bash
uv run pytest
```

### 4. Prepare Text Files

If you already have free text files, put them in a folder like this:

```text
output/example_texts/CASE-001.txt
output/example_texts/CASE-002.txt
```

If your source is a spreadsheet, use the helper to create those `.txt` files. First inspect the example workbook:

```bash
uv run spreadsheet-helper examples/sample_transactions.xlsx --inspect
```

Then extract selected free-text columns:

```bash
uv run spreadsheet-helper examples/sample_transactions.xlsx \
  --transaction-id-column "Transaction ID" \
  --text-column Notes \
  --text-column Description \
  --output-dir output/example_texts \
  --overwrite
```

On Windows PowerShell, use backticks for line continuation:

```powershell
uv run spreadsheet-helper examples/sample_transactions.xlsx `
  --transaction-id-column "Transaction ID" `
  --text-column Notes `
  --text-column Description `
  --output-dir output/example_texts `
  --overwrite
```

The helper also accepts `.csv` and `.tsv` files. For those formats, the first row is treated as headers and `--sheet` is not supported.

### 5. Add A Local Rulebook

Create a local rulebook from the non-sensitive example:

macOS/Linux:

```bash
mkdir -p rules
cp examples/rulebook.example.txt rules/ollama_rulebook.txt
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force rules
Copy-Item examples/rulebook.example.txt rules/ollama_rulebook.txt
```

Edit `rules/ollama_rulebook.txt` for your own use case. This file is ignored by Git and should be treated as local/private.

<details>
<summary>Rulebook format and best practices</summary>

The Ollama parser adds your rulebook to every prompt. Keep private client, dossier, investigation, and internal methodology details out of committed files.

Use this structure:

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

Best practices:

- Add an `Output columns:` section near the top so the CLI can build the Ollama JSON schema and CSV headers.
- Keep `Output columns:` structural: declare only `- column_name (type)` so the parser can build columns, aliases, and schema.
- Use only `string`, `number`, `integer`, or `boolean` as column types.
- Use snake_case column names, such as `record_id`, `row_id`, `clinical_item`, and `event_date`.
- Put behavioral instructions in `Rules:`, including field meanings, row splitting, normalization, and what to do when information is missing.
- Fields such as `transaction_id_parent`, `record_id`, `sub_id`, and `row_id` are filled by Python after extraction and are omitted from the model-facing aliases/schema.
- Add an optional `Inherited fields:` section for columns that are often shared by many rows, such as a global date period. Keep it structural too.
- Test changes with `--prompts-only` first, then inspect a few generated prompts before running a model.

The CLI validates the structural sections before generating prompts. If a field bullet is malformed, uses an unsupported type, duplicates a column, or references an inherited/Python-filled field that is not an output column, it stops with a `Rulebook structural format warning` and a short formatting walkthrough.

To reduce prompt and response size, the Ollama request uses compact JSON aliases internally, skips Python-filled fields, and asks the model to omit unknown/null properties. The regular CSV and JSONL outputs still use the readable column names from the rulebook, with missing values filled as null/empty cells by Python.

If no `Output columns:` section is found, the CLI falls back to neutral medical-example columns.

</details>

<details>
<summary>Optional LLM prompt for drafting a rulebook</summary>

You can use your favorite LLM to draft the first version of a rulebook. Do not paste sensitive source text into a cloud model. A good safe input is the target output columns you want and, if relevant, the column names from the spreadsheet or source table that will feed the parser.

Copy and adapt this prompt:

```text
Help me write a concise rulebook for parse-freetext-ollama.

The rulebook must have these sections only:

Output columns:
- column_name (type)

Python-filled fields:
- column_name

Inherited fields:
- column_name (type)

Rules:
- column_name: short extraction rule.

Formatting requirements:
- Use snake_case column names.
- Use only these types: string, number, integer, boolean.
- Keep Output columns structural only: no long instructions in that section.
- Put all interpretation, normalization, row splitting, and missing-value behavior in Rules.
- Mark fields that Python should fill, such as record_id, row_id, transaction_id_parent, or sub_id, under Python-filled fields.
- Mark fields that are often shared by many rows, such as document_context or event_date, under Inherited fields.
- Keep rules concise and source-grounded.
- Avoid repeating the same instruction in multiple fields.
- Do not include private examples or sensitive source text.

My intended output columns are:
[paste target output columns here]

Source spreadsheet/table columns that may help define the rulebook are:
[paste non-sensitive column names here]

Use case:
[briefly describe the parsing goal without sensitive details]
```

After saving the generated rulebook locally, run `--prompts-only` and inspect a few prompt files before calling Ollama.

</details>

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

## Main CLI: Parse With Ollama

`parse-freetext-ollama` is the main command. It reads `.txt` files from a folder, builds prompts from a local rulebook, calls Ollama unless `--prompts-only` is used, and writes structured output.

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

Useful options:

- `--prompts-only`: write prompt files and skip the Ollama API call.
- `--rules-file`: local extraction rulebook. Defaults to `rules/ollama_rulebook.txt` when that file exists.
- `--model`: Ollama model name.
- `--ollama-url`: generate endpoint. Defaults to `http://localhost:11434/api/generate`.
- `--temperature`: model temperature. Defaults to `0.0`.
- `--num-ctx`: context window. Defaults to `8192`.
- `--timeout`: HTTP timeout in seconds. Defaults to `300`.
- `--retries`: retries per text file. Defaults to `2`.
- `--think`: enable Ollama thinking mode. Defaults to off for structured extraction.
- `--output`: base output name or path. Derives CSV, JSONL, compact JSONL, call-log JSONL, and prompt folder paths.
- `--prompt-output-dir`: override the derived prompt folder.
- `--output-csv`, `--output-jsonl`, `--output-compact-jsonl`, `--call-log-jsonl`: override individual derived paths when needed.
- `--no-call-log`: disable Ollama call logging.

If parsing fails for a file after all retries, the CSV and JSONL include a failure row. For custom schemas, the error is written to `details`, `notes`, or another available detail field when one exists.

The command prints a Python-side run summary with file counts, attempts, records, wall time, and aggregated Ollama token/timing stats when the API returns them. The call log writes one JSON object per Ollama attempt with model settings, timing, token counts, response sizes, record counts, and errors. It does not store prompts, source text, or model response text.

## Helper CLI: Spreadsheet To Text

`spreadsheet-helper` is a small helper for creating input `.txt` files for `parse-freetext-ollama`. It is intentionally secondary to the Ollama parser.

Supported formats:

- `.xlsx`: supports workbook inspection and `--sheet` selection.
- `.csv`: treats the first row as headers.
- `.tsv`: treats the first row as headers.

Inspect a spreadsheet-like input:

```bash
uv run spreadsheet-helper examples/sample_transactions.xlsx --inspect
```

Extract text from selected columns:

```bash
uv run spreadsheet-helper examples/sample_transactions.xlsx \
  --sheet Transactions \
  --sheet Archive \
  --transaction-id-column "Transaction ID" \
  --text-column Notes \
  --text-column Description \
  --output-dir output/texts
```

For CSV/TSV, omit `--sheet`:

```bash
uv run spreadsheet-helper input/my_records.csv \
  --transaction-id-column "Record ID" \
  --text-column Notes \
  --output-dir output/texts
```

Column references can be:

- Header names: `--transaction-id-column "Record ID"`
- Spreadsheet letters: `--text-column C`
- 1-based numbers: `--text-column 3`

Useful options:

- `--inspect`: print sheet/table names and headers.
- `--sheet`: worksheet tab to process for `.xlsx` files. Repeat it for multiple tabs. If omitted, all sheets are processed.
- `--text-column`: free-text column to extract. Repeat it to combine multiple columns into one text file.
- `--output-dir`: output folder. Defaults to `output/texts`.
- `--overwrite`: replace existing output files.
- `--append-sheet-name`: append the sheet name to each filename to avoid cross-sheet collisions for `.xlsx` files.

Rows without a record id or without text in the selected columns are skipped and counted in the command summary.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run parse-freetext-ollama --help
uv run spreadsheet-helper --help
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
