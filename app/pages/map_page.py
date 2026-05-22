"""
Map tab — interactive node view on OpenStreetMap.

Foloseste Leaflet.js + tile-uri OSM. Optional poate folosi PySide6-WebEngine
pentru o experienta complet interactiva. Daca nu e instalat, ofera o lista
de noduri cu link-uri catre Google Maps si OpenStreetMap.
"""

from __future__ import annotations

import json
import logging
import webbrowser
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer, QUrl, QObject, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton,
    QScrollArea, QSizePolicy
)

from ..connection import MeshtasticManager, num_to_id
from ..i18n import t, i18n
from ..theme import Colors

log = logging.getLogger("meshlink.map")


# Verificam disponibilitatea WebEngine - optional
HAS_WEBENGINE = False
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView  # type: ignore
    # in unele medii (container fara display) importul reuseste dar
    # crearea instantei esueaza la rendering. Vom prinde erori la build.
    HAS_WEBENGINE = True
except Exception:
    log.info("PySide6-WebEngine indisponibil; map va folosi fallback")


# ===========================================================================
# HTML / JS for the Leaflet map
# ===========================================================================
LEAFLET_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Meshtastic Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<style>
  html, body { margin:0; padding:0; height:100%; background:#0F1115; }
  #map { height:100vh; width:100vw; background:#1A1E27; }
  .leaflet-container { background:#1A1E27; }
  .node-pin {
    background:#67EA94; color:#0A1A12; font-weight:700;
    border:2px solid #3FB872; border-radius:50%;
    width:34px; height:34px; line-height:30px;
    text-align:center; font-size:11px; font-family:Segoe UI, sans-serif;
    box-shadow:0 2px 8px rgba(0,0,0,0.4);
  }
  .node-pin.me {
    background:#F5B946; border-color:#C68E1F;
    box-shadow:0 0 0 6px rgba(245,185,70,0.25);
  }
  .leaflet-popup-content-wrapper {
    background:#1A1E27; color:#ECEEF2;
    border:1px solid #333845; border-radius:10px;
  }
  .leaflet-popup-tip { background:#1A1E27; }
  .leaflet-popup-content { margin:10px 14px; line-height:1.5; }
  .popup-title { color:#67EA94; font-weight:700; font-size:13px; }
  .popup-id { color:#5C6573; font-family:Consolas, monospace; font-size:10px; }
  .popup-row { color:#9098A5; font-size:11px; margin-top:4px; }
  .popup-link { color:#5BA9F5; text-decoration:none; }
</style>
</head><body>
<div id="map"></div>
<script>
  const map = L.map('map', { zoomControl: true }).setView([45.9432, 24.9668], 6);

  // OSM standard tile layer
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
  }).addTo(map);

  const markers = {};  // node_id -> marker

  function makeIcon(shortName, isMe) {
    return L.divIcon({
      className: 'node-pin' + (isMe ? ' me' : ''),
      html: shortName || '??',
      iconSize: [34,34], iconAnchor:[17,17]
    });
  }

  function popupHtml(node) {
    const gmaps = `https://www.google.com/maps?q=${node.lat},${node.lon}`;
    const osm = `https://www.openstreetmap.org/?mlat=${node.lat}&mlon=${node.lon}&zoom=15`;
    return `
      <div class="popup-title">${node.name}</div>
      <div class="popup-id">${node.id}</div>
      <div class="popup-row">📍 ${node.lat.toFixed(5)}, ${node.lon.toFixed(5)}</div>
      ${node.alt!=null ? `<div class="popup-row">⛰ Alt: ${node.alt} m</div>` : ''}
      ${node.snr!=null ? `<div class="popup-row">📶 SNR: ${node.snr.toFixed(1)} dB</div>` : ''}
      ${node.bat!=null ? `<div class="popup-row">🔋 ${node.bat}%</div>` : ''}
      <div class="popup-row">
        <a class="popup-link" href="${gmaps}" target="_blank">Google Maps</a> ·
        <a class="popup-link" href="${osm}" target="_blank">OpenStreetMap</a>
      </div>
      <div class="popup-row" style="margin-top:6px;">
        <a class="popup-link" href="#" style="font-weight:700;"
           onclick="window.showNodeDetails('${node.id}'); return false;">
           🔍 Show full details</a>
      </div>
    `;
  }

  // API expus pentru Python
  window.setNodes = function(nodes) {
    // sterge ce nu mai exista
    for (const id in markers) {
      if (!nodes.find(n => n.id === id)) {
        map.removeLayer(markers[id]);
        delete markers[id];
      }
    }
    // adauga / actualizeaza
    nodes.forEach(n => {
      if (markers[n.id]) {
        markers[n.id].setLatLng([n.lat, n.lon]);
        markers[n.id].setIcon(makeIcon(n.short, n.isMe));
        markers[n.id].setPopupContent(popupHtml(n));
      } else {
        const m = L.marker([n.lat, n.lon], { icon: makeIcon(n.short, n.isMe) })
                   .bindPopup(popupHtml(n));
        m.addTo(map);
        markers[n.id] = m;
      }
    });
    if (nodes.length > 0) {
      const group = L.featureGroup(Object.values(markers));
      try { map.fitBounds(group.getBounds().pad(0.2)); } catch (e) {}
    }
  };

  window.recenterToMe = function() {
    const me = Object.values(markers).find(m => m.options.icon.options.className.includes('me'));
    if (me) map.setView(me.getLatLng(), 13);
  };

  // V0.44: bridge to Python so "Show full details" opens the native dialog
  window.showNodeDetails = function(id) { /* replaced once channel ready */ };
  if (typeof QWebChannel !== 'undefined') {
    new QWebChannel(qt.webChannelTransport, function(channel) {
      window.pybridge = channel.objects.pybridge;
      window.showNodeDetails = function(id) {
        if (window.pybridge && window.pybridge.nodeClicked) {
          window.pybridge.nodeClicked(id);
        }
      };
    });
  }
</script>
</body></html>
"""


# ===========================================================================
# MapPage
# ===========================================================================
class _MapBridge(QObject):
    """JS↔Python bridge for the Leaflet map. JS calls pybridge.nodeClicked(id)
    when the user clicks 'Show full details' in a marker popup."""
    def __init__(self, page):
        super().__init__()
        self._page = page

    @Slot(str)
    def nodeClicked(self, node_id: str):
        try:
            self._page.open_node_details(node_id)
        except Exception:
            log.exception("nodeClicked bridge failed")


class MapPage(QWidget):

    def __init__(self, manager: MeshtasticManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.node_positions: Dict[str, dict] = {}   # node_id -> info pt JS
        self.node_data: Dict[str, dict] = {}        # cache pt fallback list

        self._build_ui()
        self._connect_signals()

        # debounce update spre JS
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(400)
        self._update_timer.timeout.connect(self._push_to_map)

    # -----------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header bar
        header = QFrame()
        header.setObjectName("Card")
        header.setStyleSheet(
            f"#Card {{ border-radius: 0; border-left: none; border-right: none; "
            f"border-top: none; }}"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 10, 16, 10)
        self.lbl_title = QLabel()
        self.lbl_title.setProperty("role", "title")
        hl.addWidget(self.lbl_title)
        hl.addStretch(1)
        self.lbl_count = QLabel()
        self.lbl_count.setProperty("role", "muted")
        hl.addWidget(self.lbl_count)
        self.btn_recenter = QPushButton("📍")
        self.btn_recenter.setToolTip("Centreaza pe nodul meu")
        self.btn_recenter.setMaximumWidth(40)
        self.btn_recenter.clicked.connect(self._recenter)
        hl.addWidget(self.btn_recenter)
        root.addWidget(header)

        # WebEngine sau fallback
        if HAS_WEBENGINE:
            self._build_webengine_map(root)
        else:
            self._build_fallback(root)

        self._retranslate()

    def _build_webengine_map(self, root_layout: QVBoxLayout):
        try:
            self.web = QWebEngineView()
            # V0.44: QWebChannel bridge so JS marker clicks open the native
            # NodeDetailsDialog (same popup as Nodes "Show Details").
            try:
                from PySide6.QtWebChannel import QWebChannel
                self._map_bridge = _MapBridge(self)
                self._channel = QWebChannel(self.web.page())
                self._channel.registerObject("pybridge", self._map_bridge)
                self.web.page().setWebChannel(self._channel)
            except Exception:
                log.exception("QWebChannel bridge setup failed")
            self.web.setHtml(LEAFLET_HTML, QUrl("about:blank"))
            self.web.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            root_layout.addWidget(self.web, 1)
        except Exception as e:
            log.warning(f"WebEngine init failed: {e} — falling back to list view")
            global HAS_WEBENGINE
            HAS_WEBENGINE = False
            self._build_fallback(root_layout)

    def open_node_details(self, node_id: str):
        """Open the full NodeDetailsDialog for a node clicked on the map."""
        try:
            node = self.node_data.get(node_id)
            if node is None:
                # fall back to live manager data
                nodes = getattr(self.manager.interface, "nodes", {}) or {}
                node = nodes.get(node_id, {})
            from ..dialogs.node_details_dialog import NodeDetailsDialog
            dlg = NodeDetailsDialog(node_id, node, self.window())
            dlg.exec()
        except Exception:
            log.exception("open_node_details failed")

    def _build_fallback(self, root_layout: QVBoxLayout):
        wrap = QFrame()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(20, 20, 20, 20)
        wl.setSpacing(12)

        warn = QLabel(t("map.no_webengine"))
        warn.setWordWrap(True)
        warn.setStyleSheet(
            f"background-color: {Colors.BG_SURFACE}; border: 1px solid {Colors.BORDER}; "
            f"border-radius: 10px; padding: 14px; color: {Colors.TEXT_PRIMARY};"
            f"font-family: Consolas, monospace; line-height: 1.6;"
        )
        wl.addWidget(warn)

        self.fallback_scroll = QScrollArea()
        self.fallback_scroll.setWidgetResizable(True)
        self.fallback_scroll.setFrameShape(QFrame.NoFrame)
        self.fallback_scroll.setStyleSheet(
            f"QScrollArea {{ background: {Colors.BG_BASE}; border: none; }}"
        )
        inner = QWidget()
        self.fallback_layout = QVBoxLayout(inner)
        self.fallback_layout.setContentsMargins(0, 0, 0, 0)
        self.fallback_layout.setSpacing(8)
        self.fallback_layout.addStretch(1)
        self.fallback_scroll.setWidget(inner)
        wl.addWidget(self.fallback_scroll, 1)
        root_layout.addWidget(wrap, 1)

    # -----------------------------------------------------------------
    def _connect_signals(self):
        self.manager.nodeUpdated.connect(self._on_node_updated)
        self.manager.stateChanged.connect(self._on_state)
        i18n.languageChanged.connect(self._retranslate)

    def _on_state(self, state: str):
        if state == "idle":
            self.node_positions.clear()
            self.node_data.clear()
            self._update_timer.start()

    def _on_node_updated(self, node_id: str, node: dict):
        self.node_data[node_id] = node
        pos = node.get("position") or {}
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        if lat is None and pos.get("latitudeI") is not None:
            lat = pos["latitudeI"] / 1e7
            lon = pos.get("longitudeI", 0) / 1e7
        if lat is None or lon is None:
            return

        user = node.get("user") or {}
        dm = node.get("deviceMetrics") or {}
        is_me = (node_id == self.manager.my_node_id)
        self.node_positions[node_id] = {
            "id":    node_id,
            "name":  user.get("longName") or user.get("shortName") or node_id,
            "short": user.get("shortName") or "??",
            "lat":   lat,
            "lon":   lon,
            "alt":   pos.get("altitude"),
            "snr":   node.get("snr"),
            "bat":   dm.get("batteryLevel"),
            "isMe":  is_me,
        }
        self._update_timer.start()

    # -----------------------------------------------------------------
    def _push_to_map(self):
        nodes = list(self.node_positions.values())
        self.lbl_count.setText(t("nodes.count_many", len(nodes)) if len(nodes) != 1 else t("nodes.count_one"))

        if HAS_WEBENGINE and hasattr(self, "web"):
            js_data = json.dumps(nodes)
            self.web.page().runJavaScript(f"if(window.setNodes) window.setNodes({js_data});")
        else:
            self._refresh_fallback()

    def _refresh_fallback(self):
        if not hasattr(self, "fallback_layout"):
            return
        # clear all
        while self.fallback_layout.count() > 1:
            child = self.fallback_layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        for n in self.node_positions.values():
            card = QFrame()
            card.setObjectName("Card")
            cl = QHBoxLayout(card)
            cl.setContentsMargins(14, 10, 14, 10)
            text = QLabel(
                f"<b style='color:{Colors.PRIMARY}'>{n['name']}</b>  "
                f"<span style='color:{Colors.TEXT_DIM};font-family:Consolas'>{n['id']}</span><br>"
                f"<span style='color:{Colors.TEXT_SECONDARY};font-size:11px'>"
                f"📍 {n['lat']:.5f}, {n['lon']:.5f}</span>"
            )
            text.setTextFormat(Qt.RichText)
            cl.addWidget(text, 1)
            btn_g = QPushButton("Google Maps")
            btn_g.clicked.connect(lambda _, lat=n['lat'], lon=n['lon']:
                QDesktopServices.openUrl(QUrl(f"https://www.google.com/maps?q={lat},{lon}")))
            cl.addWidget(btn_g)
            btn_o = QPushButton("OpenStreetMap")
            btn_o.clicked.connect(lambda _, lat=n['lat'], lon=n['lon']:
                QDesktopServices.openUrl(QUrl(
                    f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15")))
            cl.addWidget(btn_o)
            self.fallback_layout.insertWidget(self.fallback_layout.count() - 1, card)

    def _recenter(self):
        if HAS_WEBENGINE and hasattr(self, "web"):
            self.web.page().runJavaScript("if(window.recenterToMe) window.recenterToMe();")

    # -----------------------------------------------------------------
    def _retranslate(self, *_):
        self.lbl_title.setText(t("map.title"))
        self.lbl_count.setText(t("nodes.count_many", len(self.node_positions))
                               if len(self.node_positions) != 1 else t("nodes.count_one"))
