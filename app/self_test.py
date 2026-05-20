"""
Device self-test runner — pure logic, no UI.

Runs a series of ~15 diagnostic checks against the connected Meshtastic
device + this app's runtime, then yields a TestResult per check.

Design choices:
  • Each check is a self-contained function that takes the manager and
    returns a TestResult dict. Adding a new check = appending one entry
    to ALL_CHECKS at the bottom.
  • Checks are SAFE to run on any state — they verify connection first
    and emit SKIP results if the device isn't reachable rather than
    crashing.
  • Results have a numerical severity so the dialog can sort/filter:
        pass=0, info=1, skip=2, warn=3, fail=4.
  • "fix" string is shown as a one-line actionable hint underneath the
    result message. Keep it under ~120 chars.

Categories shown to the user (in this exact order in the UI):
    Software       — Python/library versions, app environment
    Connection     — Is the interface alive, recent activity
    Firmware/HW    — Device firmware, hardware model, stability
    LoRa config    — Region, preset, hop limit, TX
    Position       — Fixed position or GPS, broadcast cadence
    Telemetry      — Update intervals, sensors, recent samples
    Channels       — PRIMARY channel present, PSK sane
    Mesh           — Channel util, RX activity, neighbours
    Power          — Battery, voltage
"""

from __future__ import annotations

import logging
import sys
import time
import platform
from typing import Callable, List, Dict, Any, Optional

log = logging.getLogger("meshlink.self_test")


# --- Severity constants -----------------------------------------------------
PASS = "pass"
INFO = "info"
SKIP = "skip"
WARN = "warn"
FAIL = "fail"

_SEVERITY_ORDER = {PASS: 0, INFO: 1, SKIP: 2, WARN: 3, FAIL: 4}


def severity_rank(s: str) -> int:
    return _SEVERITY_ORDER.get(s, 0)


def make_result(name: str, status: str, message: str = "",
                fix: str = "", category: str = "") -> Dict[str, Any]:
    return {"name": name, "status": status, "message": message,
            "fix": fix, "category": category}


# ===========================================================================
# CHECKS — each one is a function(manager) -> TestResult dict
# ===========================================================================

# ── SOFTWARE ────────────────────────────────────────────────────────────────
def check_python_version(_mgr) -> Dict[str, Any]:
    v = sys.version_info
    msg = f"Python {v.major}.{v.minor}.{v.micro} on {platform.system()}"
    if v.major == 3 and v.minor < 10:
        return make_result("Python version", WARN, msg,
                           fix="Recommended Python 3.10+. Older versions "
                               "may have compatibility issues with PySide6.",
                           category="Software")
    return make_result("Python version", PASS, msg, category="Software")


def check_pyside_version(_mgr) -> Dict[str, Any]:
    v = None
    try:
        import PySide6
        v = getattr(PySide6, "__version__", None)
    except Exception as e:
        return make_result("PySide6 version", FAIL, f"Cannot import: {e}",
                           fix="Reinstall: pip install PySide6",
                           category="Software")
    if not v:
        # PySide6 doesn't always expose __version__; use packaging metadata
        try:
            import importlib.metadata
            v = importlib.metadata.version("PySide6")
        except Exception:
            v = "?"
    return make_result("PySide6 version", PASS, f"PySide6 {v}",
                       category="Software")


def check_meshtastic_lib(_mgr) -> Dict[str, Any]:
    try:
        import meshtastic
        v = getattr(meshtastic, "__version__", "?")
        if v == "?":
            try:
                import importlib.metadata
                v = importlib.metadata.version("meshtastic")
            except Exception:
                pass
        return make_result("meshtastic library", PASS,
                           f"meshtastic-python {v}",
                           category="Software")
    except Exception as e:
        return make_result("meshtastic library", FAIL, f"Cannot read: {e}",
                           fix="pip install -U meshtastic",
                           category="Software")


