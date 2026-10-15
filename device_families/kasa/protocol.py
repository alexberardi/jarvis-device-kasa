"""TP-Link Kasa/Tapo device protocol adapter."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from jarvis_command_sdk import (
    IJarvisDeviceProtocol,
    DiscoveredDevice,
    DeviceControlResult,
    IJarvisButton,
)

try:
    from jarvis_log_client import JarvisLogger
except ImportError:
    import logging

    class JarvisLogger:
        def __init__(self, **kw: Any) -> None:
            self._log = logging.getLogger(kw.get("service", __name__))

        def info(self, msg: str, **kw: Any) -> None:
            self._log.info(msg)

        def warning(self, msg: str, **kw: Any) -> None:
            self._log.warning(msg)

        def error(self, msg: str, **kw: Any) -> None:
            self._log.error(msg)

        def debug(self, msg: str, **kw: Any) -> None:
            self._log.debug(msg)


logger = JarvisLogger(service="device.kasa")

_KASA_TYPE_TO_DOMAIN: dict[str, str] = {
    "plug": "switch",
    "bulb": "light",
    "strip": "switch",
    "dimmer": "light",
    "lightstrip": "light",
    "wallswitch": "switch",
    "fan": "fan",
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _entity_id(dev: Any, ip: str) -> str:
    """Stable id for a device: slug of its alias, else of its MAC, else its IP."""
    alias: str = getattr(dev, "alias", "") or ""
    mac: str = getattr(dev, "mac", "") or ""
    return _slugify(alias) if alias else (_slugify(mac) if mac else ip)


class KasaProtocol(IJarvisDeviceProtocol):
    """TP-Link Kasa/Tapo LAN protocol adapter."""

    protocol_name: str = "kasa"
    friendly_name: str = "TP-Link Kasa"
    supported_domains: list[str] = ["light", "switch", "fan"]
    connection_type: str = "lan"

    @property
    def supported_actions(self) -> list[IJarvisButton]:
        return [
            IJarvisButton("Turn On", "turn_on", "primary", "power-plug"),
            IJarvisButton("Turn Off", "turn_off", "secondary", "power-plug-off"),
            IJarvisButton("Toggle", "toggle", "secondary", "toggle-switch"),
        ]

    async def discover(self, timeout: float = 5.0) -> list[DiscoveredDevice]:
        try:
            from kasa import Discover
        except ImportError:
            logger.error("python-kasa is not installed. Run: pip install python-kasa")
            return []

        devices: list[DiscoveredDevice] = []
        try:
            found = await Discover.discover(timeout=timeout)
        except Exception as e:
            logger.error(f"Kasa discovery failed: {e}")
            return []

        for ip, dev in found.items():
            try:
                await dev.update()
            except Exception as e:
                logger.warning(f"Failed to update Kasa device at {ip}: {e}")
                continue

            alias: str = getattr(dev, "alias", "") or ""
            mac: str = getattr(dev, "mac", "") or ""
            model: str = getattr(dev, "model", "") or ""
            device_type_raw: str = str(getattr(dev, "device_type", "")).lower()

            domain: str = "switch"
            for key, dom in _KASA_TYPE_TO_DOMAIN.items():
                if key in device_type_raw:
                    domain = dom
                    break

            devices.append(
                DiscoveredDevice(
                    name=alias or model or "Kasa Device",
                    domain=domain,
                    manufacturer="TP-Link",
                    model=model,
                    protocol=self.protocol_name,
                    entity_id=_entity_id(dev, ip),
                    local_ip=ip,
                    mac_address=mac or None,
                )
            )

        logger.info(f"Kasa discovery found {len(devices)} device(s)")
        return devices

    async def control(
        self,
        ip: str,
        action: str,
        data: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> DeviceControlResult:
        def fail(error: str, entity_id: str = ip) -> DeviceControlResult:
            return DeviceControlResult(
                success=False, entity_id=entity_id, action=action, error=error
            )

        try:
            from kasa import Discover
        except ImportError:
            return fail("python-kasa is not installed. Run: pip install python-kasa")

        data = data or {}
        if not ip:
            return fail("No IP address for device")

        try:
            dev = await Discover.discover_single(ip)
            await dev.update()
        except Exception as e:
            return fail(f"Failed to connect to {ip}: {e}")

        entity_id: str = _entity_id(dev, ip)
        name: str = getattr(dev, "alias", "") or ip
        ok = DeviceControlResult(success=True, entity_id=entity_id, action=action)

        try:
            if action == "turn_on":
                await dev.turn_on()
                await dev.update()
                return ok

            elif action == "turn_off":
                await dev.turn_off()
                await dev.update()
                return ok

            elif action == "toggle":
                if dev.is_on:
                    await dev.turn_off()
                else:
                    await dev.turn_on()
                await dev.update()
                return ok

            elif action == "set_brightness":
                brightness: int = int(data.get("brightness", 100))
                brightness = max(0, min(100, brightness))
                if hasattr(dev, "set_brightness"):
                    await dev.set_brightness(brightness)
                    await dev.update()
                    return ok
                return fail(f"{name} does not support brightness", entity_id)

            else:
                return fail(f"Unsupported action: {action}", entity_id)

        except Exception as e:
            return fail(f"Control failed: {e}", entity_id)

    async def get_state(self, ip: str, **kwargs: Any) -> dict[str, Any] | None:
        try:
            from kasa import Discover
        except ImportError:
            return {"error": "python-kasa is not installed"}

        if not ip:
            return {"error": "No IP address for device"}

        try:
            dev = await Discover.discover_single(ip)
            await dev.update()
        except Exception as e:
            return {"error": f"Failed to connect to {ip}: {e}"}

        state: dict[str, Any] = {
            "state": "on" if dev.is_on else "off",
        }

        if hasattr(dev, "brightness") and dev.brightness is not None:
            state["brightness"] = dev.brightness

        return state
