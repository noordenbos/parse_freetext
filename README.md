# parse-freetext

Turn messy free text into structured CSV/JSON records using local LLMs with Ollama.

Private. Reproducible. Schema-driven.

Built for sensitive workflows where prompts, source text, and outputs should stay on your own machine.

## Typical Use Cases

- Medical and clinical note abstraction
- Financial transaction extraction
- Pathology and laboratory report parsing
- Regulatory and compliance document processing
- Research dataset normalization and clean-up
- Investigation dossier extraction
- Internal enterprise ETL (Extract, Transform, Load) workflows
- Insurance claims and underwriting pipelines
- Air-gapped or privacy-sensitive document processing
- Structured extraction from PDFs, spreadsheets, and OCR text

## Why Local?

- Sensitive data never leaves your machine
- No cloud API costs
- Full control over prompts and models
- Reproducible structured extraction
- Offline capable
- HIPAA / GDPR / enterprise compliance workflows

---

## Demo In 60 Seconds

<details>
<summary>Help! I do not have Git, Python, uv, or Ollama installed</summary>

This project uses:

- **Git** to download the project
- **Python** to run it
- **uv** to manage the Python environment
- **Ollama** to run local AI models

---

# 1. Install Git

## macOS

Install Apple Command Line Tools:

```bash
xcode-select --install
```

Or download Git manually:

https://git-scm.com/downloads

## Windows

Install **Git for Windows**:

https://git-scm.com/downloads

The default installation settings are usually fine.

## Linux

### Debian / Ubuntu

```bash
sudo apt update
sudo apt install git
```

### Fedora

```bash
sudo dnf install git
```

---

# 2. Install Python

We recommend **Python 3.11 or newer**.

## macOS / Windows

Download Python from:

https://www.python.org/downloads/

### Important for Windows

During installation, enable:

```text
Add python.exe to PATH
```

## Linux

### Debian / Ubuntu

```bash
sudo apt update
sudo apt install python3 python3-pip
```

---

# 3. Verify Python

Check that Python works:

```bash
python --version
```

If that does not work, try:

```bash
python3 --version
```

---

# 4. Install uv

`uv` is the Python environment and package runner used by this project.

## macOS / Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Windows PowerShell

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installation:

- Close and reopen your terminal
- Then verify installation:

```bash
uv --version
```

---

# 5. Install Ollama

Ollama is used to run local AI models on your computer.

Download:

https://ollama.com/download

## macOS / Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

## Windows PowerShell

```powershell
irm https://ollama.com/install.ps1 | iex
```

Verify installation:

```bash
ollama --version
```

---

# 6. Download a Model

Example recommended models:

## Balanced quality/speed

```bash
ollama pull qwen2.5:7b
```

## Smaller/faster systems

```bash
ollama pull llama3.2:3b
```

---

# 7. Verify Everything

Run:

```bash
git --version
python --version
uv --version
ollama --version
```

If `python --version` fails, try:

```bash
python3 --version
```

You are now ready to continue with the project installation.

</details>

Clone the repository:

```bash
git clone https://github.com/noordenbos/parse_freetext.git
cd parse_freetext
```

Install dependencies:

```bash
uv sync --extra dev
```

Install Ollama and pull a model:

```bash
ollama pull qwen3.5:9b
```

Run a local extraction:

```bash
uv run parse-freetext-ollama input/texts/example_project \
  --model qwen3.5:9b \
  --output demo
```

Outputs:

output/demo/demo.csv
output/demo/demo.jsonl

--

## Example

Input Free Text
```Patient reports fever for 3 days. LDL 3.2 mmol/L.```

Output CSV
| clinical_item | value | unit   | qualitative_status |
|---|---:|---|---|
| fever |  |  | present |
| LDL | 3.2 | mmol/L |  |

<details>
<summary>Computer readable outputs</summary>

CSV
```csv
clinical_item,value,unit,qualitative_status
fever,,,present
LDL,3.2,mmol/L,	
```

JSON
```json
[
  {
    "clinical_item": "fever",
    "qualitative_status": "present",
    "details": "Patient reports fever for 3 days"
  },
  {
    "clinical_item": "LDL",
    "value": 3.2,
    "unit": "mmol/L"
  }
]
```
</details>