def check_optional_libs(_mgr) -> Dict[str, Any]:
    """Look for optional libs that improve features when present."""
    missing = []
    present = []
    for libname, feature in (
        ("bleak",        "BLE connection"),
        ("pyqtgraph",    "telemetry chart"),
        ("numpy",        "telemetry chart"),
        ("PySide6.QtWebEngineWidgets", "Map tab"),
        ("yaml",         "configure command"),
    ):
        try:
            __import__(libname)
            present.append(libname.split(".")[0])
        except Exception:
            missing.append(f"{libname} ({feature})")
    if not missing:
        return make_result("Optional libraries", PASS,
                           f"All present: {', '.join(present)}",
                           category="Software")
    return make_result("Optional libraries", INFO,
                       f"Missing: {'; '.join(missing)}",
                       fix="Some features will be hidden or limited. "
                           "Install via pip if you want them.",
                       category="Software")


# ── CONNECTION ──────────────────────────────────────────────────────────────
def check_connection_state(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Connection state", FAIL,
                           f"Not connected (state={mgr.state})",
                           fix="Connect via the bar at the top "
                               "(Wi-Fi / Bluetooth / USB).",
                           category="Connection")
    last_type = getattr(mgr, "_last_conn_type", "?")
    return make_result("Connection state", PASS,
                       f"Connected via {last_type}, state=ready",
                       category="Connection")


def check_recent_activity(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Recent device activity", SKIP, "Not connected",
                           category="Connection")
    h = mgr.get_mesh_health()
    last_age = h.get("rx_last_packet_age", -1)
    if last_age < 0:
        # No packets at all yet. Connection may be very fresh.
        sess = h.get("session_seconds", 0)
        if sess < 60:
            return make_result("Recent device activity", INFO,
                               f"Just connected ({sess}s ago); waiting "
                               "for first packet",
                               category="Connection")
        return make_result("Recent device activity", WARN,
                           f"No packets decoded yet in {sess}s of session",
                           fix="If the device is on but quiet, this can be "
                               "normal. Otherwise check Channel Util in "
                               "Mesh Health below.",
                           category="Connection")
    if last_age > 600:
        return make_result("Recent device activity", WARN,
                           f"Last packet {last_age//60}m ago",
                           fix="Long silence — mesh may genuinely be quiet, "
                               "or the radio link may have dropped.",
                           category="Connection")
    return make_result("Recent device activity", PASS,
                       f"Last packet {last_age}s ago",
                       category="Connection")


# ── FIRMWARE / HARDWARE ─────────────────────────────────────────────────────
def check_firmware(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Firmware version", SKIP, "Not connected",
                           category="Firmware/HW")
    iface = mgr.interface
    meta = getattr(iface, "metadata", None)
    mi = getattr(iface, "myInfo", None)
    fw = None
    if meta is not None:
        fw = getattr(meta, "firmware_version", None)
    if not fw and mi is not None:
        fw = getattr(mi, "firmware_version", None)
    if not fw:
        return make_result("Firmware version", WARN,
                           "Could not read firmware_version from device",
                           fix="Try a factory reset of the device or update "
                               "the firmware to the latest stable build.",
                           category="Firmware/HW")
    # Soft check: warn if firmware looks very old (<2.3.x)
    parts = str(fw).split(".")
    if len(parts) >= 2:
        try:
            major = int(parts[0]); minor = int(parts[1])
            if (major, minor) < (2, 3):
                return make_result("Firmware version", WARN, f"v{fw}",
                                   fix="Firmware older than 2.3 lacks several "
                                       "protocol features. Consider updating.",
                                   category="Firmware/HW")
        except ValueError:
            pass
    return make_result("Firmware version", PASS, f"v{fw}",
                       category="Firmware/HW")


def check_hardware_model(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Hardware model", SKIP, "Not connected",
                           category="Firmware/HW")
    meta = getattr(mgr.interface, "metadata", None)
    if not meta:
        return make_result("Hardware model", WARN, "No metadata from device",
                           category="Firmware/HW")
    hw_raw = getattr(meta, "hw_model", None)
    if hw_raw is None:
        return make_result("Hardware model", WARN, "hw_model unset",
                           category="Firmware/HW")
    try:
        from meshtastic.protobuf.mesh_pb2 import HardwareModel
        hw_name = HardwareModel.Name(int(hw_raw))
    except Exception:
        hw_name = str(hw_raw)
    return make_result("Hardware model", PASS, hw_name,
                       category="Firmware/HW")


