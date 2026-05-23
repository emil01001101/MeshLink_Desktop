# MeshLink Desktop

<p align="center">
  <strong>A complete, open-source desktop client for Meshtastic® LoRa mesh radios — built with Python and Qt.

> **MeshLink Desktop** is an independent, community-built project.
> It is not affiliated with or endorsed by Meshtastic LLC.
> Meshtastic® is a registered trademark of Meshtastic LLC.</strong>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white"/>
  <img alt="PySide6" src="https://img.shields.io/badge/PySide6-6.6%2B-41cd52?logo=qt&logoColor=white"/>
  <img alt="Meshtastic" src="https://img.shields.io/badge/meshtastic-2.3%2B-67ea94"/>
  <img alt="License" src="https://img.shields.io/badge/license-GPL--3.0-blue"/>
  <img alt="Platforms" src="https://img.shields.io/badge/platforms-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey"/>
  <img alt="Version" src="https://img.shields.io/badge/version-v0.45.0-green"/>
</p>

<p align="center">
  <a href="#what-is-this">About</a> ·
  <a href="#features">Features</a> ·
  <a href="#screenshots">Screenshots</a> ·
  <a href="#installation">Installation</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#usage-guide">Usage Guide</a> ·
  <a href="#license">License</a>
</p>

---

## What is this?

