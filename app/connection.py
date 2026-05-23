"""
Robust Meshtastic connection manager.

Imbunatatiri fata de versiunea anterioara:
  • Toate evenimentele pubsub trec prin metaObject.invokeMethod ca sa fie
    rulate pe Qt main thread, nu pe threadul callback-ului pubsub
  • Connection state machine cu pasi vizibili (idle -> opening -> waiting_config
    -> loading_nodes -> ready -> failed)
  • Try/except in JURUL fiecarui callback ca o exceptie sa nu opreasca
    intregul sistem pubsub
  • Logging detaliat la fiecare pas (vizibil in Debug tab)
  • Retry mechanism: daca dupa N secunde nu primim config, retransmitem cererea
  • Public API curat (fara _underscored methods folosite din UI)
"""

from __future__ import annotations

import time
import logging
import threading
from typing import Optional, Any, List

from PySide6.QtCore import (
    QObject, Signal, QThread, QTimer, Qt, QMetaObject, Q_ARG, Slot
)

from .i18n import t

log = logging.getLogger("meshlink.connection")


def num_to_id(num) -> Optional[str]:
    """Convert node number (int) to '!hex' id - public utility."""
    if num is None:
        return None
    try:
        return f"!{int(num):08x}"
    except Exception:
        return None


def id_to_num(node_id: str) -> Optional[int]:
    if not node_id or not isinstance(node_id, str) or not node_id.startswith("!"):
        return None
    try:
        return int(node_id[1:], 16)
    except Exception:
        return None


def _to_camel(name: str) -> str:
    """snake_case -> camelCase. 'battery_level' -> 'batteryLevel'."""
    if "_" not in name:
        return name
    parts = name.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] if p else "" for p in parts[1:])


