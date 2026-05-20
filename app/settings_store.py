"""
Wrapper QSettings - persistenta intre sesiuni.

Pe Windows foloseste registry (HKCU\\Software\\Meshtastic Community\\MeshLink Desktop)
Pe Linux: ~/.config/Meshtastic Community/MeshLink Desktop.conf
Pe macOS: ~/Library/Preferences/com.meshtastic-community.Meshtastic-Desktop.plist
"""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QSettings


class Settings:
    """Singleton for application settings."""

    _instance: Optional["Settings"] = None

    def __init__(self):
        self._qs = QSettings("Meshtastic Community", "MeshLink Desktop")

    @classmethod
    def get(cls) -> "Settings":
        if cls._instance is None:
            cls._instance = Settings()
        return cls._instance

    # Generic ---------------------------------------------------------------
    def value(self, key: str, default: Any = None, type_=None) -> Any:
        if type_ is not None:
            v = self._qs.value(key, default, type=type_)
        else:
            v = self._qs.value(key, default)
        return v

    def set(self, key: str, val: Any):
        self._qs.setValue(key, val)
        self._qs.sync()

    # Convenience -----------------------------------------------------------
    @property
    def language(self) -> str:
        return self.value("ui/language", "en") or "en"
    @language.setter
    def language(self, v: str): self.set("ui/language", v)

    @property
    def theme(self) -> str:
        """'dark' or 'light' — default dark."""
        v = self.value("ui/theme", "dark") or "dark"
        return v if v in ("dark", "light") else "dark"
    @theme.setter
    def theme(self, v: str):
        self.set("ui/theme", v if v in ("dark", "light") else "dark")

    def save(self):
        """Explicit sync (most setters already auto-sync via .set())."""
        self._qs.sync()

    @property
    def auto_reconnect(self) -> bool:
        return self.value("conn/auto_reconnect", True, type_=bool)
    @auto_reconnect.setter
    def auto_reconnect(self, v: bool): self.set("conn/auto_reconnect", bool(v))

    @property
    def notifications(self) -> bool:
        return self.value("ui/notifications", True, type_=bool)
    @notifications.setter
    def notifications(self, v: bool): self.set("ui/notifications", bool(v))

    @property
    def sound_enabled(self) -> bool:
        return self.value("ui/sound_enabled", True, type_=bool)
    @sound_enabled.setter
    def sound_enabled(self, v: bool): self.set("ui/sound_enabled", bool(v))

    @property
    def save_history(self) -> bool:
        return self.value("db/save_history", True, type_=bool)
    @save_history.setter
    def save_history(self, v: bool): self.set("db/save_history", bool(v))

    @property
    def last_conn_type(self) -> str:
        return self.value("conn/last_type", "serial") or "serial"
    @last_conn_type.setter
    def last_conn_type(self, v: str): self.set("conn/last_type", v)

    @property
    def last_serial_port(self) -> str:
        return self.value("conn/last_serial", "") or ""
    @last_serial_port.setter
    def last_serial_port(self, v: str): self.set("conn/last_serial", v)

    @property
    def last_wifi_host(self) -> str:
        return self.value("conn/last_wifi_host", "meshtastic.local") or "meshtastic.local"
    @last_wifi_host.setter
    def last_wifi_host(self, v: str): self.set("conn/last_wifi_host", v)

    @property
    def last_wifi_port(self) -> int:
        try:
            return int(self.value("conn/last_wifi_port", 4403) or 4403)
        except Exception:
            return 4403
    @last_wifi_port.setter
    def last_wifi_port(self, v: int): self.set("conn/last_wifi_port", int(v))

    @property
    def last_ble_address(self) -> str:
        return self.value("conn/last_ble", "") or ""
    @last_ble_address.setter
    def last_ble_address(self, v: str): self.set("conn/last_ble", v)

    @property
    def window_geometry(self) -> bytes:
        return self.value("ui/window_geometry", b"") or b""
    @window_geometry.setter
    def window_geometry(self, v: bytes): self.set("ui/window_geometry", v)