## Workflow Overview

```text
┌──────────────────────────────────────────────────────────┐
│ Raw input data support                                   │
│ • Spreadsheets (.xlsx, .csv, .tsv)                       │
│ • Plain text / copied clinical notes                     │
│ • Portable Document Format (PDF) files (planned)         │
└──────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────┐
│ Standardized intermediate text                           │
│ • Prepared {id}.txt files                                │
│ • Metadata-aware                                         │
└──────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────┐
│ Rulebook optimization                                    │
│ • Parsing quality                                        │
│ • Token efficiency                                       │
└──────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────┐
│ Batch inference pipeline                                 │
│ • Fully local execution                                  │
└──────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────┐
│ Structured outputs                                       │
│ • Comma-separated values (CSV)                           │
│ • JavaScript Object Notation (JSON / JSONL)              │
│ • Quality control (QC) reports                           │
│ • Run and resource summaries                             │
└──────────────────────────────────────────────────────────┘
```

# Choosing A Model

- Ollama Model Library: [ollama model library](https://ollama.com/library)

The field of open source models is rapidly evolving,
some of the models we had success with:

| Model | Approx. Size | Speed | Quality | Recommended Use |
|---|---|---|---|---|
| `qwen3.6:latest` | ~23 GB | Very Fast | Excellent | Best performance if VRAM permits |
| `qwen3.5:9b` | ~7 GB | Good | Excellent | Best overall default for structured extraction |
| `mistral` | ~4 GB | Good | Good | Lightweight systems |

Useful project for estimating local model compatibility and performance: [canirun.ai](https://canirun.ai)

---

# Hardware Recommendations

<details>
<summary>Consumer laptops and desktops</summary>
  
| Hardware Profile | GPU Available | Recommended VRAM | Recommended Models | Notes |
|---|---|---|---|---|
| Older laptop / office PC | No | System RAM only | `mistral` | CPU-only inference, best for lightweight extraction |
| Consumer laptop with entry GPU | Yes | 4–8 GB VRAM | `mistral`, small `llama3` | Good balance for portable systems |
| Mid-range gaming laptop / desktop | Yes | 8–12 GB VRAM | `qwen3.5:9b` | Ideal sweet spot for most users |
| High-end gaming desktop | Yes | 16–24 GB VRAM | `qwen3.5:9b` | Supports larger context windows and parallel tasks |
| Apple Silicon MacBook Pro | Shared GPU memory | 18–48 GB unified memory | `qwen3.5:9b` | Excellent local inference efficiency |
</details>

---

<details>
<summary>Professional and workstation setups</summary>

| Hardware Profile | GPU Available | Recommended VRAM | Recommended Models | Notes |
|---|---|---|---|---|
| Professional workstation | Yes | 24–48 GB VRAM | `qwen3.5:9b` | Large-scale extraction and batch processing |
| Multi-GPU AI workstation | Yes | 48+ GB VRAM | Multiple concurrent models | Parallel inference and very large contexts |
| CPU-heavy server | Optional | Large system RAM | `qwen3.5:9b` | Useful for automation pipelines |
| Dedicated AI server | Yes | 80+ GB VRAM | Large future models | Enterprise-scale workloads |
</details>

---

## Key Features

- Local-first structured extraction
- Schema-driven prompting
- Compact prompt optimization
- CSV and JSONL output
- Rulebook-based extraction logic
- Deterministic low-temperature workflows
- Retry handling and session logging
- Model-agnostic Ollama backend

---

# Installation

These steps are written to be safe across macOS, Linux, and Windows. Follow the visible path first; open the collapsed sections when you need platform-specific commands, examples, or reference details.

<details>
<summary>Need help installing Git, Python, uv, or Ollama?</summary>

This project uses:

- **Git** to download the project
- **Python** to run it
- **uv** to manage the Python environment
- **Ollama** to run local AI models

---

# 1. Install Git

## macOS

Install Apple Command Line Tools:

```bash
xcode-select --install
```

Or download Git manually:

https://git-scm.com/downloads

## Windows

Install **Git for Windows**:

https://git-scm.com/downloads

The default installation settings are usually fine.

## Linux

### Debian / Ubuntu

```bash
sudo apt update
sudo apt install git
```

### Fedora

```bash
sudo dnf install git
```

---

# 2. Install Python

We recommend **Python 3.11 or newer**.

## macOS / Windows

Download Python from:

https://www.python.org/downloads/

### Important for Windows

During installation, enable:

```text
Add python.exe to PATH
```

## Linux

### Debian / Ubuntu

```bash
sudo apt update
sudo apt install python3 python3-pip
```

---

# 3. Verify Python

Check that Python works:

```bash
python --version
```

If that does not work, try:

```bash
python3 --version
```

---

# 4. Install uv

`uv` is the Python environment and package runner used by this project.

## macOS / Linux

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Windows PowerShell

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

After installation:

- Close and reopen your terminal
- Then verify installation:

```bash
uv --version
```

---

# 5. Install Ollama

Ollama is used to run local AI models on your computer.

Download:

https://ollama.com/download

## macOS / Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

## Windows PowerShell

```powershell
irm https://ollama.com/install.ps1 | iex
```

Verify installation:

```bash
ollama --version
```

---

# 6. Download a Model

Example recommended models:

## Balanced quality/speed

```bash
ollama pull qwen2.5:7b
```

## Smaller/faster systems

```bash
ollama pull llama3.2:3b
```

---

# 7. Verify Everything

Run:

```bash
git --version
python --version
uv --version
ollama --version
```

If `python --version` fails, try:

```bash
python3 --version
```

You are now ready to continue with the project installation.

</details>

### 1. Clone The Repository

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

### 2. Install The Python Environment

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

### 3. Prepare Text Files

If you already have prepared free text files, put them in a folder like this:

```text
input/texts/example_project/CASE-001.txt
input/texts/example_project/CASE-002.txt
```

If your source is a spreadsheet, use `spreadsheet-helper` to create those `.txt` files.

<details>
<summary>Create text files from a spreadsheet</summary>

First inspect the example workbook:

```bash
uv run spreadsheet-helper input/example_project/raw/sample_transactions.xlsx --inspect
```

Then extract selected free-text columns. If you omit `--text-output-dir`, the helper writes to `input/texts/sample_transactions/` because the raw file is named `sample_transactions.xlsx`.

```bash
uv run spreadsheet-helper input/example_project/raw/sample_transactions.xlsx \
  --transaction-id-column "Transaction ID" \
  --text-column Notes \
  --text-column Description \
  --overwrite
```

For this walkthrough, write to the example project text folder:

```bash
uv run spreadsheet-helper input/example_project/raw/sample_transactions.xlsx \
  --transaction-id-column "Transaction ID" \
  --text-column Notes \
  --text-column Description \
  --text-output-dir input/texts/example_project \
  --overwrite
```

On Windows PowerShell, use backticks for line continuation:

```powershell
uv run spreadsheet-helper input/example_project/raw/sample_transactions.xlsx `
  --transaction-id-column "Transaction ID" `
  --text-column Notes `
  --text-column Description `
  --text-output-dir input/texts/example_project `
  --overwrite
```

The helper also accepts `.csv` and `.tsv` files. For those formats, the first row is treated as headers and `--sheet` is not supported.

</details>

### 4. Add A Local Rulebook

Create a local rulebook from the non-sensitive example:

macOS/Linux:

```bash
mkdir -p rules
cp input/example_project/rulebook.example.txt rules/ollama_rulebook.txt
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force rules
Copy-Item input/example_project/rulebook.example.txt rules/ollama_rulebook.txt
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

Examples:
- "LDL 3.2 mmol/L" -> clinical_item LDL, value 3.2, unit mmol/L.
- "No fever reported" -> clinical_item fever, value 0, unit yes_no, qualitative_status absent.
```

Best practices:

- Add an `Output columns:` section near the top so the CLI can build the Ollama JSON schema and CSV headers.
- Keep `Output columns:` structural: declare only `- column_name (type)` so the parser can build columns, aliases, and schema.
- Use only `string`, `number`, `integer`, or `boolean` as column types.
- Use snake_case column names, such as `record_id`, `row_id`, `clinical_item`, and `event_date`.
- Put behavioral instructions in `Rules:`, including field meanings, row splitting, normalization, and what to do when information is missing.
- Fields such as `transaction_id_parent`, `record_id`, `sub_id`, and `row_id` are filled by Python after extraction and are omitted from the model-facing aliases/schema.
- Add an optional `Inherited fields:` section for columns that are often shared by many rows, such as a global date period. Keep it structural too.
- Add a short `Examples:` section with synthetic examples when it helps resolve common ambiguities.
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

Examples:
- synthetic source phrase -> expected field values.

Formatting requirements:
- Use snake_case column names.
- Use only these types: string, number, integer, boolean.
- Keep Output columns structural only: no long instructions in that section.
- Put all interpretation, normalization, row splitting, and missing-value behavior in Rules.
- Mark fields that Python should fill, such as record_id, row_id, transaction_id_parent, or sub_id, under Python-filled fields.
- Mark fields that are often shared by many rows, such as document_context or event_date, under Inherited fields.
- Keep rules concise and source-grounded.
- Avoid repeating the same instruction in multiple fields.
- Add a short `Examples:` section with synthetic examples when it helps resolve common ambiguities.

My intended output columns are:
[paste target output columns here]

Use case:
[describe the parsing goal]
```

After saving the generated rulebook locally, run `--prompts-only` and inspect a few prompt files before running batched analysis.

</details>

### 6. Generate Prompts Without Calling A Model

Always do this first after changing a rulebook:

```bash
uv run parse-freetext-ollama input/texts/example_project \
  --prompts-only \
  --prompt-output-dir output/example_prompts
```

Inspect a few generated prompt files:

```text
output/example_prompts/
```

If the rulebook structural sections are malformed, the CLI stops here with a `Rulebook structural format warning` and a short formatting walkthrough.

### 7. Optional: Install And Run Ollama Locally

Install Ollama from [https://ollama.com/download](https://ollama.com/download). On Linux, the installer command published by Ollama is:

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

### 8. Inspect And Optimize Prompts Interactively

Before running a full batch, test one or two generated prompts directly in Ollama. This is the fastest way to tune the rulebook for response quality, token use, and runtime.

<details>
<summary>Interactive Ollama prompt tuning tutorial</summary>

Start an interactive Ollama session:

```bash
ollama run qwen3.5:9b
```

Inside the Ollama session, set these options:

```text
/set nohistory
/set nothink
/set verbose
```

Then open one generated prompt file from `output/example_prompts/`, copy the full prompt text, and paste it into the Ollama session.

The model response should be JSON only. If the response includes explanations, Markdown fences, or extra commentary, tighten the rulebook and regenerate prompts with `--prompts-only`.

With `/set verbose`, Ollama prints timing and token statistics after the response. Use those stats to compare prompt versions:

- Quality: correct rows, correct fields, no invented values, no repeated inherited context in row details.
- Prompt cost: prompt token count.
- Response cost: generated token count.
- Runtime: total response time and token evaluation speed.

Optimize for the best response quality at the lowest acceptable token and time cost. Usually that means making rules shorter, moving repeated row context into inherited fields, removing redundant examples, and keeping `Output columns:` structural.

After editing `rules/ollama_rulebook.txt`, regenerate prompts and repeat:

```bash
uv run parse-freetext-ollama input/texts/example_project \
  --prompts-only \
  --prompt-output-dir output/example_prompts
```

</details>

### 9. Run A Local Batch Extraction

This calls the local Ollama API, so it can use CPU/GPU resources. Start with a small input folder.

```bash
uv run parse-freetext-ollama input/texts/example_project \
  --model qwen3.5:9b \
  --output example_records
```

This writes:

```text
output/example_records/example_records.csv
output/example_records/example_records.jsonl
output/example_records/example_records.compact.jsonl
output/example_records/example_records.ollama_calls.jsonl
output/example_records/prompts/
output/example_records/run_metadata.txt
```

The regular CSV and JSONL use readable column names. The compact JSONL is mostly for debugging the alias-shaped model output.

## Main CLI: Parse With Ollama

`parse-freetext-ollama` is the main command. It reads prepared `{id}.txt` input files from a folder, builds prompts from a local rulebook, calls Ollama unless `--prompts-only` is used, and writes structured output.

```bash
uv run parse-freetext-ollama input/texts/example_project \
  --model qwen3.5:9b \
  --output records_extracted
```

Relative `--output` values are written as dedicated run folders under `output/`. Prompts and run metadata are saved by default.

<details>
<summary>Outputs and command options</summary>

The command above creates:

```text
output/records_extracted/records_extracted.csv
output/records_extracted/records_extracted.jsonl
output/records_extracted/records_extracted.compact.jsonl
output/records_extracted/records_extracted.ollama_calls.jsonl
output/records_extracted/prompts/
output/records_extracted/run_metadata.txt
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
- `--output`: base run folder name or path. Relative values are nested under `output/`.
- `--prompt-output-dir`: override the derived prompt folder.
- `--output-csv`, `--output-jsonl`, `--output-compact-jsonl`, `--call-log-jsonl`, `--run-metadata`: override individual derived paths when needed.
- `--no-call-log`: disable Ollama call logging.

If parsing fails for a file after all retries, the CSV and JSONL include a failure row. For custom schemas, the error is written to `details`, `notes`, or another available detail field when one exists.

The command prints a Python-side run summary with file counts, attempts, records, wall time, and aggregated Ollama token/timing stats when the API returns them. The call log writes one JSON object per Ollama attempt with model settings, timing, token counts, response sizes, record counts, and errors. It does not store prompts, source text, or model response text.

</details>

## Helper CLI: Spreadsheet To Text

`spreadsheet-helper` is a small helper for creating prepared input `.txt` files for `parse-freetext-ollama`. It is intentionally secondary to the Ollama parser.

Supported formats:

- `.xlsx`: supports workbook inspection and `--sheet` selection.
- `.csv`: treats the first row as headers.
- `.tsv`: treats the first row as headers.

<details>
<summary>Spreadsheet helper examples and options</summary>

Inspect a spreadsheet-like input:

```bash
uv run spreadsheet-helper input/example_project/raw/sample_transactions.xlsx --inspect
```

Extract text from selected columns:

```bash
uv run spreadsheet-helper input/example_project/raw/sample_transactions.xlsx \
  --sheet Transactions \
  --sheet Archive \
  --transaction-id-column "Transaction ID" \
  --text-column Notes \
  --text-column Description \
  --text-output-dir input/texts/example_project
```

For CSV/TSV, omit `--sheet`:

```bash
uv run spreadsheet-helper input/raw/my_project/my_records.csv \
  --transaction-id-column "Record ID" \
  --text-column Notes \
  --text-output-dir input/texts/my_project
```

Column references can be:

- Header names: `--transaction-id-column "Record ID"`
- Spreadsheet letters: `--text-column C`
- 1-based numbers: `--text-column 3`

Useful options:

- `--inspect`: print sheet/table names and headers.
- `--sheet`: worksheet tab to process for `.xlsx` files. Repeat it for multiple tabs. If omitted, all sheets are processed.
- `--text-column`: free-text column to extract. Repeat it to combine multiple columns into one text file.
- `--text-output-dir`: prepared text input folder. Defaults to `input/texts/<input_file_stem>`.
- `--overwrite`: replace existing output files.
- `--append-sheet-name`: append the sheet name to each filename to avoid cross-sheet collisions for `.xlsx` files.

Rows without a record id or without text in the selected columns are skipped and counted in the command summary.

</details>

## Development

```bash
uv sync --extra dev
uv run pytest
uv run parse-freetext-ollama --help
uv run spreadsheet-helper --help
```

## Artifact Policy

<details>
<summary>Committed and ignored files</summary>

Committed:

- Source code under `src/`
- Tests under `tests/`
- Sanitized example project under `input/example_project/`
- `README.md`, `LICENSE`, `pyproject.toml`, `uv.lock`, and `.gitignore`

Ignored:

- Private raw source files under `input/raw/`
- Private prepared text inputs under `input/texts/`
- Generated prompt, CSV, JSONL, call-log, and metadata outputs under `output/`
- Local extraction rules under `rules/ollama_rulebook.txt`
- Virtual environments, caches, build metadata, and operating-system files

Do not commit real client, dossier, or investigation data.

</details>

## License

MIT. See [LICENSE](LICENSE).
