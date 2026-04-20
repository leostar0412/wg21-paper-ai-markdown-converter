# WG21 paper converter tools (pre-release)

End-to-end **URL ingestion** → **first-pass Markdown** (PDF: docling → pdfplumber; HTML: Pandoc) → **PyMuPDF layout JSON** (PDF only) → **seven improve phases** (headings → code → links → tables → lists → line breaks → styles) using **Claude Code** and/or **Cursor** as substrates, then **bundle** (`outputs/bundle.zip` with `markdown/`, `result.json`, `logs.json`).

## Requirements

- **Python** 3.11+
- [**uv**](https://docs.astral.sh/uv/) for installs and lockfile
- **Pandoc** on `PATH` (HTML → Markdown)
- Claude Code and/or Cursor CLIs available when running improve phases (same as `run_prompt.py`)

Install dependencies (core + converters):

```bash
cd wg21-paper-converter-tools-pre
uv sync --all-extras
```

> **Repository on an external/USB or non-APFS drive?** Put the virtualenv on **internal APFS** — installing into `repo/.venv` on those volumes often fails with AppleDouble / resource-fork issues (see below). Use:
>
> ```bash
> chmod +x scripts/uv-sync.sh
> ./scripts/uv-sync.sh --local-venv --all-extras
> ```

### External / non-APFS volumes (`._*` / `._pdf2txt.py` / `._vba_extract.py` errors)

On USB or network drives, macOS can create **AppleDouble** files (`._*` next to real files). Unpacking wheels into **`.venv` on that same volume** may fail, for example:

- `failed to open file .../._pdf2txt.py ... (os error 2)` (often from **pdfminer-six** / **pdfplumber** deps)
- `failed to open file .../._something`
- `failed to remove directory ... __pycache__ ... (os error 66)`

Deleting `._*` files under the repo with `find` **does not reliably fix** this, because the next install still writes into an external `.venv` and macOS can recreate sidecars. **Put the environment on APFS** using `UV_PROJECT_ENVIRONMENT` or `./scripts/uv-sync.sh --local-venv` (recommended above).

`pyproject.toml` sets **`[tool.uv] link-mode = "copy"`** so installs prefer full copies (fewer hardlink issues). If anything above fails while `.venv` lives on the external volume, **use a venv on internal APFS** (next block) instead of `repo/.venv`.

**`VIRTUAL_ENV` warning:** if your shell activated a different env (e.g. `$HOME/.venvs/...`) than this project’s `.venv`, either `deactivate` before `uv sync`, or run `uv sync --active` to sync the env you already activated.

**Fix (recommended):** keep the repo on the external disk but put the **virtualenv on your internal APFS volume** using [`UV_PROJECT_ENVIRONMENT`](https://docs.astral.sh/uv/reference/environment/):

```bash
cd wg21-paper-converter-tools-pre
export UV_LINK_MODE=copy
export UV_PROJECT_ENVIRONMENT="$HOME/.venvs/wg21-paper-converter-tools-pre"
mkdir -p "$HOME/.venvs"
rm -rf .venv
uv sync --all-extras
```

After this, `uv run …` from the project directory still uses that env. Override the path anytime with `UV_PROJECT_ENVIRONMENT`.

**Or** use the helper (same effect as above, defaulting to `$HOME/.venvs/<folder-name>`):

```bash
chmod +x scripts/uv-sync.sh
./scripts/uv-sync.sh --local-venv --all-extras
```

If you **must** keep `.venv` on the external disk: try `rm -rf .venv`, `export UV_LINK_MODE=copy`, `export COPYFILE_DISABLE=1`, then `uv sync` again; or `dot_clean .` (macOS). These are **unreliable** on exFAT — prefer **`--local-venv`** / `UV_PROJECT_ENVIRONMENT` on APFS. Alternatively clone the repo to **internal APFS** only.

> **Note:** The `convert` extra pulls **docling** (and heavy ML deps). You can omit it for a lighter install: `uv sync` (no `--all-extras`) and rely on **pdfplumber** for PDF text extraction when docling is unavailable.

## Configuration JSON

| Field                 | Type       | Description                                                              |
| --------------------- | ---------- | ------------------------------------------------------------------------ |
| `papers`              | `string[]` | HTTP(S) URLs to PDF or HTML papers (required, non-empty).                |
| `claude_code`         | object?    | `api_key`, `auth_token`, `base_url` → `ANTHROPIC_*` env vars.            |
| `cursor`              | object?    | `api_key` → `CURSOR_API_KEY`.                                            |
| `model_tier`          | int        | **1–3** → `tier_1` … `tier_3` in `model-registry.yaml`.                  |
| `callback_url`        | string?    | Optional HTTPS URL for a **POST** JSON summary when the run ends.        |
| `callback_auth_token` | string?    | Optional Bearer token (or set `CALLBACK_AUTH_TOKEN` in the environment). |

At least one of `claude_code` (with `api_key` and/or `auth_token`) or `cursor.api_key` must be non-empty.

### Substrate routing

- If **both** Claude and Cursor are configured → **author = Claude Code**, **reviewer = Cursor**.
- If **only one** is configured → **both** author and reviewer use that substrate.

## Run layout

Each run creates:

`temp/ingestion_run_<hash12>_<UTC>_<url_stem>/` (12-char hex from SHA-256 of UTC + stem)

- `papers/<stem>/` — `source.pdf` or `source.html`, `<stem>.md`, and for PDFs `<stem>.layout.json` (text blocks + per-page **links** with URIs and bboxes).
- `outputs/markdown/` — collected Markdown files.
- `outputs/bundle.zip` — `markdown/*.md`, `result.json`, `logs.json`.
- `result.json`, `logs.json` at the run root.

Folder name `<stem>` matches the Markdown basename (e.g. `papers/p1234r0/p1234r0.md`).

## CLI

```bash
uv run python url2md.py --config-file examples/workflow.example.json --repo-root . -v
```

Flags:

- `--config-file` — JSON file (preferred in CI).
- `--config-json` — inline JSON string.
- `--skip-improve` — download + convert + layout excerpt only (no LLM phases).
- `--fetch-timeout` — per-URL HTTP timeout (seconds, default 120).
- `--improve-timeout-ms` — per substrate invoke timeout (default `PAPER_IMPROVE_TIMEOUT_MS` or 300000).

For folder-scoped prompts without the full workflow, use `run_prompt.py` (see script help).

**Test one improve skill** (e.g. headings) against an existing ingestion folder:

```bash
uv run python run_prompt.py \
  --folder temp/ingestion_run_<hash12>_<UTC>_<url_stem>/papers/<stem> \
  --substrate skill --skill headings \
  --prompt "## Task context
- Primary Markdown file: <stem>.md
- Source type: pdf
- Layout excerpt JSON: <stem>.layout.json

Follow the skill instructions for phase **headings**. Edit <stem>.md in place as needed."
```

Use your real run path and stem (e.g. `p3856r5`). Defaults match `url2md` (`acceptEdits` for Claude). A JSON run log is written under the paper folder unless `--run-log` overrides it.

### Claude Code permissions (improve phases)

Non-interactive runs must allow the **author** to apply **Edit**/**Write** without a prompt. `url2md.py` sets `CLAUDE_PERMISSION_MODE=acceptEdits` when it is unset. The skill runner also passes `--permission-mode` to the Claude CLI (default `acceptEdits`, or the value of `CLAUDE_PERMISSION_MODE`). The subprocess environment mirrors that variable so behavior stays consistent with the CLI flag.

Override per deployment by exporting `CLAUDE_PERMISSION_MODE` before `uv run python url2md.py …`, or set `author.permission_mode` in a skill YAML when you need a different policy.

## GitHub Actions

Workflow: `.github/workflows/convert.yml` — **workflow_dispatch** with input `workflow_config_json` (paste the full JSON). Artifacts include `temp/ingestion_run_*/result.json`, `logs.json`, and `outputs/bundle.zip`.

Set repository **secrets** for API keys if you do not embed them in the dispatch payload (recommended: inject via a separate step or OIDC; the example JSON uses empty strings).

### Artifact download URL

GitHub does not provide a permanent anonymous download link. The optional **callback** payload can include `workflow_run_url` and repository metadata; clients with a token that has `actions: read` may use the [REST API](https://docs.github.com/en/rest/actions/artifacts) to download the artifact ZIP.

## Development

```bash
uv sync --all-extras
uv run pytest
```

## Legacy `requirements.txt`

This project is managed with **uv** and `pyproject.toml`. A minimal `requirements.txt` may exist for compatibility; prefer `uv sync`.