def check_reboot_count(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Reboot count", SKIP, "Not connected",
                           category="Firmware/HW")
    mi = getattr(mgr.interface, "myInfo", None)
    if not mi:
        return make_result("Reboot count", SKIP, "No myInfo",
                           category="Firmware/HW")
    rb = getattr(mi, "reboot_count", None)
    if rb is None:
        return make_result("Reboot count", SKIP, "Not reported",
                           category="Firmware/HW")
    if rb > 500:
        return make_result("Reboot count", WARN, f"{rb} reboots",
                           fix="High reboot count may indicate instability "
                               "(brown-outs, watchdog resets). Check power "
                               "supply and antenna SWR.",
                           category="Firmware/HW")
    return make_result("Reboot count", PASS, f"{rb} reboots",
                       category="Firmware/HW")


# ── LORA CONFIG ─────────────────────────────────────────────────────────────
def check_lora_region(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("LoRa region", SKIP, "Not connected",
                           category="LoRa config")
    try:
        cfg = mgr.interface.localNode.localConfig
        region_enum = cfg.lora.region
        # region 0 = UNSET — radio TX disabled
        if int(region_enum) == 0:
            return make_result("LoRa region", FAIL, "UNSET",
                               fix="Set the region for your country, e.g. "
                                   "EU_868 (EU), US, ANZ, etc., via Console "
                                   "command: set-region EU_868",
                               category="LoRa config")
        try:
            from meshtastic.protobuf.config_pb2 import Config
            region_name = Config.LoRaConfig.RegionCode.Name(int(region_enum))
        except Exception:
            region_name = str(region_enum)
        return make_result("LoRa region", PASS, region_name,
                           category="LoRa config")
    except Exception as e:
        return make_result("LoRa region", WARN, f"Could not read: {e}",
                           category="LoRa config")


def check_lora_tx_enabled(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("LoRa TX enabled", SKIP, "Not connected",
                           category="LoRa config")
    try:
        cfg = mgr.interface.localNode.localConfig
        # In recent protobuf the field is `tx_enabled` (positive). Older
        # versions used `tx_disabled` — fall back if needed.
        if hasattr(cfg.lora, "tx_enabled"):
            tx_enabled = bool(cfg.lora.tx_enabled)
        else:
            tx_enabled = not bool(getattr(cfg.lora, "tx_disabled", False))
        if not tx_enabled:
            return make_result("LoRa TX enabled", FAIL, "TX disabled",
                               fix="Device is in RX-only mode — it won't "
                                   "transmit anything. Console: "
                                   "set lora.tx_enabled true",
                               category="LoRa config")
        return make_result("LoRa TX enabled", PASS, "TX active",
                           category="LoRa config")
    except Exception as e:
        return make_result("LoRa TX enabled", SKIP, f"{e}",
                           category="LoRa config")


def check_lora_hop_limit(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("LoRa hop limit", SKIP, "Not connected",
                           category="LoRa config")
    try:
        hl = int(mgr.interface.localNode.localConfig.lora.hop_limit)
    except Exception:
        return make_result("LoRa hop limit", SKIP, "Cannot read",
                           category="LoRa config")
    if hl == 0:
        return make_result("LoRa hop limit", FAIL, "hop_limit=0",
                           fix="With hop_limit=0 your packets won't be "
                               "forwarded. Console: set lora.hop_limit 3",
                           category="LoRa config")
    if hl > 7:
        return make_result("LoRa hop limit", WARN, f"hop_limit={hl}",
                           fix="hop_limit > 7 is wasteful and pollutes the "
                               "mesh. Recommended range: 3–5.",
                           category="LoRa config")
    return make_result("LoRa hop limit", PASS, f"hop_limit={hl}",
                       category="LoRa config")


# ── POSITION ───────────────────────────────────────────────────────────────
def check_position(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Position", SKIP, "Not connected",
                           category="Position")
    iface = mgr.interface
    # Look for the local node's position
    my_id = mgr.my_node_id
    nodes = getattr(iface, "nodes", None) or {}
    n = nodes.get(my_id) if my_id else None
    pos = (n or {}).get("position") or {}
    lat = pos.get("latitude")
    lon = pos.get("longitude")
    if lat is None or lon is None:
        return make_result("Position", WARN, "No position yet",
                           fix="Set a fixed position via the Console "
                               "(set-position <lat> <lon> <alt>) or attach "
                               "a GPS module.",
                           category="Position")
    return make_result("Position", PASS,
                       f"{lat:.4f}, {lon:.4f}",
                       category="Position")


# ── TELEMETRY ───────────────────────────────────────────────────────────────
def check_telemetry_interval(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Telemetry interval", SKIP, "Not connected",
                           category="Telemetry")
    try:
        mc = mgr.interface.localNode.moduleConfig
        iv = int(mc.telemetry.device_update_interval)
    except Exception:
        return make_result("Telemetry interval", SKIP, "Cannot read",
                           category="Telemetry")
    if iv == 0:
        return make_result("Telemetry interval", INFO,
                           "Using default (~30 min)",
                           category="Telemetry")
    if iv >= 2147483640:
        # MAX_INT or near — the factory-reset bug
        return make_result("Telemetry interval", FAIL,
                           f"interval={iv} (effectively disabled)",
                           fix="Factory-reset default leaves this at MAX_INT. "
                               "Set it to 900 (15 minutes) via Console: "
                               "set telemetry.device_update_interval 900",
                           category="Telemetry")
    if iv > 86400:
        return make_result("Telemetry interval", WARN,
                           f"interval={iv}s (>24h)",
                           fix="Interval >24h means almost no telemetry. "
                               "Recommended 900–3600s.",
                           category="Telemetry")
    return make_result("Telemetry interval", PASS, f"{iv}s",
                       category="Telemetry")


def check_telemetry_freshness(mgr) -> Dict[str, Any]:
    """Has the device actually broadcast telemetry recently?"""
    if not mgr.is_connected:
        return make_result("Telemetry freshness", SKIP, "Not connected",
                           category="Telemetry")
    h = mgr.get_mesh_health()
    cu_last = h.get("channel_util_last", -1)
    if cu_last < 0:
        sess = h.get("session_seconds", 0)
        if sess < 120:
            return make_result("Telemetry freshness", INFO,
                               f"Waiting for first sample (session={sess}s)",
                               category="Telemetry")
        return make_result("Telemetry freshness", WARN,
                           f"No telemetry samples in {sess}s",
                           fix="Device may not be broadcasting telemetry — "
                               "check Telemetry module config "
                               "(device_telemetry_enabled, interval).",
                           category="Telemetry")
    return make_result("Telemetry freshness", PASS,
                       f"Last channel-util sample present",
                       category="Telemetry")


# ── CHANNELS ────────────────────────────────────────────────────────────────
def check_primary_channel(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("PRIMARY channel", SKIP, "Not connected",
                           category="Channels")
    try:
        ch_list = list(mgr.interface.localNode.channels or [])
    except Exception:
        return make_result("PRIMARY channel", SKIP, "Cannot read",
                           category="Channels")
    primary = [c for c in ch_list
               if int(getattr(c, "role", 0) or 0) == 1]
    if not primary:
        return make_result("PRIMARY channel", FAIL, "No PRIMARY channel",
                           fix="Every Meshtastic device must have one PRIMARY "
                               "channel. Configure via Channels tab.",
                           category="Channels")
    p = primary[0]
    name = ""
    if getattr(p, "settings", None) and p.settings.name:
        name = p.settings.name
    return make_result("PRIMARY channel", PASS,
                       name or "(default LongFast)",
                       category="Channels")


def check_channels_count(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Active channels", SKIP, "Not connected",
                           category="Channels")
    try:
        ch_list = list(mgr.interface.localNode.channels or [])
        active = sum(1 for c in ch_list
                     if int(getattr(c, "role", 0) or 0) != 0)
    except Exception:
        return make_result("Active channels", SKIP, "Cannot read",
                           category="Channels")
    return make_result("Active channels", INFO,
                       f"{active} active (max 8)",
                       category="Channels")


# ── MESH HEALTH ─────────────────────────────────────────────────────────────
def check_channel_util(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Channel utilization", SKIP, "Not connected",
                           category="Mesh")
    h = mgr.get_mesh_health()
    cu = h.get("channel_util_avg", -1)
    if cu < 0:
        return make_result("Channel utilization", SKIP,
                           "No samples yet", category="Mesh")
    if cu > 25:
        return make_result("Channel utilization", FAIL,
                           f"avg {cu:.1f}% (CRITICAL)",
                           fix="Channel is saturated. Either RF interference, "
                               "too many talkative nodes, or wrong preset. "
                               "Check Mesh Health diagnostic above.",
                           category="Mesh")
    if cu > 10:
        return make_result("Channel utilization", WARN, f"avg {cu:.1f}%",
                           fix="Channel quite busy. Reduce broadcast "
                               "intervals on chatty nodes.",
                           category="Mesh")
    return make_result("Channel utilization", PASS, f"avg {cu:.1f}%",
                       category="Mesh")


def check_neighbours_heard(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Neighbours heard", SKIP, "Not connected",
                           category="Mesh")
    h = mgr.get_mesh_health()
    n1 = h.get("rx_unique_nodes_1h", 0)
    n24 = h.get("rx_unique_nodes_24h", 0)
    if n24 == 0:
        sess = h.get("session_seconds", 0)
        if sess < 600:
            return make_result("Neighbours heard", INFO,
                               f"Session only {sess}s — too early to tell",
                               category="Mesh")
        return make_result("Neighbours heard", WARN,
                           "0 in 24h",
                           fix="No neighbours heard. Likely causes: wrong "
                               "region (RF mismatch), wrong PSK, or no nodes "
                               "in range. Verify region matches your area.",
                           category="Mesh")
    return make_result("Neighbours heard", PASS,
                       f"{n1} (1h) / {n24} (24h)",
                       category="Mesh")


def check_interference_pattern(mgr) -> Dict[str, Any]:
    """Diagnose RF interference / PSK mismatch."""
    if not mgr.is_connected:
        return make_result("Interference check", SKIP, "Not connected",
                           category="Mesh")
    h = mgr.get_mesh_health()
    cu = h.get("channel_util_avg", -1)
    rx_1h_total = sum(p.get("1h", 0) for p in h.get("rx_by_port", {}).values())
    if cu < 0:
        return make_result("Interference check", SKIP, "No data yet",
                           category="Mesh")
    if cu >= 10 and rx_1h_total == 0:
        return make_result("Interference check", FAIL,
                           f"util={cu:.0f}% but ZERO decoded packets",
                           fix="RF interference on 868/915 MHz, OR your PSK "
                               "doesn't match the rest of the mesh. Check "
                               "your channel's PSK matches your local mesh.",
                           category="Mesh")
    return make_result("Interference check", PASS,
                       f"No interference pattern detected",
                       category="Mesh")


# ── POWER ──────────────────────────────────────────────────────────────────
def check_battery(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Battery", SKIP, "Not connected",
                           category="Power")
    my_id = mgr.my_node_id
    nodes = getattr(mgr.interface, "nodes", None) or {}
    n = nodes.get(my_id) if my_id else None
    dm = (n or {}).get("deviceMetrics") or {}
    bat = dm.get("batteryLevel")
    if bat is None:
        return make_result("Battery", SKIP, "No reading yet",
                           category="Power")
    if bat > 100:
        return make_result("Battery", PASS, "USB powered",
                           category="Power")
    if bat < 15:
        return make_result("Battery", FAIL, f"{bat}% (CRITICAL)",
                           fix="Charge or replace battery soon. Device may "
                               "brown-out and corrupt config flash.",
                           category="Power")
    if bat < 30:
        return make_result("Battery", WARN, f"{bat}%",
                           fix="Battery getting low — charge soon.",
                           category="Power")
    return make_result("Battery", PASS, f"{bat}%",
                       category="Power")


def check_voltage(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Voltage", SKIP, "Not connected",
                           category="Power")
    my_id = mgr.my_node_id
    nodes = getattr(mgr.interface, "nodes", None) or {}
    n = nodes.get(my_id) if my_id else None
    dm = (n or {}).get("deviceMetrics") or {}
    v = dm.get("voltage")
    if v is None:
        return make_result("Voltage", SKIP, "No reading yet",
                           category="Power")
    if v < 3.0:
        return make_result("Voltage", FAIL, f"{v:.2f} V (UNDER-VOLT)",
                           fix="Below 3.0V the radio behaves erratically. "
                               "Charge the battery now.",
                           category="Power")
    if v > 4.5:
        return make_result("Voltage", WARN, f"{v:.2f} V (over-voltage)",
                           fix="Likely USB powered or telemetry glitch.",
                           category="Power")
    return make_result("Voltage", PASS, f"{v:.2f} V",
                       category="Power")


def check_air_util(mgr) -> Dict[str, Any]:
    if not mgr.is_connected:
        return make_result("Air util TX", SKIP, "Not connected",
                           category="Power")
    my_id = mgr.my_node_id
    nodes = getattr(mgr.interface, "nodes", None) or {}
    n = nodes.get(my_id) if my_id else None
    dm = (n or {}).get("deviceMetrics") or {}
    au = dm.get("airUtilTx")
    if au is None:
        return make_result("Air util TX", SKIP, "No reading yet",
                           category="Power")
    # EU regulations: 1% duty cycle on 868 MHz typically
    if au > 10:
        return make_result("Air util TX", FAIL, f"{au:.2f}% (regulatory)",
                           fix="Above 10% you're likely violating regional "
                               "duty cycle. Reduce broadcast intervals.",
                           category="Power")
    if au > 3:
        return make_result("Air util TX", WARN, f"{au:.2f}%",
                           fix="Approaching EU 1% duty-cycle limit. "
                               "Reduce telemetry/position intervals.",
                           category="Power")
    return make_result("Air util TX", PASS, f"{au:.2f}%",
                       category="Power")


# ===========================================================================
# CHECK REGISTRY
# ===========================================================================
ALL_CHECKS: List[Callable] = [
    # Software
    check_python_version,
    check_pyside_version,
    check_meshtastic_lib,
    check_optional_libs,
    # Connection
    check_connection_state,
    check_recent_activity,
    # Firmware/HW
    check_firmware,
    check_hardware_model,
    check_reboot_count,
    # LoRa config
    check_lora_region,
    check_lora_tx_enabled,
    check_lora_hop_limit,
    # Position
    check_position,
    # Telemetry
    check_telemetry_interval,
    check_telemetry_freshness,
    # Channels
    check_primary_channel,
    check_channels_count,
    # Mesh
    check_channel_util,
    check_neighbours_heard,
    check_interference_pattern,
    # Power
    check_battery,
    check_voltage,
    check_air_util,
]


def run_all(mgr, progress_cb: Optional[Callable[[int, int, str], None]] = None
            ) -> List[Dict[str, Any]]:
    """Run every check in ALL_CHECKS and return the result list.

    progress_cb is called as progress_cb(done, total, current_name) so the
    UI can update a progress bar between checks.
    """
    results: List[Dict[str, Any]] = []
    total = len(ALL_CHECKS)
    for i, fn in enumerate(ALL_CHECKS, start=1):
        try:
            r = fn(mgr)
        except Exception as e:
            log.exception(f"Check {fn.__name__} crashed")
            r = make_result(fn.__name__, FAIL,
                            f"Check crashed: {type(e).__name__}: {e}",
                            category="(internal)")
        results.append(r)
        if progress_cb:
            try:
                progress_cb(i, total, r["name"])
            except Exception:
                pass
    return results


def summary(results: List[Dict[str, Any]]) -> Dict[str, int]:
    """Return a count-by-severity dict for a results list."""
    out = {PASS: 0, INFO: 0, SKIP: 0, WARN: 0, FAIL: 0}
    for r in results:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out
