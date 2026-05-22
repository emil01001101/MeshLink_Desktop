# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
