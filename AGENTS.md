# astrbot_plugin_pubg

A plugin for the [AstrBot](https://github.com/AstrBotDevs/AstrBot) chatbot
framework that queries PUBG player stats via the official PUBG API and renders
them as image cards (Pillow) or text. All logic lives in `main.py`; see
`README.md` for user-facing commands and config.

## Cursor Cloud specific instructions

### Nature of this repo
- This is **not a standalone app** — it is an AstrBot plugin (a `Star`). At
  runtime it is loaded by a host AstrBot instance which provides the command
  router, config panel, and LLM-tool registration. `main.py` imports `astrbot`
  at module load, so `astrbot` must be installed to import the plugin at all.
- No test suite, linter config, build system, or `.cursor/environment.json`
  exists. Dependencies are declared only in `requirements.txt`
  (`astrbot`, `aiohttp`, `Pillow`).

### Environment
- Python deps are installed into a project virtualenv at `.venv` (gitignored).
  Always run the plugin's code with `.venv/bin/python` (e.g.
  `.venv/bin/python -c "import main"`), not the system `python3`.
- The startup update script recreates/refreshes `.venv` from `requirements.txt`;
  it is idempotent and fast on warm snapshots.
- `fonts-noto-cjk` is installed at the system level (persisted in the snapshot).
  The UI labels are Chinese, so this is needed for readable image cards. Without
  a CJK font the code silently falls back to `ImageFont.load_default()`, which
  renders Chinese text as boxes — image rendering still "works" but looks wrong.

### Running / testing without secrets
- The core output path (`_render_image` / `_render_text` / `_parse_match`) is
  pure and can be exercised with sample PUBG-API-shaped dicts — no API key or
  running host needed. This is the recommended smoke test for rendering changes.
- Importing the package via `from . import ...` requires package context; the
  simplest check is `.venv/bin/python -c "import sys; sys.path.insert(0,'.'); import main"`.

### True end-to-end (needs external setup)
- A full `/pubg <player> [platform]` flow additionally requires: a running
  AstrBot host, at least one connected chat-platform adapter, and a **PUBG
  Developer API key** (config field `api_key`, from https://developer.pubg.com/).
  The API is a remote service (`https://api.pubg.com/shards`) with no local
  mock, so end-to-end testing of live queries needs that key as a secret.