def normalize_keys(obj):
    """
    Normalizeaza RECURSIV toate cheile dict-urilor la camelCase.
    Necesar pentru ca biblioteca meshtastic-python returneaza unele campuri
    in snake_case (ex: 'device_metrics', 'battery_level', 'latitude_i')
    iar codul nostru se asteapta la camelCase ('deviceMetrics', 'batteryLevel',
    'latitudeI').
    """
    if isinstance(obj, dict):
        return {_to_camel(k) if isinstance(k, str) else k: normalize_keys(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [normalize_keys(x) for x in obj]
    return obj


# ===========================================================================
# Connect worker - thread separat pentru deschiderea conexiunii (blocant)
# ===========================================================================
class _ConnectWorker(QThread):
    """Deschide interfata pe un thread separat ca sa nu blocheze UI-ul."""

    progress  = Signal(str)           # progress message
    succeeded = Signal(object)        # created interface
    failed    = Signal(str)           # mesaj de eroare

    def __init__(self, conn_type: str, target: str, parent=None):
        super().__init__(parent)
        self.conn_type = conn_type
        self.target = target

    def run(self):
        try:
            iface = None

            if self.conn_type == "serial":
                self.progress.emit("Deschid portul serial…")
                from meshtastic.serial_interface import SerialInterface
                if self.target:
                    iface = SerialInterface(devPath=self.target)
                else:
                    iface = SerialInterface()

            elif self.conn_type == "tcp":
                raw = (self.target or "").strip() or "localhost"
                # suport "host:port"
                host = raw
                port = 4403
                if ":" in raw:
                    host, _, port_str = raw.rpartition(":")
                    try:
                        port = int(port_str)
                    except ValueError:
                        host, port = raw, 4403
                if port != 4403:
                    log.warning(
                        f"TCP port {port} is not the Meshtastic default "
                        f"(4403). If the connection is refused, try 4403.")
                self.progress.emit(f"Conectez TCP la {host}:{port}…")
                from meshtastic.tcp_interface import TCPInterface
                # A more generous handshake timeout helps devices on weak
                # WiFi finish the Meshtastic protocol handshake (the library
                # default can be too short → "Timed out waiting for
                # connection completion"). Fall back gracefully on older
                # library versions that don't accept these kwargs.
                try:
                    iface = TCPInterface(hostname=host, portNumber=port,
                                         timeout=20)
                except TypeError:
                    try:
                        iface = TCPInterface(hostname=host, portNumber=port)
                    except TypeError:
                        # versiuni mai vechi nu accepta portNumber
                        iface = TCPInterface(hostname=host)

            elif self.conn_type == "ble":
                from meshtastic.ble_interface import BLEInterface
                tgt = (self.target or "").strip()
                # V20-turn9: meshtastic-python 2.5+ removed auto-scan from
                # the BLEInterface constructor — address is now required.
                # If the user didn't supply one, we instruct them to click
                # the "🔍 Scan" button in the connection bar instead of
                # silently calling BLEInterface() (which now raises
                # TypeError: __init__() missing 1 required positional
                # argument: 'address').
                if not tgt:
                    raise ValueError(
                        "No BLE device selected.\n\n"
                        "Click the 🔍 Scan button next to the BLE address "
                        "field to discover nearby Meshtastic devices, then "
                        "pick one from the list.")
                self.progress.emit(f"Connecting to BLE device {tgt}…")
                iface = BLEInterface(address=tgt)

            else:
                raise ValueError(f"Unknown connection type: {self.conn_type}")

            self.progress.emit("Awaiting handshake with device…")
            self.succeeded.emit(iface)

        except Exception as e:
            log.exception("Error in ConnectWorker")
            sl = str(e).lower()
            # Tag the error so the reconnect logic can stop hammering after
            # a few attempts when it's clear the user needs to fix something.
            self._ble_not_found = "ble" in self.conn_type and (
                "no meshtastic ble peripheral" in sl
                or "bleinterface.bleerror" in type(e).__name__.lower()
            )
            self._serial_locked = self.conn_type == "serial" and (
                "could not open port" in sl
                or "access is denied" in sl
                or "permissionerror" in type(e).__name__.lower()
            )
            self.failed.emit(self._friendly_error(e))

    @staticmethod
    def _friendly_error(e: Exception) -> str:
        """Translate a technical exception into a user-facing message.

        V20-turn12: all messages are now i18n-translated using `t()` so
        the language follows the user's UI setting. Previously the
        messages were hardcoded in Romanian even when the app was set
        to English.
        """
        from .i18n import t
        s = str(e)
        sl = s.lower()
        if "could not open port" in sl or "access is denied" in sl \
                or "permissionerror" in type(e).__name__.lower():
            return t("err.serial_busy", s)
        if "no such file" in sl or "filenotfound" in sl:
            return t("err.serial_no_port", s)
        if ("no meshtastic ble peripheral" in sl
                or "bleinterface.bleerror" in type(e).__name__.lower()):
            return t("err.ble_not_found", s)
        # Connection refused (WinError 10061) — usually wrong IP or port.
        # Meshtastic listens on TCP 4403; a refused connection often means
        # the port is wrong (e.g. 4404) or the device's WiFi/TCP is off.
        if "10061" in s or "refused" in sl or "connectionrefused" in type(e).__name__.lower():
            return ("Connection refused. Check the IP address and make sure "
                    "the port is 4403 (the Meshtastic default). A refused "
                    "connection usually means nothing is listening on that "
                    "host/port — verify the device's WiFi/TCP is enabled.")
        # Socket-level timeout (WinError 10060) — host unreachable / wrong IP
        if "10060" in s:
            return ("Connection timed out reaching the device. The IP may be "
                    "wrong or the device is off the network. Double-check the "
                    "address and that the device is powered on and on WiFi.")
        # Protocol handshake timeout — socket connected but device didn't
        # finish the Meshtastic handshake (common on weak WiFi / busy device).
        if "waiting for connection completion" in sl:
            return ("Reached the device but it didn't finish the Meshtastic "
                    "handshake in time. This is common on a weak WiFi link or "
                    "a busy device — try again, or move the node closer to "
                    "the access point.")
        if "timeout" in sl:
            return t("err.conn_timeout", s)
        if "no devices detected" in sl or "no meshtastic device" in sl:
            return t("err.no_device", s)
        return f"{type(e).__name__}: {s}"


# ===========================================================================
# MeshtasticManager - obiectul central
# ===========================================================================
class MeshtasticManager(QObject):
    """
    Inca o data: TOATE semnalele Qt sunt emise pe Qt main thread (via
    QTimer.singleShot sau via QueuedConnection auto). Callbackurile pubsub
    sunt rulate pe threadul lui meshtastic, deci ne ferim de race conditions.
    """

    # --- Semnale UI ---
    stateChanged       = Signal(str)            # idle | opening | waiting_config | loading | ready | failed
    progressMessage    = Signal(str)            # text descriptiv pentru utilizator
    deviceInfoReady    = Signal(dict)
    nodeUpdated        = Signal(str, dict)
    nodeRemoved        = Signal(str)
    textMessageReceived= Signal(dict)
    positionReceived   = Signal(str, dict)
    telemetryReceived  = Signal(str, dict)
    channelsUpdated    = Signal(list)
    rawPacketReceived  = Signal(dict)
    errorMessage       = Signal(str)            # user-friendly error string

    # Signal fired when user-requested telemetry arrives → trigger popup
    telemetryPopupReady = Signal(str)  # node_id

    # Signal fired when a ROUTING_APP ack/nack arrives for a previously
    # sent message. Carries a dict {"packet_id": int, "status": str}.
    #
    # IMPORTANT: this used to be Signal(int, str). Despite an explicit
    # @Slot(int, str) decoration on the receiver, PySide6 6.11.0 still
    # logged "AttributeError: Slot 'MessagesPage::_on_message_ack(int,
    # QString)' not found." for every queued emission across threads.
    # The Signal(dict) form (already used successfully by
    # textMessageReceived and reactionReceived) sidesteps the QString
    # metaobject lookup entirely by routing through PyObject marshaling.
    messageAckReceived = Signal(dict)

    # V20-turn7: fired whenever WE successfully send a text message,
    # regardless of source (Messages-tab input, Scripts/automation, or
    # the Console's sendtext/send commands). This lets MessagesPage be
    # the single source of truth for rendering and persisting outbound
    # bubbles — without this, messages sent from scripts vanished into
    # the network without ever showing up in the conversation log.
    #
    # Payload mirrors what _send_current used to build locally:
    #   {
    #     "fromId":    "!hexnodeid",
    #     "toId":      "^all" or "!hexnodeid",
    #     "channel":   int,
    #     "text":      str,
    #     "packetId":  int | None,
    #     "rxTime":    int (epoch),
    #     "replyId":   int | None,
    #     "ackStatus": "pending" (DM, waiting for ROUTING ack) | "sent",
    #     "source":    "ui" | "script" | "console" — informational
    #   }
    messageSent = Signal(dict)

    # --- New signals for advanced packet types (V20) ---
    # Reaction: EMOJI_APP packet referencing an earlier message via reply_id
    # Payload: {fromId, toId, channel, replyId, emoji, rxTime}
    reactionReceived = Signal(dict)

    # NeighborInfo (NEIGHBORINFO_APP): list of direct radio neighbors
    # observed by a node. Carries (node_id, neighbors_list) where each
    # neighbor is {node_id, snr, last_rx_time}.
    neighborInfoReceived = Signal(str, list)

    # RangeTest sequence packet (RANGE_TEST_APP) — incoming text from a
    # node running the range test sender. Includes RX SNR/RSSI so the UI
    # can build TX/RX statistics. Payload: {fromId, seq, text, rxSnr,
    # rxRssi, hopStart, hopLimit, rxTime}.
    rangeTestPacket = Signal(dict)

    # RF scan signals
    scanProgress  = Signal(dict)   # {elapsed, duration, packets, phase}
    scanFinished  = Signal(dict)   # full report
    scanStateChanged = Signal(bool)  # True=scanning, False=idle

    # --- Semnal intern pentru dispecerizare cross-thread ---
    # The only 100%-safe way to execute code on the Qt main thread from
    # pubsub callbacks (which run on threads without a Qt event loop).
    _qtDispatch = Signal(object)   # carries a 0-arg callable

    # internal state -> human text mapping
    STATE_LABELS = {
        "idle":           "Inactiv",
        "opening":        "Se deschide conexiunea",
        "waiting_config": "Waiting for config",
        "loading":        "Incarc nodurile",
        "ready":          "Conectat",
        "failed":         "Eroare conexiune",
    }

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._iface: Any = None
        self._worker: Optional[_ConnectWorker] = None
        self._state = "idle"
        self._my_node_num: Optional[int] = None
        self._subscribed = False
        self._connection_established_seen = False
        self._config_timeout_timer: Optional[QTimer] = None

        # mentinem ultimele setari pentru auto-reconnect
        self._last_conn_type: Optional[str] = None
        self._last_target: str = ""
        self._auto_reconnect: bool = False
        self._reconnect_timer: Optional[QTimer] = None
        self._reconnect_attempts: int = 0
        self._user_disconnected: bool = False

        # Dispatch signal connectat cu QueuedConnection -> ruleaza pe Qt thread
        # garantat, indiferent de unde se face emit().
        self._qtDispatch.connect(self._do_dispatched_call,
                                 type=Qt.QueuedConnection)

        # Dedup for packets that arrive on multiple subtopics simultaneously
        self._recent_packet_ids: set = set()
        self._recent_packet_lock = threading.Lock()

        # Track popup-pending telemetry requests (120s window)
        self._popup_pending: dict = {}    # node_id -> request_timestamp
        self._popup_timeout: int = 120

        # Track ACK / relay responses for every sent message we know about.
        # Each entry maps a packet_id to a list of routing responses:
        # [{from_id, status, time, error, snr, rssi}, ...]
        # Capped at the 200 most-recent sent packets to bound memory.
        self._sent_msg_acks: dict = {}        # packet_id -> list of dicts
        self._sent_msg_meta: dict = {}        # packet_id -> {dest, channel, text, sent_at}
        self._sent_msg_order: list = []       # FIFO of packet_ids for eviction

        # V20-turn8: Mesh-health counters. We sample channel_utilization
        # from our own TELEMETRY packets (the device measures airtime) and
        # count decoded packets by direction. The `mesh-health` console
        # command and the Info-tab indicator read these to tell the user
        # apart "RF noise high, decode low" (PSK mismatch / interference)
        # from "channel quiet" (no neighbours active).
        #
        # rx_packets[port] = [(timestamp, from_id), …] last 1000 per port
        # tx_packets       = [(timestamp, dest), …] last 1000
        # channel_util     = [(timestamp, percent), …] last 500 samples
        from collections import deque
        self._rx_packets: dict = {
            "TEXT_MESSAGE_APP": deque(maxlen=1000),
            "POSITION_APP":     deque(maxlen=1000),
            "TELEMETRY_APP":    deque(maxlen=1000),
            "NODEINFO_APP":     deque(maxlen=1000),
            "ROUTING_APP":      deque(maxlen=1000),
            "OTHER":            deque(maxlen=1000),
        }
        self._tx_packets: deque  = deque(maxlen=1000)
        self._channel_util_log: deque = deque(maxlen=500)
        self._session_started_at = int(time.time())

        # ── RF Scan mode ─────────────────────────────────────────────────
        # When the user starts a scan, we dedicate the connection to
        # capturing EVERY received frame (no sampling cap) and pause the
        # app's background chatter (script scheduler, telemetry polling).
        # A stock Meshtastic node is not a spectrum analyser — it can only
        # hear its current band+preset — so the scan is an intensive
        # passive-listen session, optionally cycling presets for breadth.
        self._scanning: bool = False
        self._scan_packets: list = []   # [(ts, from_id, port, snr, rssi, hops, channel)]
        self._scan_started_at: int = 0
        self._scan_orig_lora = None      # saved config to restore after preset-cycle

        # ── Safety-net timer ─────────────────────────────────────────────
        # If anything causes the auto-reconnect chain to break (OS suspend
        # eating queued events, a lost timer reference, an unexpected race),
        # this periodic check forces a reconnect when we *should* be online
        # but aren't. Runs every 30 s, idempotent.
        # Windows laptops in particular freeze every QTimer when the OS
        # sleeps; the queued reconnect call may never fire. When the laptop
        # wakes, this timer catches up on the next tick.
        self._safety_timer = QTimer(self)
        self._safety_timer.setInterval(30 * 1000)
        self._safety_timer.timeout.connect(self._safety_net_check)
        self._safety_timer.start()

    def _safety_net_check(self):
        """Force a reconnect if we should be connected but aren't."""
        if not self._auto_reconnect or self._user_disconnected:
            return
        if not self._last_conn_type:
            return
        # Case 1: state is idle/failed and nothing is scheduled — the
        # reconnect chain stalled (e.g. timer killed by OS sleep).
        if self._state in ("idle", "failed") and self._reconnect_timer is None:
            log.warning(
                f"Safety net: state={self._state} but no reconnect scheduled "
                f"— forcing reconnect now")
            self._schedule_reconnect()
            return
        # Case 2 (V20-turn14): state says "ready" but the underlying reader
        # thread has died. This happens when the meshtastic stream reader
        # hits "Unexpected OSError, terminating reader" (WinError 10054
        # after a config-write reboot, or a Wi-Fi drop) WITHOUT publishing
        # the connection.lost pubsub event — so _handle_connection_lost
        # never fires and we're stuck believing we're connected on a dead
        # socket. Detect the dead reader thread and recover.
        if self._state == "ready" and self._iface is not None:
            rx_thread = getattr(self._iface, "_rxThread", None)
            if rx_thread is not None:
                try:
                    alive = rx_thread.is_alive()
                except Exception:
                    alive = True  # can't tell — assume OK
                if not alive:
                    log.warning(
                        "Safety net: state=ready but the reader thread is "
                        "DEAD (socket likely closed by remote). Forcing a "
                        "reconnect.")
                    # Treat exactly like a lost connection
                    self._handle_connection_lost()

    # ---------- proprietati publice ----------
    @property
    def interface(self):    return self._iface
    @property
    def state(self) -> str: return self._state
    @property
    def is_connected(self) -> bool:
        return self._state == "ready" and self._iface is not None
    @property
    def my_node_num(self) -> Optional[int]: return self._my_node_num
    @property
    def my_node_id(self)  -> Optional[str]: return num_to_id(self._my_node_num)

    # =======================================================================
    # CONECTARE
    # =======================================================================
    def connect_to_device(self, conn_type: str, target: str = "",
                          _auto_reconnect: bool = False):
        """Punct unic de pornire a conexiunii."""
        if self._state in ("opening", "waiting_config", "loading"):
            log.warning("Connection already in progress; ignoring request")
            return
        if self.is_connected:
            log.info("Disconnecting before reconnecting")
            self.disconnect(user_initiated=False)

        self._last_conn_type = conn_type
        self._last_target = target
        self._user_disconnected = False
        # Only reset the attempt counter for *user-initiated* connects.
        # Auto-reconnect preserves it so exponential back-off accumulates
        # correctly instead of resetting to 3 s after every attempt.
        if not _auto_reconnect:
            self._reconnect_attempts = 0
        self._connection_established_seen = False
        self._stop_reconnect_timer()
        self._subscribe_to_pubsub_once()
        self._set_state("opening")
        self.progressMessage.emit(t("progress.preparing"))

        log.info(f"Initiating connection: type={conn_type} target={target!r}")

        self._worker = _ConnectWorker(conn_type, target, self)
        self._worker.progress.connect(self.progressMessage)
        self._worker.succeeded.connect(self._on_worker_succeeded)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def disconnect(self, user_initiated: bool = True):
        """Cleanly close the current connection.

        When a TCP/serial link drops abruptly (WinError 10054, cable yank),
        the meshtastic library's close() still tries to send a disconnect
        packet over the dead socket, which raises. We pre-empt that by
        closing the underlying stream/socket directly first, so the normal
        close() has nothing left to fail on. Any residual error is logged
        quietly (debug) since it's expected, not a real fault.
        """
        log.info(f"disconnect() called (user={user_initiated})")
        if user_initiated:
            self._user_disconnected = True
            self._stop_reconnect_timer()
        self._stop_config_timeout()
        if self._iface is not None:
            iface = self._iface
            self._iface = None
            # Full teardown: cancels heartbeat timer + closes raw socket so
            # no background thread keeps trying to write to a dead link.
            self._teardown_iface(iface)
        self._my_node_num = None
        self._connection_established_seen = False
        self._set_state("idle")

    def set_auto_reconnect(self, enabled: bool):
        """Activeaza/dezactiveaza auto-reconnect la pierderea conexiunii."""
        self._auto_reconnect = bool(enabled)
        log.info(f"Auto-reconnect: {self._auto_reconnect}")

    # =======================================================================
    # SUBSCRIPTII PUBSUB
    # =======================================================================
    def _subscribe_to_pubsub_once(self):
        if self._subscribed:
            return
        try:
            from pubsub import pub
            # Evenimente conexiune
            pub.subscribe(self._pubsub_connection_established, "meshlink.connection.established")
            pub.subscribe(self._pubsub_connection_lost,        "meshlink.connection.lost")

            # IMPORTANT: meshtastic Python publica pe SUBTOPICURI specifice.
            # Subscriem la TOATE ca sa nu pierdem nimic - dedup-ul filtreaza
            # eventuale duplicate pe baza de packet["id"].
            pub.subscribe(self._pubsub_receive, "meshtastic.receive")
            pub.subscribe(self._pubsub_receive, "meshtastic.receive.text")
            pub.subscribe(self._pubsub_receive, "meshtastic.receive.data")
            pub.subscribe(self._pubsub_receive, "meshtastic.receive.position")
            pub.subscribe(self._pubsub_receive, "meshtastic.receive.user")
            pub.subscribe(self._pubsub_receive, "meshtastic.receive.telemetry")
            pub.subscribe(self._pubsub_receive, "meshtastic.receive.traceroute")

            # Node DB
            pub.subscribe(self._pubsub_node_updated, "meshtastic.node.updated")

            self._subscribed = True
            log.info("Subscribed to all Meshtastic pubsub events")
        except Exception:
            log.exception("Nu am putut abona la pubsub")

    # --- callback-uri pubsub (vin pe alt thread) ---
    # Toate decoraza un thunk care reapeleaza pe Qt main thread

    def _pubsub_connection_established(self, interface=None, topic=None):  # noqa: ARG002
        log.info("[pubsub] connection.established")
        self._invoke_on_qt(self._handle_connection_established, interface)

    def _pubsub_connection_lost(self, interface=None, topic=None):  # noqa: ARG002
        log.warning("[pubsub] connection.lost")
        self._invoke_on_qt(self._handle_connection_lost)

    def _pubsub_node_updated(self, node=None, interface=None, topic=None):  # noqa: ARG002
        if node:
            self._invoke_on_qt(self._handle_node_updated, dict(node))

    def _pubsub_receive(self, packet=None, interface=None, topic=None):  # noqa: ARG002
        if not packet:
            return
        # Logging vizibil in Console
        try:
            decoded = packet.get("decoded") if isinstance(packet, dict) else None
            portnum = (decoded or {}).get("portnum", "?") if decoded else "?"
            pkt_id  = packet.get("id", "?") if isinstance(packet, dict) else "?"
            from_id = packet.get("fromId", "?") if isinstance(packet, dict) else "?"
            topic_str = str(topic) if topic else "?"
            log.info(f"[pubsub.receive] topic={topic_str} portnum={portnum} "
                     f"id={pkt_id} from={from_id}")
        except Exception:
            log.exception("Error logging pubsub.receive")

        # Dedup: acelasi pachet poate veni pe mai multe subtopicuri.
        try:
            pkt_id = packet.get("id") if isinstance(packet, dict) else None
            if pkt_id is not None:
                with self._recent_packet_lock:
                    if pkt_id in self._recent_packet_ids:
                        log.debug(f"  -> dup, ignor (id={pkt_id})")
                        return
                    self._recent_packet_ids.add(pkt_id)
                    if len(self._recent_packet_ids) > 500:
                        # tinem doar ultimele ~250
                        self._recent_packet_ids = set(
                            list(self._recent_packet_ids)[-250:])
        except Exception:
            log.exception("Dedup error")

        try:
            self._invoke_on_qt(self._handle_packet, dict(packet))
        except Exception:
            log.exception("Error processing pubsub.receive")

    # =======================================================================
    # DISPATCHER cross-thread (signal cu QueuedConnection)
    # =======================================================================
    def _do_dispatched_call(self, fn):
        """Apelat pe Qt main thread cand cineva emite _qtDispatch."""
        try:
            fn()
        except Exception:
            log.exception("Error in dispatched call")

    def _invoke_on_qt(self, fn, *args):
        """
        Garanteaza ca fn(*args) ruleaza pe Qt main thread, indiferent de unde
        e apelat. Folosim signal + QueuedConnection - 100% sigur cross-thread.
        """
        try:
            self._qtDispatch.emit(lambda: fn(*args))
        except Exception:
            log.exception("Error emitting _qtDispatch")

    # =======================================================================
    # HANDLERE Qt thread (pot emite semnale direct, sigur)
    # =======================================================================
    def _handle_connection_established(self, interface):
        if self._connection_established_seen:
            return
        self._connection_established_seen = True
        log.info("Meshtastic connection established")

        # Enable aggressive TCP keepalive on TCP socket. Default Windows TCP
        # keepalive is 2 hours which is too long; many home routers and WiFi
        # access points drop idle connections after 30-60 seconds, causing
        # silent dead connections that only surface on the next write.
        # We send keepalive probes every 5s after 10s idle, fail after 3 tries.
        try:
            sock = getattr(interface, "socket", None)
            if sock is not None:
                import socket as _sock
                sock.setsockopt(_sock.SOL_SOCKET, _sock.SO_KEEPALIVE, 1)
                # Windows: SIO_KEEPALIVE_VALS(onoff=1, idle_ms, interval_ms)
                if hasattr(_sock, "SIO_KEEPALIVE_VALS"):
                    sock.ioctl(_sock.SIO_KEEPALIVE_VALS, (1, 10000, 5000))
                # POSIX: TCP_KEEPIDLE/TCP_KEEPINTVL/TCP_KEEPCNT
                if hasattr(_sock, "TCP_KEEPIDLE"):
                    sock.setsockopt(_sock.IPPROTO_TCP, _sock.TCP_KEEPIDLE, 10)
                if hasattr(_sock, "TCP_KEEPINTVL"):
                    sock.setsockopt(_sock.IPPROTO_TCP, _sock.TCP_KEEPINTVL, 5)
                if hasattr(_sock, "TCP_KEEPCNT"):
                    sock.setsockopt(_sock.IPPROTO_TCP, _sock.TCP_KEEPCNT, 3)
                log.info("TCP keepalive enabled (10s idle, 5s interval, 3 probes)")
        except Exception:
            log.debug("Could not enable TCP keepalive", exc_info=True)

        # Extract local node id quickly
        try:
            mi = getattr(interface, "myInfo", None)
            if mi:
                self._my_node_num = getattr(mi, "my_node_num", None)
                log.info(f"My node num = {self._my_node_num}")
        except Exception:
            log.exception("Error extracting myInfo")

        self._stop_config_timeout()
        self._set_state("loading")
        self.progressMessage.emit(t("progress.loading"))

        # publica info imediat
        self._publish_device_info()
        self._publish_all_nodes()
        self._publish_channels()

        # Final ready dupa o mica latenta (lasam pubsub-ul sa termine)
        QTimer.singleShot(300, self._mark_ready)

    def _mark_ready(self):
        if self._state in ("loading", "waiting_config"):
            self._set_state("ready")
            self._reconnect_attempts = 0  # reset on successful connect
            self.progressMessage.emit(t("progress.ready"))

    def _teardown_iface(self, iface):
        """Forcibly stop a (probably dead) interface so its background timers
        don't keep firing on a closed socket.

        The meshtastic library arms a self-rescheduling heartbeat timer
        (threading.Timer) that calls sendHeartbeat() -> socket.send(). When
        the link drops, that timer keeps firing every few seconds, each time
        spawning a thread that crashes with WinError 10054. Dozens pile up.
        We must cancel that timer and close the raw socket so the heartbeat
        becomes a no-op. Done defensively across library versions.
        """
        if iface is None:
            return
        # 1) Cancel the self-rescheduling heartbeat timer
        for attr in ("heartbeatTimer", "_heartbeatTimer"):
            t_ = getattr(iface, attr, None)
            if t_ is not None:
                try:
                    t_.cancel()
                except Exception:
                    pass
                try:
                    setattr(iface, attr, None)
                except Exception:
                    pass
        # 2) Close the raw socket/stream so any in-flight send() is a no-op
        for attr in ("socket", "stream"):
            s_ = getattr(iface, attr, None)
            if s_ is not None:
                try:
                    s_.close()
                except Exception:
                    pass
        # 3) Best-effort full close (guarded — may itself raise on dead link)
        try:
            iface.close()
        except Exception:
            pass

    def _handle_connection_lost(self):
        log.warning("Connection lost")
        # Tear down the dead interface FIRST so its heartbeat timer stops
        # spamming crashed threads on the closed socket.
        old_iface = self._iface
        self._iface = None
        try:
            self._teardown_iface(old_iface)
        except Exception:
            log.debug("teardown_iface failed", exc_info=True)
        self._connection_established_seen = False
        self._set_state("idle")
        self.errorMessage.emit(t("err.conn_lost"))
        # auto-reconnect if enabled and user did not disconnect manually
        if self._auto_reconnect and not self._user_disconnected and self._last_conn_type:
            self._schedule_reconnect()

    # =======================================================================
    # AUTO-RECONNECT
    # =======================================================================
    def _schedule_reconnect(self):
        if self._reconnect_timer is not None:
            return  # already queued
        self._reconnect_attempts += 1
        # backoff: 3s, 6s, 12s, max 30s
        delay = min(3 * (2 ** (self._reconnect_attempts - 1)), 30)
        log.info(f"Auto-reconnect in {delay}s (attempt {self._reconnect_attempts})")
        self.progressMessage.emit(t("progress.reconnect_in", delay))
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._do_reconnect)
        self._reconnect_timer.start(delay * 1000)

    def _stop_reconnect_timer(self):
        if self._reconnect_timer:
            self._reconnect_timer.stop()
            self._reconnect_timer.deleteLater()
            self._reconnect_timer = None

    def _do_reconnect(self):
        self._reconnect_timer = None
        if self._user_disconnected or not self._last_conn_type:
            return
        # Skip if already connected (fixed serial double-reconnect bug)
        if self._state == "ready":
            log.info("Auto-reconnect: already connected and ready — skipping")
            self._reconnect_attempts = 0
            return
        if self._state in ("opening", "waiting_config", "loading"):
            log.info("Auto-reconnect: connection already in progress — skipping")
            return
        # V20-turn9: For BLE "device not found" errors, stop retrying after
        # 8 attempts (~4 minutes of scanning) and tell the user to re-scan.
        # Without this the app hammers BLE forever eating battery and CPU.
        BLE_MAX_NOT_FOUND = 8
        if (self._last_conn_type == "ble"
                and self._reconnect_attempts >= BLE_MAX_NOT_FOUND
                and getattr(self, "_last_ble_not_found", False)):
            self._user_disconnected = True   # pause auto-reconnect
            log.warning(
                f"BLE device '{self._last_target}' not found after "
                f"{self._reconnect_attempts} scans. Auto-reconnect paused. "
                "Re-scan with the 🔍 button to retry.")
            self.errorMessage.emit(
                f"BLE device not found after {self._reconnect_attempts} scans.\n\n"
                "The device may be:\n"
                "  • Too far away / out of range\n"
                "  • Powered off or in sleep mode\n"
                "  • BLE disabled in its Settings\n\n"
                "Click 🔍 Scan to search for nearby devices again."
            )
            return

        # V20-turn12: Same protection for serial PermissionError(13) — the
        # port is held by another process (Arduino IDE, another instance of
        # this app, an older meshtastic CLI session). Hammering it every
        # 3-6 seconds doesn't help. Pause after 5 attempts so the user can
        # close the offending app.
        SERIAL_MAX_LOCKED = 5
        if (self._last_conn_type == "serial"
                and self._reconnect_attempts >= SERIAL_MAX_LOCKED
                and getattr(self, "_last_serial_locked", False)):
            self._user_disconnected = True
            log.warning(
                f"Serial port '{self._last_target}' has been locked for "
                f"{self._reconnect_attempts} attempts. Auto-reconnect paused.")
            from .i18n import t
            self.errorMessage.emit(
                t("err.serial_locked_giving_up",
                  self._last_target, self._reconnect_attempts))
            return
        log.info("Auto-reconnect: attempting to reconnect")
        self.connect_to_device(self._last_conn_type, self._last_target,
                               _auto_reconnect=True)

    def _handle_node_updated(self, node: dict):
        try:
            node = normalize_keys(node)  # normalize keys
            user    = node.get("user") or {}
            node_id = user.get("id") or num_to_id(node.get("num"))
            if node_id:
                self.nodeUpdated.emit(node_id, node)
        except Exception:
            log.exception("Error in _handle_node_updated")

    def _emit_node_update_merged(self, node_id: str,
                                 position: Optional[dict] = None,
                                 device_metrics: Optional[dict] = None,
                                 environment_metrics: Optional[dict] = None,
                                 power_metrics: Optional[dict] = None,
                                 neighbors: Optional[list] = None,
                                 neighbors_rx_time: Optional[int] = None):
        """
        Build a complete node dict (starting from iface.nodes if available)
        and apply the partial updates received, then emit nodeUpdated.
        Used to refresh the card + map + info when POSITION or TELEMETRY
        packets arrive for REMOTE nodes (not our local node).
        """
        try:
            base: dict = {}
            if self._iface and getattr(self._iface, "nodes", None):
                try:
                    raw = self._iface.nodes.get(node_id)
                    if raw:
                        base = normalize_keys(dict(raw))
                except Exception:
                    pass
            if not base.get("user"):
                base["user"] = {"id": node_id}
            if position:
                merged_pos = {**(base.get("position") or {}), **position}
                base["position"] = merged_pos
            if device_metrics:
                merged_dm = {**(base.get("deviceMetrics") or {}), **device_metrics}
                base["deviceMetrics"] = merged_dm
            if environment_metrics:
                # Carry the most recent env reading on the node (camelCase keys)
                merged_em = {**(base.get("environmentMetrics") or {}),
                             **environment_metrics}
                base["environmentMetrics"] = merged_em
            if power_metrics:
                merged_pm = {**(base.get("powerMetrics") or {}), **power_metrics}
                base["powerMetrics"] = merged_pm
            if neighbors is not None:
                base["neighbors"] = neighbors
            if neighbors_rx_time is not None:
                base["neighborsRxTime"] = neighbors_rx_time
            base["lastHeard"] = int(time.time())
            log.info(f"     -> emit nodeUpdated({node_id}) "
                     f"position={bool(position)} dm={bool(device_metrics)} "
                     f"env={bool(environment_metrics)} pwr={bool(power_metrics)} "
                     f"neighbors={'yes' if neighbors is not None else 'no'}")
            self.nodeUpdated.emit(node_id, base)
        except Exception:
            log.exception("Error _emit_node_update_merged")

    def _handle_packet(self, packet: dict):
        try:
            # CRITICAL: normalize all keys to camelCase because the meshtastic
            # library returns some fields in snake_case (device_metrics,
            # battery_level, latitude_i) while our code expects camelCase.
            packet = normalize_keys(packet)
            self.rawPacketReceived.emit(packet)

            decoded = packet.get("decoded") or {}
            portnum = decoded.get("portnum", "")
            if hasattr(portnum, "name"):
                portnum = portnum.name
            portnum = str(portnum)

            from_num = packet.get("from")
            from_id  = packet.get("fromId") or num_to_id(from_num)
            to_num   = packet.get("to")
            to_id    = packet.get("toId")   or num_to_id(to_num)

            log.debug(f"_handle_packet: portnum={portnum} from={from_id} to={to_id}")

            # V20-turn8: count this RX in the per-port deque so mesh-health
            # can report decode rates. We skip our OWN broadcasts (the device
            # echoes back local TX as RX so they'd otherwise inflate the
            # numbers and hide real decode-rate problems).
            try:
                if from_id and from_id != self.my_node_id:
                    port_key = portnum if portnum in self._rx_packets else "OTHER"
                    self._rx_packets[port_key].append((
                        int(time.time()), from_id,
                        float(packet.get("rxSnr") or 0),
                        int(packet.get("rxRssi") or 0),
                    ))
                # RF scan: capture EVERY frame (incl. our own echoes) with full
                # metadata so the scan report can characterise all activity.
                if self._scanning:
                    try:
                        hops = None
                        if packet.get("hopStart") is not None and \
                           packet.get("hopLimit") is not None:
                            hops = int(packet["hopStart"]) - int(packet["hopLimit"])
                        ch_idx = packet.get("channel")
                        self._scan_packets.append((
                            int(time.time()),
                            from_id or "(unknown)",
                            portnum or "(none)",
                            float(packet.get("rxSnr") or 0),
                            int(packet.get("rxRssi") or 0),
                            hops,
                            ch_idx,
                        ))
                    except Exception:
                        log.debug("scan capture failed", exc_info=True)
                # Sample channel_utilization from local telemetry — this is
                # the device's own measurement of how busy the air is.
                if (from_id == self.my_node_id
                        and portnum == "TELEMETRY_APP"):
                    metrics = (decoded.get("telemetry") or {}) \
                              .get("deviceMetrics") or {}
                    cu = metrics.get("channelUtilization")
                    if cu is not None:
                        self._channel_util_log.append(
                            (int(time.time()), float(cu)))
            except Exception:
                log.exception("RX counter update failed")

            # ----------- TEXT MESSAGE ----------
            # Detectare permisiva: portnum contine "TEXT_MESSAGE" SAU avem `text` SAU
            # avem `payload` cu bytes printabile (fallback)
            text_field = decoded.get("text")
            if not text_field:
                # Fallback: decodam payload-ul brut daca biblioteca n-a setat text
                payload = decoded.get("payload")
                if isinstance(payload, (bytes, bytearray)) and payload:
                    try:
                        candidate = bytes(payload).decode("utf-8", errors="strict")
                        # accept doar daca pare text vizibil (nu doar binar)
                        if candidate.isprintable() or "\n" in candidate:
                            text_field = candidate
                            log.info(f"  text decodat din payload bytes: {text_field[:50]!r}")
                    except Exception:
                        pass

            is_text = ("TEXT_MESSAGE" in portnum) or bool(text_field)

            if is_text:
                if not text_field:
                    log.debug(f"  text gol, ignor (portnum={portnum})")
                    return
                # Extract replyId — newer Meshtastic firmware threads replies.
                # Library may surface it as decoded.replyId or packet.replyId.
                reply_id = (decoded.get("replyId")
                            or packet.get("replyId")
                            or decoded.get("reply_id")
                            or packet.get("reply_id"))
                try:
                    reply_id = int(reply_id) if reply_id else None
                except Exception:
                    reply_id = None
                msg = {
                    "fromId":  from_id,
                    "toId":    to_id,
                    "channel": packet.get("channel", 0),
                    "text":    text_field,
                    "rxTime":  packet.get("rxTime", int(time.time())),
                    "rxSnr":   packet.get("rxSnr"),
                    "rxRssi":  packet.get("rxRssi"),
                    "hopStart":packet.get("hopStart"),
                    "hopLimit":packet.get("hopLimit"),
                    "id":      packet.get("id"),
                    "replyId": reply_id,
                }
                log.info(f"  >> TEXT emit: from={from_id} to={to_id} "
                         f"ch={msg['channel']} reply_id={reply_id} "
                         f"text={msg['text'][:80]!r}")
                self.textMessageReceived.emit(msg)
                return

            # ---------- POSITION ----------
            if "POSITION" in portnum:
                pos = decoded.get("position", {}) or {}
                if from_id:
                    log.info(f"  >> POSITION from {from_id} pos={pos}")
                    self.positionReceived.emit(from_id, pos)
                    self._emit_node_update_merged(from_id, position=pos)
                return

            # ---------- TELEMETRY ----------
            if "TELEMETRY" in portnum:
                tel = decoded.get("telemetry", {}) or {}
                if not from_id:
                    return
                log.info(f"  >> TELEMETRY from {from_id} tel={tel}")
                self.telemetryReceived.emit(from_id, tel)

                dm = tel.get("deviceMetrics") or {}
                local_stats = tel.get("localStats") or {}
                environment = tel.get("environmentMetrics") or {}
                power_metrics = tel.get("powerMetrics") or {}

                if dm:
                    log.info(f"     deviceMetrics={dm}")
                    # Save in DB for chart history
                    try:
                        from .telemetry_db import TelemetryDB
                        TelemetryDB.get().add_reading(
                            node_id=from_id,
                            timestamp=int(tel.get("time") or time.time()),
                            battery_level=dm.get("batteryLevel"),
                            voltage=dm.get("voltage"),
                            channel_utilization=dm.get("channelUtilization"),
                            air_util_tx=dm.get("airUtilTx"),
                            uptime_seconds=dm.get("uptimeSeconds"),
                        )
                    except Exception:
                        log.exception("Failed to save telemetry to DB")
                    self._emit_node_update_merged(from_id, device_metrics=dm)
                elif local_stats:
                    log.info(f"     localStats (router stats)")
                elif environment:
                    log.info(f"     environmentMetrics={environment}")
                    # Persist env data so the chart can show
                    # temperature/humidity/pressure history
                    try:
                        from .telemetry_db import TelemetryDB
                        TelemetryDB.get().add_env_reading(
                            node_id=from_id,
                            timestamp=int(tel.get("time") or time.time()),
                            temperature=environment.get("temperature"),
                            humidity=environment.get("relativeHumidity"),
                            pressure=environment.get("barometricPressure"),
                            gas_resistance=environment.get("gasResistance"),
                            iaq=environment.get("iaq"),
                        )
                    except Exception:
                        log.exception("Failed to save env telemetry to DB")
                    self._emit_node_update_merged(
                        from_id, environment_metrics=environment)
                elif power_metrics:
                    log.info(f"     powerMetrics={power_metrics}")
                    # V0.44: persist INA219/INA260 ch1 voltage+current so the
                    # Info Power graph can show charge/consume over time.
                    try:
                        from .telemetry_db import TelemetryDB
                        TelemetryDB.get().add_power_reading(
                            node_id=from_id,
                            timestamp=int(tel.get("time") or time.time()),
                            ch1_voltage=power_metrics.get("ch1Voltage"),
                            ch1_current=power_metrics.get("ch1Current"),
                        )
                    except Exception:
                        log.exception("Failed to save power telemetry to DB")
                    self._emit_node_update_merged(
                        from_id, power_metrics=power_metrics)
                else:
                    log.debug(f"     Telemetry packet without known metrics; keys={list(tel.keys())}")

                # ALWAYS check pending popup — fire on ANY telemetry response,
                # not just deviceMetrics (remote routers often reply with
                # localStats or environmentMetrics only).
                self._maybe_fire_telemetry_popup(from_id)
                return

            # ---------- NODEINFO / user ----------
            if "NODEINFO" in portnum or portnum == "NODEINFO_APP":
                # User info, will be handled by pubsub.node.updated anyway
                log.debug(f"  nodeinfo packet")
                return

            # ---------- EMOJI_APP (reactions on earlier messages) ----------
            # Reactions arrive as a data packet with portnum=EMOJI_APP whose
            # payload is the emoji UTF-8 bytes and whose decoded.replyId
            # references the original message's packet.id.
            if "EMOJI" in portnum:
                payload = decoded.get("payload")
                emoji_str = ""
                if isinstance(payload, (bytes, bytearray)):
                    try:
                        emoji_str = bytes(payload).decode("utf-8",
                                                          errors="replace")
                    except Exception:
                        emoji_str = ""
                reply_id = (decoded.get("replyId")
                            or packet.get("replyId")
                            or decoded.get("reply_id")
                            or packet.get("reply_id"))
                try:
                    reply_id = int(reply_id) if reply_id else None
                except Exception:
                    reply_id = None
                if from_id and reply_id and emoji_str:
                    reaction = {
                        "fromId":  from_id,
                        "toId":    to_id,
                        "channel": packet.get("channel", 0),
                        "replyId": reply_id,
                        "emoji":   emoji_str,
                        "rxTime":  packet.get("rxTime", int(time.time())),
                    }
                    log.info(f"  >> REACTION from {from_id} on pkt #{reply_id}: "
                             f"{emoji_str!r}")
                    self.reactionReceived.emit(reaction)
                else:
                    log.debug(f"  EMOJI packet ignored (from={from_id} "
                              f"reply_id={reply_id} emoji={emoji_str!r})")
                return

            # ---------- NEIGHBORINFO_APP ----------
            # Direct radio neighbors observed by a node. Useful for showing
            # the mesh topology and 1-hop SNR even for nodes that we
            # ourselves can't hear directly.
            if "NEIGHBOR" in portnum:
                ni = decoded.get("neighborinfo") or decoded.get("neighborInfo") \
                     or decoded.get("neighbor_info") or {}
                neighbors_raw = ni.get("neighbors") or []
                neighbors = []
                for n in neighbors_raw:
                    nb_num = n.get("nodeId") or n.get("node_id")
                    nb_id = num_to_id(nb_num) if isinstance(nb_num, int) \
                            else nb_num
                    if not nb_id:
                        continue
                    neighbors.append({
                        "node_id": nb_id,
                        "snr":     n.get("snr"),
                        "last_rx_time": (n.get("lastRxTime")
                                         or n.get("last_rx_time")),
                    })
                if from_id:
                    log.info(f"  >> NEIGHBORINFO from {from_id}: "
                             f"{len(neighbors)} neighbors")
                    self.neighborInfoReceived.emit(from_id, neighbors)
                    # Attach to the node so the details dialog can show it.
                    self._emit_node_update_merged(
                        from_id, neighbors=neighbors,
                        neighbors_rx_time=int(time.time()))
                return

            # ---------- RANGE_TEST_APP ----------
            # The range-test module periodically broadcasts a sequence
            # number; we just forward the raw signal info so the modules
            # tab can build TX/RX statistics.
            if "RANGE_TEST" in portnum:
                # Payload is plain text "seq=N" or similar; just attach
                # the raw decoded text for the UI.
                rt_text = decoded.get("text") or ""
                if not rt_text:
                    payload = decoded.get("payload")
                    if isinstance(payload, (bytes, bytearray)):
                        try:
                            rt_text = bytes(payload).decode("utf-8",
                                                            errors="replace")
                        except Exception:
                            rt_text = ""
                rt = {
                    "fromId":   from_id,
                    "text":     rt_text,
                    "rxSnr":    packet.get("rxSnr"),
                    "rxRssi":   packet.get("rxRssi"),
                    "hopStart": packet.get("hopStart"),
                    "hopLimit": packet.get("hopLimit"),
                    "rxTime":   packet.get("rxTime", int(time.time())),
                }
                log.info(f"  >> RANGE_TEST from {from_id}: {rt_text!r} "
                         f"SNR={rt['rxSnr']} RSSI={rt['rxRssi']}")
                self.rangeTestPacket.emit(rt)
                return

            # ---------- ROUTING_APP (ACK / NACK for sent messages) ----------
            if "ROUTING" in portnum:
                # ROUTING_APP packets carry the ACK/NACK for our previously
                # sent messages (DMs with wantAck=True). decoded.requestId
                # matches the ID of the original message; routing.errorReason
                # indicates success (NONE) or failure.
                # For BROADCASTS: when relay routers forward our broadcast,
                # they may also emit ROUTING_APP packets, giving us a view
                # of which nodes in the mesh actually relayed our message.
                routing = decoded.get("routing") or {}
                req_id = decoded.get("requestId") or packet.get("requestId")
                err = routing.get("errorReason") or "NONE"
                if hasattr(err, "name"):
                    err = err.name
                err = str(err)
                if req_id:
                    status = "delivered" if err in ("NONE", "0") else "failed"
                    log.info(f"  ROUTING for pkt #{req_id} from {from_id}: {err} → {status}")
                    # Record per-responder details
                    entry = {
                        "from_id":  from_id,
                        "status":   status,
                        "error":    err,
                        "time":     int(time.time()),
                        "snr":      packet.get("rxSnr"),
                        "rssi":     packet.get("rxRssi"),
                        "hop_start":packet.get("hopStart"),
                        "hop_limit":packet.get("hopLimit"),
                    }
                    try:
                        req_id_int = int(req_id)
                    except Exception:
                        req_id_int = None
                    if req_id_int is not None:
                        responders = self._sent_msg_acks.setdefault(req_id_int, [])
                        # Avoid duplicates from the same responder
                        if not any(r["from_id"] == from_id for r in responders):
                            responders.append(entry)
                        try:
                            self.messageAckReceived.emit({
                                "packet_id": req_id_int,
                                "status":    status,
                                "error":     err,
                                "from_id":   from_id,
                            })
                        except Exception:
                            log.exception("Could not emit messageAckReceived")
                return

            log.debug(f"  packet ignored (portnum={portnum})")

        except Exception:
            log.exception("Error processing packet")

    # =======================================================================
    # WORKER CALLBACKS
    # =======================================================================
    def _on_worker_succeeded(self, iface):
        log.info("Worker: interface ready, waiting for pubsub establish")
        self._iface = iface
        self._set_state("waiting_config")
        self.progressMessage.emit(t("progress.waiting_config"))

        # Daca pubsub-ul NU trimite 'connection.established' in 15s
        # (poate s-a trimis inainte sa ne abonam), fortam manual
        self._start_config_timeout(seconds=15)

    def _on_worker_failed(self, err: str):
        log.error(f"Worker: connect failed: {err}")
        # Guard: if another path already brought us to ready, ignore
        if self._state == "ready":
            log.info("Worker failed but state is already ready — ignoring failure")
            return
        # Track whether the failure was "BLE device not found" (vs a real error)
        # so _do_reconnect can stop retrying after too many scans.
        self._last_ble_not_found = bool(
            getattr(self._worker, "_ble_not_found", False))
        self._iface = None
        self._set_state("failed")
        self.errorMessage.emit(err)
        if (self._auto_reconnect and not self._user_disconnected
                and self._last_conn_type):
            log.info("Worker failed during auto-reconnect — scheduling next retry")
            self._schedule_reconnect()

    # =======================================================================
    # TIMEOUT FALLBACK pt connection.established
    # =======================================================================
    def _start_config_timeout(self, seconds: int):
        self._stop_config_timeout()
        self._config_timeout_timer = QTimer(self)
        self._config_timeout_timer.setSingleShot(True)
        self._config_timeout_timer.timeout.connect(self._on_config_timeout)
        self._config_timeout_timer.start(seconds * 1000)

    def _stop_config_timeout(self):
        if self._config_timeout_timer:
            self._config_timeout_timer.stop()
            self._config_timeout_timer.deleteLater()
            self._config_timeout_timer = None

    def _on_config_timeout(self):
        if self._connection_established_seen:
            return
        if self._iface is None:
            return
        log.warning("Timeout asteptand connection.established - fortez")
        # Verificam daca avem myInfo deja (caz uzual: pubsub-ul a tras inainte)
        try:
            if getattr(self._iface, "myInfo", None):
                self._handle_connection_established(self._iface)
                return
        except Exception:
            pass
        self.errorMessage.emit(
            "Device-ul nu a trimis configuratia in 15 secunde.\n"
            "Verifica firmware-ul (>= 2.0) si reconecteaza.")
        self.disconnect()
        self._set_state("failed")

    # =======================================================================
    # PUBLICARE STARE INITIALA dupa connect
    # =======================================================================
    def _publish_device_info(self):
        if not self._iface:
            return
        info = {}
        try:
            my_info  = getattr(self._iface, "myInfo", None)
            metadata = getattr(self._iface, "metadata", None)
            local    = getattr(self._iface, "localNode", None)

            if my_info:
                info["myNodeNum"]      = getattr(my_info, "my_node_num", None)
                info["rebootCount"]    = getattr(my_info, "reboot_count", None)
                info["minAppVersion"]  = getattr(my_info, "min_app_version", None)

            if metadata:
                info["firmwareVersion"]    = getattr(metadata, "firmware_version", None)
                info["deviceStateVersion"] = getattr(metadata, "device_state_version", None)
                hw = getattr(metadata, "hw_model", "")
                if hw: info["hwModel"] = str(hw)

            my_id = num_to_id(info.get("myNodeNum"))
            if my_id and self._iface.nodes and my_id in self._iface.nodes:
                me = self._iface.nodes[my_id]
                user = me.get("user", {})
                info["longName"]  = user.get("longName")
                info["shortName"] = user.get("shortName")
                info["hwModel"]   = info.get("hwModel") or user.get("hwModel")
                info["id"]        = my_id

            if local and getattr(local, "localConfig", None):
                cfg = local.localConfig
                try:
                    if cfg.HasField("lora"):
                        info["region"]      = str(cfg.lora.region)
                        info["modemPreset"] = str(cfg.lora.modem_preset)
                        info["hopLimit"]    = cfg.lora.hop_limit
                except Exception:
                    pass
        except Exception:
            log.exception("Error extracting device info")

        log.info(f"Device info published: {info}")
        self.deviceInfoReady.emit(info)

    def _publish_all_nodes(self):
        if not self._iface or not self._iface.nodes:
            return
        count = 0
        for node_id, node in dict(self._iface.nodes).items():
            try:
                self.nodeUpdated.emit(str(node_id), normalize_keys(dict(node)))
                count += 1
            except Exception:
                log.exception(f"Error emitting for node {node_id}")
        log.info(f"Published {count} nodes from nodeDB")

    def _publish_channels(self):
        if not self._iface:
            return
        try:
            local = getattr(self._iface, "localNode", None)
            if not local:
                return
            channels = []
            # Include ALL slots (incl. DISABLED) — the management UI needs
            # to know which slots are free for the "Add channel" action.
            for ch in (local.channels or []):
                role = getattr(ch, "role", None)
                role_int = int(role) if role is not None else 0
                role_name = {0: "DISABLED",
                             1: "PRIMARY",
                             2: "SECONDARY"}.get(role_int, "DISABLED")
                settings = ch.settings if ch.settings else None
                name = ""
                if settings and settings.name:
                    name = settings.name
                elif role_int == 1:
                    name = "LongFast"
                # PSK as raw bytes (UI presents it base64 / hex on demand).
                # Convention:
                #   • empty → "default" key for that channel name
                #   • 0x01 → use default (legacy single-byte marker)
                #   • 16 / 32 bytes → AES-128 / AES-256 key
                psk_bytes = b""
                if settings and getattr(settings, "psk", None) is not None:
                    try:
                        psk_bytes = bytes(settings.psk) or b""
                    except Exception:
                        psk_bytes = b""
                uplink_enabled = False
                downlink_enabled = False
                position_precision = 0
                if settings:
                    uplink_enabled = bool(
                        getattr(settings, "uplink_enabled", False))
                    downlink_enabled = bool(
                        getattr(settings, "downlink_enabled", False))
                    mod_settings = getattr(settings, "module_settings", None)
                    if mod_settings is not None:
                        try:
                            position_precision = int(
                                getattr(mod_settings, "position_precision", 0))
                        except Exception:
                            position_precision = 0
                channels.append({
                    "index": ch.index,
                    "name":  name or (
                        f"Channel {ch.index}" if role_int else ""),
                    "role":  role_name,
                    "psk":               psk_bytes,
                    "uplink_enabled":    uplink_enabled,
                    "downlink_enabled":  downlink_enabled,
                    "position_precision": position_precision,
                })
            active_names = [c['name'] for c in channels
                            if c['role'] != 'DISABLED']
            log.info(f"Channels found: {active_names}")
            self.channelsUpdated.emit(channels)
        except Exception:
            log.exception("Error fetching channels")

    def add_channel(self, name: str, psk: bytes = b"",
                    uplink: bool = False, downlink: bool = False) -> bool:
        """Create a new SECONDARY channel in the first free slot.

        Args:
            name: 1..11 char channel name
            psk:  encryption key. Empty bytes → use default LongFast key.
                  Single byte 0x01 → use default (legacy marker).
                  16 bytes → AES-128; 32 bytes → AES-256; anything else is
                  rejected by the firmware so we validate here.
            uplink, downlink: MQTT bridge flags
        Returns True on success, False otherwise.
        """
        if not self.is_connected:
            self.errorMessage.emit(t("err.not_connected"))
            return False
        if not name or len(name) > 11:
            self.errorMessage.emit(t("channels.err_name_length"))
            return False
        if psk and len(psk) not in (0, 1, 16, 32):
            self.errorMessage.emit(t("channels.err_psk_length"))
            return False
        try:
            local = self._iface.localNode
            # Find first DISABLED slot at index >= 1 (index 0 is PRIMARY).
            target = None
            for ch in (local.channels or []):
                role = int(getattr(ch, "role", 0) or 0)
                if ch.index >= 1 and role == 0:   # DISABLED
                    target = ch
                    break
            if target is None:
                self.errorMessage.emit(t("channels.err_no_slot"))
                return False
            # Compose the new ChannelSettings
            target.settings.name = name
            try:
                target.settings.psk = psk
            except Exception:
                # psk field expects bytes; some pb wrappers want assignment
                # via CopyFrom — fallback path.
                target.settings.ClearField("psk")
                target.settings.psk = psk
            target.settings.uplink_enabled   = bool(uplink)
            target.settings.downlink_enabled = bool(downlink)
            # Mark as SECONDARY
            target.role = 2
            log.info(f"add_channel: writing slot {target.index} "
                     f"name={name!r} psk_len={len(psk)}")
            local.writeChannel(target.index)
            # Re-publish so the UI refreshes
            self._publish_channels()
            return True
        except Exception as e:
            log.exception("add_channel failed")
            self.errorMessage.emit(t("channels.err_save", str(e)))
            return False

    def update_channel(self, index: int, *,
                       name: Optional[str] = None,
                       psk: Optional[bytes] = None,
                       uplink: Optional[bool] = None,
                       downlink: Optional[bool] = None,
                       position_precision: Optional[int] = None) -> bool:
        """Update an existing channel. Only non-None fields are touched.

        For the PRIMARY channel (index 0) name/psk changes break compat with
        the rest of the mesh — callers should warn the user up front. This
        function applies whatever is requested regardless.
        """
        if not self.is_connected:
            self.errorMessage.emit(t("err.not_connected"))
            return False
        try:
            local = self._iface.localNode
            target = None
            for ch in (local.channels or []):
                if int(ch.index) == int(index):
                    target = ch
                    break
            if target is None:
                self.errorMessage.emit(t("channels.err_not_found", index))
                return False
            if name is not None:
                if len(name) > 11:
                    self.errorMessage.emit(t("channels.err_name_length"))
                    return False
                target.settings.name = name
            if psk is not None:
                if len(psk) not in (0, 1, 16, 32):
                    self.errorMessage.emit(t("channels.err_psk_length"))
                    return False
                try:
                    target.settings.psk = psk
                except Exception:
                    target.settings.ClearField("psk")
                    target.settings.psk = psk
            if uplink is not None:
                target.settings.uplink_enabled = bool(uplink)
            if downlink is not None:
                target.settings.downlink_enabled = bool(downlink)
            if position_precision is not None:
                try:
                    target.settings.module_settings.position_precision = \
                        int(position_precision)
                except Exception:
                    pass
            log.info(f"update_channel: writing slot {index} "
                     f"(name={name!r} psk={'set' if psk is not None else '-'} "
                     f"uplink={uplink} downlink={downlink} "
                     f"pos_prec={position_precision})")
            local.writeChannel(int(index))
            self._publish_channels()
            return True
        except Exception as e:
            log.exception("update_channel failed")
            self.errorMessage.emit(t("channels.err_save", str(e)))
            return False

    def remove_channel(self, index: int) -> bool:
        """Disable (= remove) a SECONDARY channel.

        Refuses to remove the PRIMARY channel (index 0) which would break
        the device. To repurpose the PRIMARY slot, edit it instead.
        """
        if not self.is_connected:
            self.errorMessage.emit(t("err.not_connected"))
            return False
        if int(index) == 0:
            self.errorMessage.emit(t("channels.err_cannot_remove_primary"))
            return False
        try:
            local = self._iface.localNode
            target = None
            for ch in (local.channels or []):
                if int(ch.index) == int(index):
                    target = ch
                    break
            if target is None:
                self.errorMessage.emit(t("channels.err_not_found", index))
                return False
            target.role = 0   # DISABLED
            # Wipe settings so the slot is fully free for future re-use
            try:
                target.settings.name = ""
                target.settings.psk = b""
                target.settings.uplink_enabled = False
                target.settings.downlink_enabled = False
            except Exception:
                pass
            log.info(f"remove_channel: disabling slot {index}")
            local.writeChannel(int(index))
            self._publish_channels()
            return True
        except Exception as e:
            log.exception("remove_channel failed")
            self.errorMessage.emit(t("channels.err_save", str(e)))
            return False

    # =======================================================================
    # ACTIUNI - apelate din UI
    #
    # IMPORTANT: sendPosition / sendTelemetry / sendTraceRoute din biblioteca
    # meshtastic-python sunt BLOCANTE (default timeout 300s) cand wantResponse=True.
    # Trebuie sa le rulam pe THREAD-uri de background, altfel inghetam UI-ul.
    # Raspunsul real ajunge oricum asincron prin pubsub.receive si actualizeaza
    # tabul Info / Harta automat.
    # =======================================================================
    def get_message_status(self, packet_id):
        """Return delivery info for a previously-sent message.

        Returns None if the packet ID is unknown (e.g., from a session before
        the app was restarted). Otherwise:
            {
              "meta": {text, destination, channel, sent_at, is_broadcast, want_ack},
              "responders": [{from_id, status, error, time, snr, rssi, hop_start, hop_limit}, ...]
            }
        For DMs (wantAck=True) the destination's ACK appears in 'responders'.
        For broadcasts, any intermediate router that forwards our packet may
        also emit a routing ACK; those appear in 'responders' too.
        """
        if not packet_id:
            return None
        try:
            pid = int(packet_id)
        except Exception:
            return None
        meta = self._sent_msg_meta.get(pid)
        if not meta:
            return None
        return {"meta": meta,
                "responders": list(self._sent_msg_acks.get(pid, []))}

    @staticmethod
    def scan_ble_devices(timeout: float = 5.0) -> list:
        """Scan for nearby Meshtastic BLE devices.

        Blocks for ~`timeout` seconds while Bleak does an active scan.
        Should be called from a worker thread, not the Qt main thread,
        otherwise the UI freezes for the duration of the scan.

        Returns a list of dicts:
            [{"name": "Meshtastic_a8b4", "address": "AA:BB:CC:DD:EE:FF",
              "rssi": -60}, ...]

        Empty list if scanning fails or no devices found.
        """
        try:
            from meshtastic.ble_interface import BLEInterface
            raw = BLEInterface.scan() or []
        except Exception as e:
            log.exception("BLE scan failed")
            return []
        out = []
        for item in raw:
            try:
                # bleak BLEDevice has .name and .address attributes
                name = getattr(item, "name", None) or "Unknown"
                addr = getattr(item, "address", None)
                if not addr:
                    continue
                # rssi may not always be exposed
                rssi = getattr(item, "rssi", None)
                out.append({
                    "name":    str(name),
                    "address": str(addr),
                    "rssi":    int(rssi) if rssi is not None else None,
                })
            except Exception:
                log.exception("Skipping malformed BLE scan entry")
        # Sort by signal strength (strongest first), then by name
        out.sort(key=lambda d: (-(d["rssi"] or -999), d["name"].lower()))
        return out

    # ===================================================================
    # RF SCAN MODE
    # ===================================================================
    @property
    def is_scanning(self) -> bool:
        return self._scanning

    def start_scan(self, pause_callback=None):
        """Enter RF scan mode: dedicate the link to capturing all activity.

        Pauses the app's background chatter via pause_callback (the UI passes
        a function that stops the script scheduler + telemetry polling) so
        the scan is the priority. We do NOT change the device config here —
        an honest passive listen on the current band+preset. (Preset cycling
        is a separate, explicit deep-scan action.)
        """
        if not self.is_connected:
            log.warning("start_scan called while not connected")
            return False
        if self._scanning:
            return True
        log.info("=== RF SCAN START ===")
        self._scanning = True
        self._scan_packets = []
        self._scan_started_at = int(time.time())
        self._scan_pause_cb = pause_callback
        if pause_callback:
            try:
                pause_callback(True)   # pause background activity
            except Exception:
                log.exception("scan pause callback failed")
        self.scanStateChanged.emit(True)
        return True

    def stop_scan(self) -> dict:
        """Exit scan mode, resume background activity, return the report."""
        if not self._scanning:
            return {}
        log.info("=== RF SCAN STOP ===")
        self._scanning = False
        if getattr(self, "_scan_pause_cb", None):
            try:
                self._scan_pause_cb(False)   # resume background activity
            except Exception:
                log.exception("scan resume callback failed")
        report = self.build_scan_report()
        self.scanStateChanged.emit(False)
        self.scanFinished.emit(report)
        return report

    def emit_scan_progress(self, duration: int):
        """Called by the UI timer to push a progress update."""
        if not self._scanning:
            return
        elapsed = int(time.time()) - self._scan_started_at
        self.scanProgress.emit({
            "elapsed":  elapsed,
            "duration": duration,
            "packets":  len(self._scan_packets),
            "senders":  len({p[1] for p in self._scan_packets}),
        })

    def build_scan_report(self) -> dict:
        """Build a comprehensive trust report from the captured scan packets.

        Combines every detection method available to a stock node:
          • frame count + rate (generic activity level)
          • unique senders + their signal quality
          • per-port breakdown (what kinds of traffic)
          • hop distribution (direct neighbours vs relayed)
          • SNR/RSSI distribution (how strong / how close)
          • channels we can decrypt (configured PSKs)
          • channel utilization from the device's own telemetry
          • the exact freq/preset we listened on
        """
        pkts = list(self._scan_packets)
        now = int(time.time())
        duration = max(1, now - self._scan_started_at)

        senders = {}
        ports = {}
        hop_hist = {}
        snrs, rssis = [], []
        channels_idx = set()
        for ts, frm, port, snr, rssi, hops, ch in pkts:
            senders.setdefault(frm, {"count": 0, "snr": [], "rssi": []})
            senders[frm]["count"] += 1
            if snr: senders[frm]["snr"].append(snr)
            if rssi: senders[frm]["rssi"].append(rssi)
            ports[port] = ports.get(port, 0) + 1
            if hops is not None:
                hop_hist[hops] = hop_hist.get(hops, 0) + 1
            if snr: snrs.append(snr)
            if rssi: rssis.append(rssi)
            if ch is not None: channels_idx.add(ch)

        # Channels we can actually decrypt (configured locally)
        decrypt_channels = []
        try:
            for c in (self._iface.localNode.channels or []):
                if int(getattr(c, "role", 0) or 0) != 0:
                    decrypt_channels.append(c.settings.name or "(primary)")
        except Exception:
            pass

        # Channel utilization from device telemetry (its own air-busy metric)
        cu_recent = [v for ts, v in self._channel_util_log
                     if now - ts <= 600]
        cu_avg = round(sum(cu_recent) / len(cu_recent), 2) if cu_recent else None

        def _rng(v): return (min(v), max(v)) if v else (None, None)
        snr_lo, snr_hi = _rng(snrs)
        rssi_lo, rssi_hi = _rng(rssis)

        # Direct neighbours = packets that arrived with 0 hops
        direct_neighbours = hop_hist.get(0, 0)

        freq = self.get_radio_frequency() if self.is_connected else None
        total = len(pkts)
        rate = round(total / duration * 60, 1)  # packets/min

        # Build per-sender summary (top 10 by count)
        sender_rows = []
        for frm, d in sorted(senders.items(),
                             key=lambda x: -x[1]["count"])[:10]:
            avg_snr = (round(sum(d["snr"]) / len(d["snr"]), 1)
                       if d["snr"] else None)
            avg_rssi = (round(sum(d["rssi"]) / len(d["rssi"]))
                        if d["rssi"] else None)
            sender_rows.append({
                "id": frm, "count": d["count"],
                "avg_snr": avg_snr, "avg_rssi": avg_rssi,
            })

        return {
            "duration":            duration,
            "total_packets":       total,
            "packets_per_min":     rate,
            "unique_senders":      len(senders),
            "direct_neighbours":   direct_neighbours,
            "by_port":             ports,
            "hop_histogram":       hop_hist,
            "snr_range":           (snr_lo, snr_hi),
            "rssi_range":          (rssi_lo, rssi_hi),
            "decryptable_channels": decrypt_channels,
            "channels_seen_idx":   sorted(channels_idx),
            "channel_util_avg":    cu_avg,
            "frequency":           freq,
            "senders":             sender_rows,
        }

    def get_rf_activity_report(self) -> dict:
        """Analyse recently received packets to characterise the RF activity
        around this node — WITHOUT changing any radio settings.

        A Meshtastic radio can only "hear" traffic on the band + preset it's
        currently configured for, and can only decode packets whose channel
        PSK it knows. So this report is built from what actually arrived:

          • generic_lora        — are we receiving ANY LoRa frames at all?
          • meshtastic_compatible — frames that parsed as Meshtastic packets
          • decodable_no_key    — packets we could read the header of
          • exact_channel       — channels we actually decrypted (know PSK)
          • by_port             — breakdown of decoded packet types
          • unique_senders      — distinct nodes heard
          • snr / rssi ranges   — signal quality of what we heard

        Returns a dict the Scanner tab renders into plain-language verdicts.
        """
        import time as _t
        now = int(_t.time())
        window = 600  # last 10 minutes

        total_rx = 0
        meshtastic_pkts = 0
        senders = set()
        ports = {}
        snrs = []
        rssis = []
        channels_seen = set()

        for port, dq in self._rx_packets.items():
            for entry in dq:
                ts = entry[0]
                if now - ts > window:
                    continue
                total_rx += 1
                meshtastic_pkts += 1  # everything we logged is decoded mesh
                ports[port] = ports.get(port, 0) + 1
                if len(entry) > 1 and entry[1]:
                    senders.add(entry[1])
                if len(entry) > 2 and entry[2] is not None:
                    snrs.append(entry[2])
                if len(entry) > 3 and entry[3] is not None:
                    rssis.append(entry[3])

        # Channels we can decrypt = the ones configured locally
        try:
            for ch in (self._iface.localNode.channels or []):
                if int(getattr(ch, "role", 0) or 0) != 0:
                    nm = ch.settings.name or "(primary)"
                    channels_seen.add(nm)
        except Exception:
            pass

        freq = self.get_radio_frequency() if self.is_connected else None

        def _rng(vals):
            return (min(vals), max(vals)) if vals else (None, None)
        snr_lo, snr_hi = _rng(snrs)
        rssi_lo, rssi_hi = _rng(rssis)

        return {
            "window_secs":          window,
            "total_rx":             total_rx,
            "meshtastic_pkts":      meshtastic_pkts,
            "unique_senders":       len(senders),
            "by_port":              ports,
            "decryptable_channels": sorted(channels_seen),
            "snr_range":            (snr_lo, snr_hi),
            "rssi_range":           (rssi_lo, rssi_hi),
            "frequency":            freq,
            "connected":            self.is_connected,
        }

    def get_radio_frequency(self) -> Optional[dict]:
        """Compute the exact LoRa frequency the device is transmitting on.

        Meshtastic derives the operating frequency from:
          • the region's frequency band (freq_start..freq_end)
          • the modem preset's bandwidth
          • the channel number (lora.channel_num, or derived from the
            primary channel name hash if 0)

        Returns a dict with center frequency (MHz), region, preset,
        bandwidth and channel number — or None if not connected.

        Frequency formula (matches firmware RadioInterface.cpp):
            num_channels = floor((freq_end - freq_start) / (bandwidth/1000))
            freq = freq_start + (bandwidth/2000) + (channel_num * bandwidth/1000)
        """
        if not self.is_connected:
            return None
        try:
            cfg = self._iface.localNode.localConfig.lora
        except Exception:
            return None

        # Region frequency bands (MHz) — start, end. From Meshtastic firmware.
        REGIONS = {
            1:  ("US",      902.0, 928.0),
            2:  ("EU_433",  433.0, 434.0),
            3:  ("EU_868",  869.4, 869.65),
            4:  ("CN",      470.0, 510.0),
            5:  ("JP",      920.8, 927.8),
            6:  ("ANZ",     915.0, 928.0),
            7:  ("KR",      920.0, 923.0),
            8:  ("TW",      920.0, 925.0),
            9:  ("RU",      868.7, 869.2),
            10: ("IN",      865.0, 867.0),
            11: ("NZ_865",  864.0, 868.0),
            12: ("TH",      920.0, 925.0),
            13: ("LORA_24", 2400.0, 2483.5),
            14: ("UA_433",  433.0, 434.7),
            15: ("UA_868",  868.0, 868.6),
            16: ("MY_433",  433.0, 435.0),
            17: ("MY_919",  919.0, 924.0),
            18: ("SG_923",  917.0, 925.0),
        }
        # Modem preset → bandwidth in kHz. From firmware.
        PRESETS = {
            0:  ("LONG_FAST",      250.0),
            1:  ("LONG_SLOW",      125.0),
            2:  ("VERY_LONG_SLOW", 62.5),
            3:  ("MEDIUM_SLOW",    250.0),
            4:  ("MEDIUM_FAST",    250.0),
            5:  ("SHORT_SLOW",     250.0),
            6:  ("SHORT_FAST",     250.0),
            7:  ("LONG_MODERATE",  125.0),
            8:  ("SHORT_TURBO",    500.0),
            9:  ("LONG_TURBO",     500.0),
        }
        region_num  = int(getattr(cfg, "region", 0) or 0)
        preset_num  = int(getattr(cfg, "modem_preset", 0) or 0)
        channel_num = int(getattr(cfg, "channel_num", 0) or 0)

        region = REGIONS.get(region_num)
        preset = PRESETS.get(preset_num)
        if not region or not preset:
            return None

        region_name, freq_start, freq_end = region
        preset_name, bw_khz = preset
        bw_mhz = bw_khz / 1000.0

        # Number of channels that fit in the band
        num_channels = max(1, int((freq_end - freq_start) / bw_mhz))

        # If channel_num is 0, the firmware derives it from the primary
        # channel name hash. We approximate using the same xor-hash.
        if channel_num == 0:
            try:
                ch_name = ""
                for ch in self._iface.localNode.channels:
                    if int(getattr(ch, "role", 0)) == 1:  # PRIMARY
                        ch_name = ch.settings.name or ""
                        break
                if not ch_name:
                    ch_name = "LongFast"  # default name when blank
                h = 0
                for c in ch_name.encode():
                    h ^= c
                channel_num = (h % num_channels)
            except Exception:
                channel_num = 0

        freq = freq_start + (bw_mhz / 2.0) + (channel_num * bw_mhz)
        return {
            "frequency_mhz": round(freq, 4),
            "region":        region_name,
            "preset":        preset_name,
            "bandwidth_khz": bw_khz,
            "channel_num":   channel_num,
            "num_channels":  num_channels,
        }

    def get_last_rx_tx(self) -> dict:
        """Return timestamps + age of the last received and transmitted packet.

        Used by the Info tab to show "last RX 12s ago / last TX 3m ago".
        """
        import time as _t
        now = int(_t.time())
        last_rx_ts = None
        for dq in self._rx_packets.values():
            for ts, *_ in dq:
                if last_rx_ts is None or ts > last_rx_ts:
                    last_rx_ts = ts
        last_tx_ts = None
        if self._tx_packets:
            last_tx_ts = max(ts for ts, *_ in self._tx_packets)
        return {
            "last_rx_ts":  last_rx_ts,
            "last_tx_ts":  last_tx_ts,
            "last_rx_age": (now - last_rx_ts) if last_rx_ts else None,
            "last_tx_age": (now - last_tx_ts) if last_tx_ts else None,
        }

    @staticmethod
    def scan_network_for_devices(timeout: float = 0.3,
                                 progress_cb=None) -> list:
        """Scan the local /24 subnet for Meshtastic TCP devices (port 4403).

        Determines the local IP, then probes every host in the same /24
        for an open port 4403 (the Meshtastic TCP API port). Returns a
        list of dicts: [{"ip": "10.10.10.187", "hostname": "..."}].

        Should be run from a worker thread — scanning 254 hosts takes a
        few seconds even with a short timeout. progress_cb(done, total)
        is called as it scans.
        """
        import socket
        import concurrent.futures

        # Find our local IP (the one used to reach the internet)
        local_ip = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            try:
                local_ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                log.warning("Could not determine local IP for network scan")
                return []
        if not local_ip or local_ip.startswith("127."):
            return []

        subnet = ".".join(local_ip.split(".")[:3])
        found = []

        def probe(host_ip):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(timeout)
                    if sock.connect_ex((host_ip, 4403)) == 0:
                        # Port open — try reverse DNS for a friendly name
                        try:
                            hostname = socket.gethostbyaddr(host_ip)[0]
                        except Exception:
                            hostname = ""
                        return {"ip": host_ip, "hostname": hostname}
            except Exception:
                pass
            return None

        hosts = [f"{subnet}.{i}" for i in range(1, 255)]
        total = len(hosts)
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
            futures = {pool.submit(probe, h): h for h in hosts}
            for fut in concurrent.futures.as_completed(futures):
                done += 1
                if progress_cb:
                    try: progress_cb(done, total)
                    except Exception: pass
                r = fut.result()
                if r:
                    found.append(r)
        # Sort by last octet
        found.sort(key=lambda d: int(d["ip"].split(".")[-1]))
        log.info(f"Network scan found {len(found)} device(s) on :4403")
        return found

    def get_mesh_health(self) -> dict:
        """Compute a snapshot of mesh activity for diagnostics.

        Helps diagnose the "no messages for 48h" symptom: combines our
        TX/RX counters with the device's own channel_utilization
        measurements so users can tell apart:
          • channel quiet + zero RX        → mesh genuinely silent
          • channel busy + decoded RX low  → likely RF noise / PSK mismatch
          • channel busy + decoded RX high → all normal

        Returned dict:
            {
              "session_seconds":   int,
              "tx_total":          int,
              "tx_last_hour":      int,
              "rx_by_port":        {portnum: {"total": n, "1h": n, "24h": n}},
              "rx_unique_nodes_1h": int,
              "rx_unique_nodes_24h": int,
              "rx_last_packet_age": int (seconds since last non-self RX, -1 if none),
              "rx_last_text_age":   int (seconds since last TEXT_MESSAGE_APP RX),
              "channel_util_avg":   float (% over all samples, -1 if none),
              "channel_util_max":   float,
              "channel_util_last":  float,
              "diagnostic":         str (one-line plain-English hint),
            }
        """
        now = int(time.time())
        out: dict = {
            "session_seconds":     now - self._session_started_at,
            "tx_total":            len(self._tx_packets),
            "tx_last_hour":        sum(1 for ts, _ in self._tx_packets
                                       if now - ts <= 3600),
            "rx_by_port":          {},
            "rx_unique_nodes_1h":  0,
            "rx_unique_nodes_24h": 0,
            "rx_last_packet_age":  -1,
            "rx_last_text_age":    -1,
            "channel_util_avg":   -1.0,
            "channel_util_max":   -1.0,
            "channel_util_last":  -1.0,
            "diagnostic":          "",
        }
        nodes_1h: set = set()
        nodes_24h: set = set()
        latest_rx = 0
        latest_text = 0
        for port, dq in self._rx_packets.items():
            total = len(dq)
            n1h = n24h = 0
            for ts, who, *_ in dq:
                if now - ts <= 3600:
                    n1h += 1
                    nodes_1h.add(who)
                if now - ts <= 86400:
                    n24h += 1
                    nodes_24h.add(who)
                if ts > latest_rx:
                    latest_rx = ts
                if port == "TEXT_MESSAGE_APP" and ts > latest_text:
                    latest_text = ts
            out["rx_by_port"][port] = {"total": total, "1h": n1h, "24h": n24h}
        out["rx_unique_nodes_1h"]  = len(nodes_1h)
        out["rx_unique_nodes_24h"] = len(nodes_24h)
        if latest_rx > 0:
            out["rx_last_packet_age"] = now - latest_rx
        if latest_text > 0:
            out["rx_last_text_age"] = now - latest_text

        # Channel utilization stats
        if self._channel_util_log:
            vals = [v for _, v in self._channel_util_log]
            out["channel_util_avg"]  = sum(vals) / len(vals)
            out["channel_util_max"]  = max(vals)
            out["channel_util_last"] = vals[-1]

        # Plain-English hint
        out["diagnostic"] = self._diagnose_health(out)
        return out

    @staticmethod
    def _diagnose_health(h: dict) -> str:
        """Plain-English one-liner from the health snapshot."""
        cu_avg = h.get("channel_util_avg") or -1
        cu_max = h.get("channel_util_max") or -1
        rx_1h  = sum(p["1h"] for p in h["rx_by_port"].values())
        text_1h = h["rx_by_port"].get("TEXT_MESSAGE_APP", {}).get("1h", 0)
        nodes_1h = h["rx_unique_nodes_1h"]

        if cu_avg < 0:
            return ("No telemetry samples yet — wait ~60 s for the device "
                    "to publish its first reading.")
        if rx_1h == 0 and cu_avg < 2.0:
            return ("Channel is quiet and we've decoded nothing in the last "
                    "hour. The mesh appears genuinely silent — no neighbours "
                    "transmitting nearby.")
        if rx_1h == 0 and cu_avg >= 10.0:
            return ("⚠ Channel is busy (~%.0f%% util) but we've decoded ZERO "
                    "packets in the last hour. This usually means RF "
                    "interference on 868 MHz or a PSK mismatch with the "
                    "mesh you're trying to join. Check your channel's PSK "
                    "matches the rest of the mesh." % cu_avg)
        if text_1h == 0 and rx_1h > 0:
            return ("Decoding non-text packets (telemetry/position) but no "
                    "text messages in the last hour. Mesh is alive but quiet "
                    "— that's normal outside peak hours.")
        if nodes_1h >= 1:
            return ("✓ Mesh active — heard %d neighbour(s), %d text "
                    "message(s) decoded in the last hour."
                    % (nodes_1h, text_1h))
        return "Mesh status: %d RX, %d TX in the last hour." % (
            rx_1h, h["tx_last_hour"])

    def send_text(self, text: str, channel_index: int = 0,
                  destination_id: Optional[str] = None,
                  want_ack: Optional[bool] = None,
                  reply_id: Optional[int] = None):
        """Send a text message.

        Args:
            reply_id: When set, the message is sent with the protobuf
                replyId field referencing an earlier packet — clients that
                support threading will display the new message as a reply.

        Returns:
          • packet ID (int) on success — usable as a key for ACK tracking.
            For DMs (destination_id set), wantAck defaults to True so the
            recipient sends back a ROUTING_APP ACK we can listen for.
          • None on failure.

        Returns True/None preserves backward compatibility for callers that
        just check the truthiness — an int is truthy.
        """
        if not self.is_connected:
            self.errorMessage.emit(t("err.not_connected"))
            return None
        if not text or not text.strip():
            return None
        # Default: enable wantAck for DMs (so we get delivery confirmation),
        # leave broadcasts as-is (no per-recipient ACK in mesh broadcasts).
        is_broadcast = (not destination_id
                        or destination_id in ("^all", "!ffffffff"))
        if want_ack is None:
            want_ack = not is_broadcast
        try:
            kwargs = {"channelIndex": channel_index, "wantAck": bool(want_ack)}
            if not is_broadcast:
                kwargs["destinationId"] = destination_id
            # replyId — newer meshtastic-python versions support this kwarg
            # natively on sendText. Pass it through; if the library is too
            # old it'll raise TypeError which we catch and retry without it.
            if reply_id:
                kwargs["replyId"] = int(reply_id)
            log.info(f"Sending text: ch={channel_index} dest={destination_id} "
                     f"want_ack={want_ack} reply_id={reply_id} text={text[:60]!r}")
            try:
                pkt = self._iface.sendText(text, **kwargs)
            except TypeError as e:
                # Older meshtastic-python: drop replyId and retry. We log
                # so user knows replies will not be threaded for the peer.
                if reply_id and "replyId" in kwargs:
                    log.warning(f"sendText does not accept replyId on this "
                                f"meshtastic-python version ({e}); resending "
                                f"without reply threading")
                    kwargs.pop("replyId", None)
                    pkt = self._iface.sendText(text, **kwargs)
                else:
                    raise
            # Extract packet ID from the protobuf returned by sendText.
            # Versions of meshtastic-python return a MeshPacket with .id field.
            pkt_id = None
            try:
                pkt_id = int(getattr(pkt, "id", None) or 0) or None
            except Exception:
                pkt_id = None
            log.info(f"  -> packet id={pkt_id}")
            # Register in the ACK tracker so we can correlate later
            # ROUTING_APP responses with this message.
            if pkt_id:
                self._sent_msg_acks[pkt_id] = []
                self._sent_msg_meta[pkt_id] = {
                    "text": text,
                    "destination": destination_id if not is_broadcast else None,
                    "channel": channel_index,
                    "sent_at": int(time.time()),
                    "is_broadcast": is_broadcast,
                    "want_ack": bool(want_ack),
                }
                self._sent_msg_order.append(pkt_id)
                # Evict oldest if over 200
                while len(self._sent_msg_order) > 200:
                    old = self._sent_msg_order.pop(0)
                    self._sent_msg_acks.pop(old, None)
                    self._sent_msg_meta.pop(old, None)

            # V20-turn7: announce that we just sent a message so the
            # Messages tab can render the bubble + persist to history.
            # This unifies what UI-typed and script-sent messages do —
            # without it, scripts could send text that never appeared in
            # the conversation log.
            try:
                self.messageSent.emit({
                    "fromId":    self.my_node_id or "",
                    "toId":      destination_id if not is_broadcast else "^all",
                    "channel":   int(channel_index),
                    "text":      text,
                    "packetId":  pkt_id,
                    "rxTime":    int(time.time()),
                    "replyId":   int(reply_id) if reply_id else None,
                    # Broadcasts have no per-recipient ACK; DMs wait
                    # for ROUTING_APP and start as 'pending'.
                    "ackStatus": "pending" if (not is_broadcast and want_ack)
                                  else "sent",
                })
            except Exception:
                log.exception("Failed to emit messageSent")

            # V20-turn8: track this TX for mesh-health reporting
            try:
                self._tx_packets.append((
                    int(time.time()),
                    destination_id if not is_broadcast else "^all",
                ))
            except Exception:
                pass

            return pkt_id if pkt_id else True  # True if id unavailable
        except Exception as e:
            log.exception("send_text failed")
            self.errorMessage.emit(t("err.send_failed", str(e)))
            return None

    def send_reaction(self, emoji: str, reply_id: int,
                      channel_index: int = 0,
                      destination_id: Optional[str] = None) -> bool:
        """Send a reaction (tapback emoji) on an earlier message.

        Reactions are EMOJI_APP packets whose payload is the emoji UTF-8
        bytes and whose `replyId` field references the original message.
        Meshtastic clients display them as a small chip below the bubble.

        Args:
            emoji: single grapheme cluster (e.g. "❤️", "👍", "😂")
            reply_id: packet id of the message being reacted to
            channel_index: channel to send on (must match original convo)
            destination_id: peer node id for DM reactions; None for broadcast.

        Returns True on send success, False otherwise.
        """
        if not self.is_connected:
            self.errorMessage.emit(t("err.not_connected"))
            return False
        if not emoji or not reply_id:
            return False
        try:
            from meshtastic import portnums_pb2
            # EMOJI_APP is the public portnum name; the underlying integer
            # value (71) is what the firmware looks at.
            try:
                portnum = portnums_pb2.PortNum.EMOJI_APP
            except AttributeError:
                portnum = 71
            is_broadcast = (not destination_id
                            or destination_id in ("^all", "!ffffffff"))
            kwargs = {
                "data": emoji.encode("utf-8"),
                "portNum": portnum,
                "channelIndex": channel_index,
                "wantAck": False,
                "replyId": int(reply_id),
            }
            if not is_broadcast:
                kwargs["destinationId"] = destination_id
            log.info(f"Sending reaction: emoji={emoji!r} reply_id={reply_id} "
                     f"ch={channel_index} dest={destination_id}")
            try:
                self._iface.sendData(**kwargs)
            except TypeError:
                # very old meshtastic-python without replyId on sendData
                kwargs.pop("replyId", None)
                self._iface.sendData(**kwargs)
            return True
        except Exception as e:
            log.exception("send_reaction failed")
            self.errorMessage.emit(t("err.send_failed", str(e)))
            return False

    def _run_in_background(self, name: str, fn):
        """Ruleaza fn() pe un thread separat. Folosit pentru apeluri blocante
        din biblioteca meshtastic ca sa nu inghete UI-ul."""
        t = threading.Thread(target=fn, daemon=True, name=name)
        t.start()

    def request_position(self, dest_id: str) -> bool:
        if not self.is_connected:
            return False
        iface = self._iface
        def worker():
            try:
                iface.sendPosition(destinationId=dest_id, wantResponse=True)
                log.info(f"request_position to {dest_id} — completed")
            except Exception as e:
                # timeout is NORMAL - response arrives async via pubsub.receive
                log.info(f"request_position to {dest_id} — wait timeout (ok): {e}")
        self._run_in_background(f"req-pos-{dest_id}", worker)
        log.info(f"Position request sent to {dest_id} (async response)")
        return True

    def request_telemetry(self, dest_id: str) -> bool:
        if not self.is_connected:
            return False
        iface = self._iface
        def worker():
            try:
                iface.sendTelemetry(destinationId=dest_id, wantResponse=True)
                log.info(f"request_telemetry to {dest_id} — completed")
            except Exception as e:
                log.info(f"request_telemetry to {dest_id} — wait timeout (ok): {e}")
        self._run_in_background(f"req-telem-{dest_id}", worker)
        log.info(f"Telemetry request sent to {dest_id} (async response)")
        return True

    def request_telemetry_with_popup(self, dest_id: str) -> bool:
        """Request telemetry AND fire popup when response arrives."""
        self._popup_pending[dest_id] = int(time.time())
        log.info(f"Telemetry popup pending for {dest_id}")
        return self.request_telemetry(dest_id)

    def _maybe_fire_telemetry_popup(self, node_id: str):
        """Verifica daca user-ul a cerut explicit telemetrie pentru node_id; daca
        DA si raspunsul a sosit in <60s, declanseaza popup."""
        if node_id not in self._popup_pending:
            return
        ts = self._popup_pending.pop(node_id)
        if int(time.time()) - ts > self._popup_timeout:
            log.info(f"Popup for {node_id} expired ({self._popup_timeout}s), ignoring")
            return
        log.info(f"Popup TELEMETRY ready for {node_id} -> firing signal")
        self.telemetryPopupReady.emit(node_id)

    def traceroute(self, dest_id: str, channel_index: int = 0) -> bool:
        if not self.is_connected:
            return False
        iface = self._iface
        def worker():
            try:
                iface.sendTraceRoute(dest=dest_id, hopLimit=5,
                                     channelIndex=channel_index)
                log.info(f"traceroute to {dest_id} — completed")
            except Exception as e:
                log.info(f"traceroute to {dest_id} — wait timeout (ok): {e}")
        self._run_in_background(f"trace-{dest_id}", worker)
        log.info(f"Traceroute sent to {dest_id} (async response)")
        return True

    def reboot(self):
        if not self.is_connected:
            return
        try:
            self._iface.localNode.reboot()
        except Exception:
            log.exception("Reboot failed")
            self.errorMessage.emit(t("err.reboot_failed"))

    def set_owner(self, long_name: str, short_name: str):
        if not self.is_connected:
            return
        try:
            self._iface.localNode.setOwner(long_name=long_name,
                                           short_name=short_name)
        except Exception:
            log.exception("setOwner failed")
            self.errorMessage.emit(t("err.set_owner_failed"))

    # =======================================================================
    # V20-turn4: Remote GPIO control + file management
    #
    # GPIO works via RemoteHardwareClient which encapsulates the protobuf
    # HardwareMessage sent to a remote node's REMOTE_HARDWARE_APP port.
    # The remote node must have the Remote Hardware module enabled and
    # its available_pins configured for any pin to be addressable.
    # =======================================================================
    def gpio_read(self, dest_id: str, pin_mask: int) -> bool:
        """Read the state of remote GPIO pins selected by `pin_mask`.

        Result arrives asynchronously as a GPIOS_CHANGED packet which the
        meshtastic library logs; the response isn't surfaced as a Qt signal
        in this build — users see it in the console (raw packets toggle).
        """
        if not self.is_connected:
            self.errorMessage.emit(t("err.not_connected"))
            return False
        try:
            from meshtastic.remote_hardware import RemoteHardwareClient
            client = RemoteHardwareClient(self._iface)
            log.info(f"gpio_read dest={dest_id} mask=0x{int(pin_mask):x}")
            # Library API: readGPIOs(node_id, mask, callback=None)
            client.readGPIOs(dest_id, int(pin_mask))
            return True
        except Exception as e:
            log.exception("gpio_read failed")
            self.errorMessage.emit(t("err.send_failed", str(e)))
            return False

    def gpio_write(self, dest_id: str, pin_mask: int, value_mask: int) -> bool:
        """Set remote GPIO pins selected by `pin_mask` to `value_mask`.

        Bits in pin_mask choose which pins are touched; for each selected
        pin, the corresponding bit in value_mask is the new level.
        """
        if not self.is_connected:
            self.errorMessage.emit(t("err.not_connected"))
            return False
        try:
            from meshtastic.remote_hardware import RemoteHardwareClient
            client = RemoteHardwareClient(self._iface)
            log.info(f"gpio_write dest={dest_id} "
                     f"mask=0x{int(pin_mask):x} value=0x{int(value_mask):x}")
            client.writeGPIOs(dest_id, int(pin_mask), int(value_mask))
            return True
        except Exception as e:
            log.exception("gpio_write failed")
            self.errorMessage.emit(t("err.send_failed", str(e)))
            return False

    def gpio_watch(self, dest_id: str, pin_mask: int) -> bool:
        """Ask the remote node to broadcast a GPIOS_CHANGED message every
        time the selected pins change state. mask=0 disables watching."""
        if not self.is_connected:
            self.errorMessage.emit(t("err.not_connected"))
            return False
        try:
            from meshtastic.remote_hardware import RemoteHardwareClient
            client = RemoteHardwareClient(self._iface)
            log.info(f"gpio_watch dest={dest_id} mask=0x{int(pin_mask):x}")
            client.watchGPIOs(dest_id, int(pin_mask))
            return True
        except Exception as e:
            log.exception("gpio_watch failed")
            self.errorMessage.emit(t("err.send_failed", str(e)))
            return False

    def delete_file(self, path: str) -> bool:
        """Delete a file from the device's flash filesystem.

        Uses the AdminMessage.delete_file_request admin message; available
        from firmware 2.5.x onward. Use with caution — there is no undo.
        """
        if not self.is_connected:
            self.errorMessage.emit(t("err.not_connected"))
            return False
        if not path:
            return False
        try:
            from meshtastic.protobuf import admin_pb2
            from meshtastic import portnums_pb2
            admin = admin_pb2.AdminMessage()
            admin.delete_file_request = path
            log.info(f"delete_file: {path}")
            # Send as admin message to ourselves (the local node) — the
            # protobuf is just an AdminMessage encoded payload.
            self._iface.sendData(
                data=admin.SerializeToString(),
                destinationId=self.my_node_id or "^local",
                portNum=portnums_pb2.PortNum.ADMIN_APP,
                wantAck=True,
            )
            return True
        except Exception as e:
            log.exception("delete_file failed")
            self.errorMessage.emit(t("err.send_failed", str(e)))
            return False

    # =======================================================================
    # UTILITARE
    # =======================================================================
    def _set_state(self, s: str):
        if s != self._state:
            log.info(f"State: {self._state} -> {s}")
            self._state = s
            self.stateChanged.emit(s)

    @staticmethod
    def list_serial_ports() -> List[dict]:
        """Return COM ports with rich metadata for the picker dialog.

        Each entry: device, description, manufacturer, serial_number,
        vid, pid (ints or None), and `likely_meshtastic` bool that flags
        the USB-UART chips typically used by Meshtastic-compatible boards
        (CP210x, CH340/CH341, FT232, ESP32 native USB-JTAG).
        """
        # Well-known USB-UART chip IDs used by Heltec / T-Beam / RAK / Lilygo
        MESHTASTIC_USB_IDS = {
            (0x10C4, 0xEA60),   # Silicon Labs CP210x  (most common — Heltec)
            (0x1A86, 0x7523),   # WCH CH340/CH341 v1
            (0x1A86, 0x5523),   # WCH CH341 v2
            (0x1A86, 0x55D4),   # WCH CH9102F
            (0x0403, 0x6001),   # FTDI FT232R
            (0x0403, 0x6015),   # FTDI FT231X
            (0x303A, 0x1001),   # ESP32-S3 USB-JTAG/Serial (native)
            (0x303A, 0x4001),   # ESP32-S3 USB-OTG
        }
        try:
            from serial.tools import list_ports
            out = []
            for p in list_ports.comports():
                vid = getattr(p, "vid", None)
                pid = getattr(p, "pid", None)
                likely = (vid is not None and pid is not None
                          and (vid, pid) in MESHTASTIC_USB_IDS)
                out.append({
                    "device":            p.device,
                    "description":       p.description or "",
                    "manufacturer":      getattr(p, "manufacturer", "") or "",
                    "serial_number":     getattr(p, "serial_number", "") or "",
                    "vid":               vid,
                    "pid":               pid,
                    "likely_meshtastic": likely,
                })
            # Sort: likely-Meshtastic first, then by COM name
            out.sort(key=lambda d: (not d["likely_meshtastic"],
                                    d["device"].lower()))
            return out
        except Exception:
            log.exception("Error enumerating serial ports")
            return []