**MeshLink Desktop** is a feature-complete, cross-platform desktop GUI for
[Meshtastic](https://meshtastic.org) LoRa mesh radios. It connects to your
radio over **TCP/IP (Wi-Fi)**, **USB serial**, or **Bluetooth Low Energy** and
gives you a full chat client, mesh dashboard, device configurator, and
automation engine — all without leaving your computer.

It implements the entire Meshtastic Python CLI surface inside an interactive
GUI, adds a visual script editor for automating broadcasts, and includes a
23-point hardware self-test system for quick diagnostics.

> **Not affiliated with the Meshtastic project.**  
> This is an independent client built on the official
> [meshtastic-python](https://github.com/meshtastic/python) library.

---

## Features

### 🔗 Connection

- **Three connection methods** in one click: TCP/IP (Wi-Fi), USB serial, Bluetooth (BLE)
- **Smart serial port scanner** — identifies Meshtastic-compatible devices by USB chip
  (CP210x, CH340, FT232, ESP32 native USB) and highlights them at the top of the list
- **BLE device scanner** — scans nearby Bluetooth devices, filters Meshtastic nodes,
  auto-selects the strongest signal
- **Auto-reconnect** with exponential back-off (3 s → 6 s → 12 s → 30 s) that survives
  Wi-Fi router reboots, cable reinsertions and device restarts
- Persistent "last connection" memory — reconnects on next launch without any setup
- Graceful stop after repeated failures: after 5 locked serial attempts or 8 failed BLE
  scans the app pauses auto-reconnect and shows a clear resolution hint

---

### 💬 Messages

- **Real-time group chat** on every channel your device is configured for
- **Private / direct messages** (DMs) to any individual node in the mesh
- **Threaded replies** — quote the message you're responding to
- **Emoji reactions** — tap a bubble to add a reaction chip visible to everyone
- **Delivery status tracking** per message:
  - Sent → Pending → Delivered (per-relay ACK) → Failed
  - Click any sent message for a full delivery report: which nodes forwarded it,
    SNR/RSSI at each hop, and how many nodes were active near you at send time
- **Signal-report auto-reply** — the app can automatically reply with your SNR/RSSI
  when it receives a signal-check message
- **Persistent history** stored in a local SQLite database; survives app restarts
- Messages sent from Scripts or the Console appear in the correct conversation,
  exactly as if you had typed them

---

### 🌐 Nodes

- Live node list with signal bars (SNR-based), last-seen time, and battery level
- Expand any node card for full detail: lat/lon, hardware, firmware version, public key,
  channel utilization, air utilization, uptime
- **Neighbor topology** — shows 1-hop neighbours for each node
- Sort by: name, signal strength (SNR), last seen, distance
- Filter by name or node ID
- **Own node** clearly distinguished (no misleading "signal unknown" label)
- Start a DM to any node with one click

---

### 📊 Info & Mesh Health

- Device dashboard cards: battery %, voltage, uptime, channel utilization, air util TX
- **24-hour telemetry chart** — plot battery, voltage, channel utilization, air TX, uptime
  over time; toggle to environment metrics (temperature, humidity, pressure, IAQ) if your
  hardware has a sensor
- **Mesh Health panel** (live, updates every second):
  - Channel-utilization sparkline for the last 60 minutes (colour-coded: green < 5 %,
    orange 5–15 %, red > 15 %)
  - RX packets broken down by type (text, position, telemetry, node-info, routing, other)
    with 1 h and 24 h windows
  - Unique neighbours heard in the last 1 h and 24 h
  - Time since last decoded packet / last text message
  - **Automatic diagnostic hint** that distinguishes three situations:
    - Channel quiet + zero RX → "mesh genuinely silent"
    - Channel busy + zero RX → "⚠ RF interference or PSK mismatch"
    - Normal activity → "✓ Mesh active"
- **Position panel** with altitude, source (GPS / fixed / manual) and a link to
  OpenStreetMap
- Owner name editor and basic LoRa config (region, preset, hop limit) directly from
  the Info tab

---

### 🩺 Device Self-Test

A one-click diagnostic that runs **23 checks** against the connected device and
the app's runtime environment. Safe to run at any time — no transmissions, no writes.

Checks cover:

| Category | Checks |
|---|---|
| **Software** | Python version, PySide6, meshtastic-python, optional libraries |
| **Connection** | State, recent activity |
| **Firmware/HW** | Version, hardware model, reboot count |
| **LoRa config** | Region set, TX enabled, hop limit range |
| **Position** | Fixed or GPS, broadcast cadence |
| **Telemetry** | Update interval (catches factory-reset MAX_INT bug), freshness |
| **Channels** | PRIMARY channel present, active channel count |
| **Mesh** | Channel utilization, neighbours heard, interference pattern |
| **Power** | Battery level, voltage, air util TX vs EU duty-cycle limit |

Results are colour-coded (✓ pass / ℹ info / — skip / ⚠ warn / ✗ fail). Every
warning and failure includes a **one-line fix** suggestion. The full report can be
copied to the clipboard for sharing in bug reports or Discord.

---

### 🗺 Map

- Interactive Leaflet / OpenStreetMap view rendered inside the app
- Every node with a known position is plotted; click for the full node detail
- Your own node highlighted separately
- No external account or API key required

---

### 🧩 Modules (Firmware Configuration)

Thirteen sub-tabs that read and write Meshtastic module configuration directly
from the device. All fields are **auto-generated from the protobuf descriptors** —
booleans become checkboxes, integers become spin-boxes, enums become drop-downs —
so the UI always matches the firmware version you have installed.

| Module | Fields | Purpose |
|---|---|---|
| MQTT | 10 | Bridge to MQTT broker; proxy-to-client mode |
| Serial | 8 | Serial port passthrough / external modules |
| External notification | 15 | LED / buzzer / vibration on message receive |
| Store & forward | 6 | Message store-and-forward router |
| Range test | 4 | Automated range test + live stats panel (SNR/RSSI/packet loss) |
| **Telemetry** | **15** | Device + environment sensor intervals and screen display |
| Neighbor info | 3 | Periodic 1-hop topology broadcasts |
| Detection sensor | 8 | GPIO-based motion / presence detection |
| Audio (codec2) | 7 | Experimental voice-over-LoRa |
| Canned messages | 11 | Pre-defined quick-reply phrases |
| Remote hardware | 3 | Remote GPIO pin control |
| Ambient lighting | 5 | WS2812 / NeoPixel LED colour and brightness |
| Pax counter | 4 | Crowd estimation via passive BLE / Wi-Fi probe counting |

---

### # Channel Management

- Visual list of all 8 channel slots with role (PRIMARY / SECONDARY / DISABLED)
- **Add, edit, and delete channels** through a dialog
- PSK modes: default (LongFast cleartext), random AES-256, or custom (paste base64
  or hex key)
- MQTT uplink / downlink toggles per channel
- Position-precision selector (how accurately your location is shared on each channel)

---

### 🤖 Automation Scripts

A Python-based scripting engine that runs your code in background threads and
delivers the results (including any `send_text()` calls) to the mesh.

**What you can do in a script:**

```python
# No imports needed — the API is injected automatically

env = local_env()           # temperature, humidity, pressure, IAQ, gas resistance
dev = local_device()        # battery, voltage, channel utilization, air util

if "temperature" in env:
    msg = f"🌡 {env['temperature']:.1f}°C  💧 {env['relativeHumidity']:.0f}%"
    send_text(msg)          # goes to the channels selected in the UI
```

**Features:**
- **Scheduler** — run every N seconds / minutes / hours / days
- **Channel selector** per script — pick which channels receive the message
- **Broadcast or DM** mode per script (with node picker)
- **Six quick-insert snippet buttons** — send_text, env metrics, device metrics,
  list nodes, current time, full template
- **Output panel** — see print() and log() output from each run
- **One-click test** — run any script immediately without waiting for the schedule
- Built-in API: `send_text`, `send_dm`, `local_env`, `local_device`, `local_position`,
  `channels`, `channel_by_name`, `list_nodes`, `get_node`, `log`, `is_connected`,
  `my_node_id`, `my_channels`

A ready-to-use **Environment Telemetry** example is included: posts temperature,
humidity, pressure, IAQ, battery and voltage to LongFast every 6 hours (disabled
by default; enable when you're ready).

---

### ⌨ Console (Full CLI parity)

A terminal-style tab with **65+ commands** covering the full Meshtastic Python CLI:

```
Node info & config:   info, support, nodes, set, get, seturl, configure
Owner:                set-owner-long, set-owner-short
Position:             set-position, pos-fields
LoRa:                 set-region, set-preset, set-power, set-hop-limit
Channels:             channels, ch-add, ch-del, ch-set, qr, qr-all
Messages:             sendtext, send, reply, canned, set-canned-message
GPIO:                 gpio-rd, gpio-wr, gpio-wrb, gpio-watch
Files:                delete-file
BLE:                  ble-scan
Diagnostics:          mesh-health, stats, version
Scripts/misc:         clear, help
```

Type `help` for the full list with descriptions. All commands work exactly
as their CLI equivalents, with autocomplete history and multi-line paste support.

---

### ⚙ Settings

- Language selector: **English, Romanian, Spanish** (applied live without restart)
- **Dark / Light theme toggle** (☀ / 🌙 button in the status bar); preference saved
- Sound notifications on/off
- Save chat history on/off
- Connection persistence (last-used target remembered across restarts)

---

## Screenshots

> 📸 Screenshots are stored in `docs/screenshots/` — add yours after a first run.

| | |
|---|---|
| **Messages** — replies, reactions, delivery status | **Info / Mesh Health** — live sparkline + diagnostic |
| **Nodes** — signal bars, expand for full detail | **Map** — all node positions on OSM |
| **Modules** — 13 tabs, all fields from protobuf | **Scripts** — scheduler + channel picker |
| **Console** — 65+ CLI commands | **Self-Test** — 23 diagnostic checks |

---

## Installation

### Requirements

- **Python 3.10+** ([python.org](https://www.python.org/downloads/))
- A Meshtastic radio running firmware **≥ 2.3**
  (Heltec V3, T-Beam, T-Echo, RAK4631, LilyGo T-Deck, …)
- Connection method: USB cable, Wi-Fi (same LAN), or Bluetooth

### Windows (recommended)

```cmd
git clone https://github.com/emil01001101/MeshLink_Desktop.git
cd meshlink_desktop
run.bat
```

`run.bat` automatically installs missing dependencies on the first run.

### Linux / macOS

```bash
git clone https://github.com/emil01001101/MeshLink_Desktop.git
cd meshlink_desktop
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

On Linux you may also need to add yourself to the `dialout` group for
serial access: `sudo usermod -aG dialout $USER` (log out and back in).

### Optional extras

```bash
pip install PySide6-WebEngine   # Map tab (Leaflet/OpenStreetMap)
pip install bleak                # Bluetooth (BLE) connection
pip install PyYAML               # Console 'configure' command
pip install pyqtgraph numpy      # Telemetry chart
```

### Portable EXE (Windows, no Python needed)

```powershell
pip install pyinstaller
pyinstaller --onefile --windowed --name MeshLinkDesktop `
  --collect-all meshtastic --collect-all PySide6 --collect-all bleak `
  --hidden-import google.protobuf main.py
# Output: dist\MeshLinkDesktop.exe  (~250 MB, self-contained)
```

---

## Quick Start

1. **Launch the app.** A dark-themed window opens.
2. **Pick a connection type** in the top bar: `TCP`, `Serial`, or `BLE`.
3. **Connect:**
   - *TCP/IP* — type your radio's IP address and port (e.g. `10.10.10.187:4403`)
   - *Serial* — click 🔍 to open the port scanner; your Heltec/T-Beam will appear
     at the top marked as "likely Meshtastic"
   - *BLE* — click 🔍 to scan; devices named `Meshtastic_xxxx` appear first
4. The status bar turns green and says **Connected**.
5. Channels and nodes download automatically — you'll see them in 5–10 seconds.
6. Go to **Messages** to chat, **Info** to check mesh health, or **Console** to
   configure your device.

**First-time device setup after a factory reset:**

```
# Paste each line into the Console tab, one at a time:
set-owner-long  "Your Node Name"
set-owner-short "YRNM"
set-region EU_868          # or US, AU_915, etc. — MUST be set!
set-preset LONG_FAST
set lora.hop_limit 3
set-position 51.5074 -0.1278 10    # lat lon altitude_m
set telemetry.device_update_interval 900
set device.node_info_broadcast_secs 900
```

---

## Usage Guide

### Connecting to your radio

The app remembers your last connection. On subsequent launches just press
**Connect** — the previous target is pre-filled.

**TCP/IP** is the most reliable connection on Windows: plug the radio into
USB, let it obtain a DHCP address on your LAN, and connect via IP. You can
find the IP in the Meshtastic Android/iOS app or in your router's DHCP table.

**Serial** requires no Wi-Fi, works offline. The 🔍 scanner identifies your
Meshtastic board by its USB chip VID:PID (CP210x for Heltec, CH340 for many
others). If "Access denied" appears, close any other app holding the port
(Arduino IDE Serial Monitor, another Python session) or re-plug the cable.

**BLE** works well but takes ~15 seconds to establish. The device must be
paired in Windows Bluetooth Settings first.

### Sending a message

- Go to the **Messages** tab
- Select a **channel** (or a DM conversation) in the left panel
- Type in the input box at the bottom; press Enter or click Send
- A bubble appears instantly; the status icon changes as ACKs arrive
- To **reply** to a specific message: hover it and click the ↩ icon
- To **react**: click 😊 on any bubble and pick an emoji

### Running the self-test

Open **Info tab → 🩺 Run device self-test**.

Results appear grouped by category. Each warning or failure includes a
suggested fix. Use the **📋 Copy report** button to paste the result into
a bug report or Discord message.

### Automating a message (example: temperature every 6 hours)

1. Go to the **Scripts** tab
2. Open the built-in *"Environment telemetry (example)"* script
3. Verify the **Send to** channels match your mesh
4. Click **▶ Run Now** to test — the message appears in the Messages tab
5. Tick **Enabled** and click **💾 Save**

The scheduler runs it every 6 hours in the background.

### Configuring firmware modules

Go to the **Modules** tab and pick a sub-tab. The form is auto-generated
from the firmware's protobuf schema. Change values and click **Save** —
the app writes the updated config to the device and triggers a soft restart.

**Important:** the **Telemetry** module controls `device_update_interval`.
After a factory reset this defaults to `2147483647` (MAX_INT, effectively
disabled). Set it to `900` (15 minutes) so the Info dashboard and Mesh
Health panel show live data.

---

## Where your data lives

```
~/meshlink_desktop_logs/         (Windows: C:\Users\<you>\meshlink_desktop_logs\)
├── meshlink_desktop_*.log       per-session debug log (last 30 days)
├── messages.db                    chat history (SQLite)
├── telemetry.db                   24h device metrics (SQLite)
└── scripts.db                     your automation scripts (SQLite)

App settings:
  Windows: HKCU\Software\MeshLinkDesktop   (Qt QSettings)
  Linux:   ~/.config/MeshLinkDesktop.ini
  macOS:   ~/Library/Preferences/MeshLinkDesktop.plist
```

Nothing leaves your computer unless you explicitly enable the MQTT bridge
in the Modules tab.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│                     Qt main thread                          │
│                                                             │
│   Pages: Messages · Nodes · Info · Map · Channels ·         │
│           Scripts · Modules · Console · Settings            │
│                  │ signals/slots │                          │
│         ┌────────▼───────────────▼──────────┐               │
│         │       MeshtasticManager           │               │
│         │  signals · mesh-health counters   │               │
│         │  SQLite stores (msg/telem/script)  │               │
│         └────────┬───────────────┬──────────┘               │
└──────────────────┼───────────────┼─────────────────────────┘
                   │ QueuedConnection (thread-safe)
         ┌─────────▼──────────┐   ┌──────────▼──────────┐
         │  pubsub thread      │   │  script threads      │
         │  meshtastic-python  │   │  (one per run)       │
         └─────────────────────┘   └──────────────────────┘
```

Cross-thread signals use `Signal(dict)` (not `Signal(int, str)`) to work
around a PySide6 6.11 metaobject type-lookup bug in queued connections.
Full design notes are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Tested hardware

| Board | Chip | Connection | Notes |
|---|---|---|---|
| Heltec WiFi LoRa 32 V3 | ESP32-S3 | TCP, Serial (CP210x), BLE | Primary test device |
| LILYGO T-Beam | ESP32 | TCP, Serial (CP210x) | |
| LILYGO T-Echo | nRF52840 | BLE, Serial (CH341) | |
| RAK4631 | nRF52840 | Serial (FTDI) | |

Firmware tested: 2.3.x through 2.7.x.

---

## Contributing

Bug reports, feature requests, and pull requests are welcome!

- **Bugs:** open an issue with the log file from `~/meshlink_desktop_logs/`
  and the output of **Info → 🩺 Self-test → 📋 Copy report**
- **Features:** open an issue first to discuss the approach
- **PRs:** one feature per PR; run `python -m py_compile app/**/*.py` before submitting

See [CONTRIBUTING.md](CONTRIBUTING.md) for dev setup details.

---

## Authors & Acknowledgments

Built by **Emil M.** (human author, copyright holder) with extensive AI coding
assistance from **Claude (Anthropic)**. Architecture decisions, hardware testing,
and direction were Emil's; Claude generated and refactored code under Emil's review.

Thanks to:
- The [Meshtastic project](https://meshtastic.org) for firmware, protocol and
  the [`meshtastic-python`](https://github.com/meshtastic/python) library
- [Qt for Python / PySide6](https://www.qt.io/qt-for-python)
- [PyQtGraph](https://www.pyqtgraph.org) for telemetry charts
- The Iberian Meshtastic mesh community for real-world testing

---

## License

**[GPL-3.0-only](LICENSE)** © 2026 Emil M.

This project is copyleft because it links against
[`meshtastic-python`](https://github.com/meshtastic/python) which is GPL-3.0.
Any redistribution or derivative work must also be GPL-3.0 and include source code.

If you distribute a compiled executable, you must provide a link to this
repository (a note in the About dialog is sufficient).

See [NOTICE](NOTICE) for full third-party attributions.

---

## Disclaimer

This software is provided "as is", without warranty of any kind.
The author is not responsible for any consequences of using the software,
including damage to radio hardware caused by misconfiguration through the
Modules or Console tabs.
**Always verify your regional LoRa regulations before transmitting**,
especially TX power and duty-cycle limits (EU 868 MHz: 1 % duty cycle on
most sub-bands).
