# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.52.0] — 2026-05-27

### Fixed (build)
- `requirements.txt` no longer lists the non-existent `PySide6-WebEngine`
  package (which caused `pip install -r requirements.txt` to fail). Qt
  WebEngine already ships with PySide6 via PySide6-Addons, so no separate
  dependency is needed. This unblocks both `run.bat` and
  `build_meshlink_exe.bat`.


### Fixed
- **Battleship now starts correctly.** The board no longer appears before a
  game is started — until you press ▶ New game (or accept an invite) the area
  shows a clear "press New game" placeholder, so the earlier confusing state
  (a visible board where clicks did nothing) is gone. After starting, tap your
  own fleet grid to place 3 ships, then Ready.

### Added
- **Five new two-player games (10 total), each tested with real 2-player
  simulations and playable end-to-end via the UI:**
  - **Guess the Number** — one picks 1–100, the other guesses with
    higher/lower hints.
  - **Dots and Boxes** — 5×5 dot grid; complete a box to score and play again.
  - **Hangman** — one sets a secret word, the other guesses letters (6 lives).
  - **Nine Men's Morris** — place 9 men, form mills to capture, then move.
  - **Checkers** — 8×8 draughts with forced captures and simple kings.
- **Game names localized** in English, Spanish and Romanian (the picker shows
  the name in the app's current language; wire codes stay stable).

### Changed
- `run.bat` rewritten in professional English (status messages, Python version
  detection, clearer errors).
- `requirements.txt` reviewed, grouped and documented; every third-party import
  verified as covered.
- Added `build_meshlink_exe.bat` — one-click PyInstaller builder that produces
  a single-file `dist\MeshLinkDesktop.exe` (no Python needed to run it).



## [0.48.0] — 2026-05-26

### Fixed
- **DM action buttons no longer crash.** Request position, request telemetry,
  traceroute and "open in Maps" called a missing helper
  (`_current_dm_partner`), raising AttributeError every time. Added the helper
  (resolves the current "dm:<node>" conversation to a node ID).
- **Custom LoRa settings now persist and reload when editing a channel.**
  The channel dialog now reads the device's current LoRa config and pre-fills
  the bandwidth / spread factor / coding rate / slot / frequency-override
  fields, auto-enabling the radio section when the device is on a custom
  (non-preset) config. Previously these values were lost on re-open. Verified
  with a full round-trip (e.g. SFNarrow BW62/SF7/CR5/slot4/869.618 MHz).
- New `read_lora_config()` manager method backing the above.


## [0.47.0] — 2026-05-26

### Added
- **Full LoRa radio configuration in the channel dialog.** When adding or
  editing a channel you can now optionally tick "📻 Also configure device
  LoRa radio" to set the exact technical parameters in one place:
  - **Bandwidth** (31 / 62 / 125 / 250 / 500 kHz)
  - **Spreading Factor** (7–12)
  - **Coding Rate** (4/5 – 4/8)
  - **Frequency slot** (0 = auto)
  - **Frequency override** (exact MHz, e.g. 869.618)
  - **Live frequency preview** calculated from bandwidth + slot + region.
  This makes it possible to set up narrow-band test channels (e.g. SFNarrow:
  name SFNarrow, PSK AQ==, BW 62, SF 7, CR 5, slot 4, override 869.618 MHz)
  entirely from the channel dialog. A clear warning notes these are
  device-wide settings affecting all channels.
- New `write_lora_config()` manager method (use_preset, bandwidth,
  spread_factor, coding_rate, channel_num, override_frequency).


## [0.46.0] — 2026-05-25

### Added / Improved
- **Full channel configuration** in the add/edit dialog, in plain language:
  - **Role**: choose PRIMARY or SECONDARY.
  - **Encryption**: Default key (AQ==), None (no encryption), Random AES-128,
    Random AES-256, or Custom (paste base64 or hex, validated to 16/32 bytes).
  - **Location sharing**: friendly position-precision presets from "Off" to
    "Precise" (maps to the firmware's 0–32 precision bits).
  - **MQTT uplink / downlink** toggles and a **Mute channel** option.
  - A note clarifying that radio settings (region/preset/bandwidth/SF/CR/
    frequency) are device-wide (Settings → Quick Device Config), and that the
    primary channel name sets the LoRa frequency slot.
- The manager's add/update channel methods now carry role, position precision
  and mute through to the firmware, and channels report their mute state.

### Fixed (connection)
- TCP connect uses a longer 20s handshake timeout for weak-WiFi devices.
- Clear, actionable errors for refused connections (wrong port — Meshtastic
  uses 4403), socket timeouts and protocol-handshake timeouts.

### Changed (UI)
- Connection bar made compact (capped IP field) and the Scan buttons widened
  so "🔍 Scan" is never clipped; all buttons stay visible on narrow windows.


## [0.45.0] — 2026-05-23

### Fixed (connection robustness)
- Friendlier connection errors: "connection refused" now explains to check
  the IP and use port 4403 (the Meshtastic default — a common cause is using
  the wrong port like 4404); socket timeouts and protocol-handshake timeouts
  get distinct, actionable messages.
- TCP connections now use a more generous 20s handshake timeout so devices on
  weak WiFi can finish connecting (was timing out with "Timed out waiting for
  connection completion"). Falls back gracefully on older library versions.
- Logs a warning when a non-standard TCP port is used.

### Changed (UI)
- Connection bar made more compact: the IP/host field no longer grows
  unbounded (capped width), so the Scan, Connect and language buttons stay
  fully visible even on narrow windows.

### Added
- **Games: 4 new games + a game picker**. The Games tab now offers five
  two-player games chosen from a dropdown, all bandwidth-friendly (each move
  is one tiny DM via the MLGAME: protocol):
  - **Tic-Tac-Toe** — the classic 3×3.
  - **Connect 4** — drop discs in a 7×6 grid, four in a row wins.
  - **Rock-Paper-Scissors** — best of 3 rounds, simultaneous choices.
  - **Battleship** — place 3 ships on a 5×5 grid, take turns firing.
  - **Nim (21)** — take 1–3 sticks; whoever takes the last one loses.
  Each game is a self-contained engine (app/game_engines.py) with full
  rules, win/draw detection and turn enforcement; all five were verified
  with real two-player simulations.

### Changed
- Game wire protocol generalised from MLTTT: to MLGAME:<code>:<payload> so a
  single tab can host many games. Both prefixes are filtered out of the normal
  chat view (MLTTT: kept for backward-compat).


## [0.44.0] — 2026-05-22

### Added
- **🎮 Games tab — Tic-Tac-Toe over the mesh**: a tiny, bandwidth-friendly
  two-player game. Pick an opponent node and play; each move is a single ~8-byte
  DM (MLTTT: protocol). Game messages are filtered out of the normal chat.
- **🔔 Watchlist & Alerts** (Settings): get a desktop notification + sound when
  a watched node comes back online, or when a message contains a watched keyword
  (e.g. SOS, your name). Ideal for an always-on base station. Persisted across
  restarts.
- **⚡ Power graph** in Info: plots INA219/INA260 voltage, current (+charge /
  −draw) and power (mW) over time — see a solar panel's real-world yield.
- **Delete conversations**: a trash button in the Messages header clears a DM
  or channel's local history (with confirmation).
- **Map → click a node → full details**: the marker popup's "Show full details"
  opens the same NodeDetailsDialog as the Nodes tab (via a QWebChannel bridge).
- **Console "Explain activity"** mode (on by default): every RX/TX packet gets a
  short plain-English description (≤150 chars), e.g. "📍 Node-7F shared its GPS
  location" or "📤 Sending your message to Node-3C".


## [0.43.0] — 2026-05-22

### Added
- **RF Activity Scanner tab** (between Info and Map). A "Start scan" button
  dedicates the radio to an intensive passive-listen session, pausing the
  script scheduler and telemetry polling so capture is the priority. Produces
  a trust report: generic-LoRa / Meshtastic-compatible / decodable-without-key
  / exact-message-without-PSK / channel-if-PSK-known verdicts, plus per-sender
  signal stats, hop distribution, channel utilization and a plain-language
  recommendation. Honest about hardware limits (a node hears only its current
  band+preset; true wideband scanning needs SDR).
- **Settings → Quick Device Config**: 22+ controls (Identity, Radio, Custom
  LoRa BW/SF/CR for narrow-band configs, Position, Broadcast intervals,
  Display, Buttons/LED, Power saving) with auto-load from device.
- **Modules → WiFi/Network tab**: set wifi_enabled / SSID / PSK so the device
  can join Wi-Fi (reads/writes localConfig.network).
- **Channels → Import from URL/QR link**: paste a meshtastic.org/e/# share
  link to apply a channel set.
- **Network scanner** on the TCP connection bar: probes the local /24 subnet
  for devices on port 4403.
- **Serial picker**: enriched with VID:PID + manufacturer, Meshtastic-likely
  chips listed first.
- **Info tab**: exact operating Frequency (e.g. EU_868 = 869.525 MHz), plus
  live Last RX / Last TX.
- **LONG_TURBO** modem preset added (now 10 presets).
- Connection scan buttons (Serial/BLE/Wi-Fi) labelled "Scan".

### Fixed
- Crash `RuntimeError: QLabel already deleted` — node-card avatar now updates
  in place instead of destroy/recreate.
- Connection stuck on "ready" after the meshtastic reader thread died silently
  (WinError 10054 after a config write) — watchdog detects the dead reader and
  forces reconnect.
- `disconnect()` crash on an already-dead TCP socket — raw socket is closed
  first and the expected error is silenced.
- Thread leak / crash storm after a dropped link — the meshtastic heartbeat
  timer kept firing on the dead socket, spawning dozens of crashing threads
  (WinError 10054). Connection-loss and disconnect now cancel the heartbeat
  timer and close the raw socket so no background thread survives.
- Console `nodes` crash when hwModel was numeric — values are now coerced to
  str before slicing.
- Scripts DM mode no longer looks like it also broadcasts — channels are
  disabled with a clear hint when Direct Message is selected.
- Info Frequency field stayed blank — now retried each second until the LoRa
  config arrives.
- `set`/`get` console commands now support module-config sections and suggest
  the correct section when a field is in a different one.

### Changed
- Project renamed **Meshtastic Desktop → MeshLink Desktop** (trademark
  compliance). Logger names, log folder, QSettings key and the in-app logo
  updated; README carries a trademark disclaimer.
- Message delivery ticks (✓ / ✓✓) rendered in blue for visibility.
- Friendlier About text.


## [0.20.0] — 2026-05-18

First public release.

### Added
- **Messages tab**
  - Threaded replies via `replyId`
  - Emoji reactions (`EMOJI_APP`) with chip rows + multi-user grouping
  - Right-click bubble → Reply / React / Send DM / Signal report
  - Signal-report dialog with quality assessment + hop visualization
  - Outbound `messageSent` signal so script-sent messages appear in
    conversations like user-typed ones
- **Info tab**
  - Live **Mesh Health** card with channel-utilization sparkline,
    per-port RX counters and plain-English diagnostic hint
    (distinguishes "mesh quiet" from "RF interference / PSK mismatch")
  - Environment-metrics toggle on the 24h chart (temperature, humidity,
    pressure, gas resistance, IAQ)
  - Neighbor radio section in the node-details dialog
- **Channels tab**
  - Visual PSK display with mask / unmask / copy
  - Add / Edit / Remove dialog (default key / random AES256 / custom
    base64 or hex)
  - MQTT uplink and downlink toggles per channel
  - Position-precision selector
- **Modules tab** (new)
  - 8 sub-tabs: MQTT, Serial, External Notification, Store & Forward,
    Range Test, Neighbor Info, Detection Sensor, Audio
  - All fields auto-generated from the protobuf descriptors (61 fields
    total) — supports future firmware additions without code changes
  - Range Test sub-tab with live statistics panel (SNR/RSSI min/max/avg
    + packet-loss detection through sequence-number gaps)
- **Scripts tab**
  - Redesigned UI with channel checkboxes, broadcast-vs-DM target picker,
    schedule control (seconds / minutes / hours / days), and
    quick-insert snippet buttons
  - Extended script API: `local_env()`, `local_device()`,
    `local_position()`, `channels()`, `channel_by_name()`, multi-channel
    broadcast
  - Default demo: environment-telemetry broadcast every 6 h
- **Console tab**
  - Full CLI parity: 52 of 67 official `meshtastic-python` CLI flags
    mapped to console commands
  - New commands: `version`, `support`, `mesh-health`, `qr-all`,
    `seturl`, `pos-fields`, `ch-add`, `ch-del`, `ch-set`, `configure`,
    `set-canned-message`, `get-canned-message`, `set-ringtone`,
    `get-ringtone`, `gpio-rd`, `gpio-wr`, `gpio-wrb`, `gpio-watch`,
    `delete-file`, `ble-scan`, `reply`
  - Preset shortcuts: `ch-vlongslow`, `ch-longslow`, `ch-longfast`,
    `ch-medslow`, `ch-medfast`, `ch-shortslow`, `ch-shortfast`
- **Internationalization**
  - 230+ translation keys
  - 3 languages: Romanian (RO), English (EN), Spanish (ES)

### Changed
- `MeshtasticManager.messageAckReceived` now uses `Signal(dict)` instead
  of `Signal(int, str)` (works around a PySide6 6.11 slot-resolution bug)
- Unified message-send path: every successful send fires `messageSent`
  so the Messages tab is the single source of truth for rendering

### Fixed
- **Bug 20:** `Slot 'MessagesPage::_on_message_ack(int,QString)' not found`
  in PySide6 6.11 cross-thread queued connections
- **Bug 21:** `AttributeError: 'MessagesPage' object has no attribute
  'requestStartDM'` when right-clicking a message and choosing "Send DM"
- **Bug 22:** Console `set lora.region EU_868 …` crashed on multi-line
  paste (now splits and tokenizes correctly)
- **Bug 23:** `NameError: name 't' is not defined` in several console
  command handlers (i18n import was missing)
- **Bug 24:** `FieldDescriptor.label` AttributeError on protobuf 4.x+
  `_upb` backend (guarded with `getattr`)
- **Bug 25:** Message ACK status didn't update in stored dict when no
  bubble was rendered, causing wrong status when user switched convos
- Channel utilization counters didn't include the device's own
  measurements (now sampled from local TELEMETRY packets)
- `_coerce_value` stripped only leading/trailing whitespace; now also
  takes only the first whitespace-separated token for enum / numeric
  fields, making it tolerant of accidental multi-line pastes
- Auto-reconnect safety net (every 30 s) fires reconnect when the OS
  unfreezes after sleep — addresses Windows laptop wake-up scenarios

## [0.19.0] — 2026-05-10 (pre-release)

Internal development version. See git history for details.

[Unreleased]: https://github.com/<your-username>/meshtastic-desktop/compare/v0.20.0...HEAD
[0.20.0]: https://github.com/<your-username>/meshtastic-desktop/releases/tag/v0.20.0
