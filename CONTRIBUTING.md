# Contributing to MeshLink Desktop

Thanks for considering a contribution! Bug reports, documentation
improvements, translations, and code patches are all welcome.

## Before you start

- **Search existing issues** to avoid duplicates.
- For **non-trivial features** or refactors, please open an issue first to
  discuss the approach — it saves everyone time.
- Keep pull requests **focused**: one feature or fix per PR.

## Development setup

```bash
# Clone the repo
git clone https://github.com/<your-username>/meshtastic-desktop.git
cd meshtastic-desktop

# Create an isolated Python environment
python3 -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate

# Install runtime + dev deps
pip install -r requirements.txt
pip install ruff                    # used for linting

# Run from source
python main.py
```

You'll need a Meshtastic-compatible radio for end-to-end testing.
Most code paths can be exercised with a fake interface — see the
smoke tests in `tests/` for the pattern.

## Project layout

```
meshlink_desktop/
├── main.py                 boot, logging, single-instance lock
├── app/
│   ├── connection.py       MeshtasticManager (the brains)
│   ├── i18n.py             translations (RO / EN / ES)
│   ├── message_db.py       SQLite store for chat history
│   ├── telemetry_db.py     SQLite store for 24h chart
│   ├── scripts_db.py       SQLite store for automation
│   ├── script_runner.py    sandboxed script execution + scheduler
│   ├── settings_store.py   JSON-backed user preferences
│   ├── theme.py            colour palette
│   ├── pages/              one file per top-level tab
│   ├── widgets/            reusable Qt widgets
│   └── dialogs/            modal windows
├── tests/                  smoke tests + scenario tests
├── docs/                   architecture notes, screenshot guide
└── requirements.txt
```

## Code style

- **Python 3.10+** with type hints encouraged but not enforced
- **Line length:** 88 (matches `black` / `ruff` defaults)
- **Imports:** standard library, then third-party, then local
- **Logging:** use `log = logging.getLogger("meshtastic.<module>")`
  — never `print()` in production code
- **String formatting:** prefer f-strings
- **Qt patterns:**
  - All UI work happens on the Qt main thread
  - Cross-thread emits go through `MeshtasticManager._invoke_on_qt` or
    use `Signal(dict)` / `Signal(object)` instead of multi-arg signals
    (PySide6 6.11 has a slot-resolution bug with `Signal(int, str)` —
    see comments in `connection.py`)
- **Comments:** prefer "why" over "what". The code shows what; the comment
  should explain non-obvious reasoning, especially around RF quirks,
  PySide6 workarounds, and protobuf differences between firmware versions.

Run before opening a PR:

```bash
ruff check app/                 # lint
python -m compileall -q app/    # syntax check
```

## Testing

The repo includes scenario smoke tests under `tests/` that exercise the
full app with a stub interface (no real radio needed). To run them:

```bash
QT_QPA_PLATFORM=offscreen python tests/run_smoke.py
```

For features that touch the wire (sending packets, receiving), please
also describe how you tested with real hardware in the PR description.
Useful info to include:
- Hardware model + firmware version
- Region and LoRa preset
- Connection type (TCP / serial / BLE)
- Number of nodes in your local mesh

## Pull request checklist

- [ ] Branch is up to date with `main`
- [ ] `ruff check app/` passes (or any new findings are documented)
- [ ] `python -m compileall -q app/` reports no errors
- [ ] Smoke tests still pass
- [ ] If you added a new UI string, all 3 languages (RO/EN/ES) are updated
  in `app/i18n.py`
- [ ] If you changed protobuf-touching code, the change works on both the
  pure-Python and `_upb` (C++) protobuf backends
- [ ] CHANGELOG.md has an entry under "Unreleased" describing the change
- [ ] Tested on real hardware (or explained why that wasn't possible)

## Submitting translations

Adding a new language? Open `app/i18n.py`, copy the `_EN` dict, translate
the values, and register it. Then update the language picker in
`app/pages/settings_page.py`. Roughly 240 strings as of V20.

## Reporting security issues

Please **don't** open public issues for security vulnerabilities. See
[SECURITY.md](SECURITY.md) for the private reporting process.

## Code of conduct

By participating in this project you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md). Be respectful, be patient,
assume good faith.

## License

By contributing, you agree that your contributions will be licensed
under the [MIT License](LICENSE) that covers the project.
