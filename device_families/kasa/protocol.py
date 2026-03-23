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


class KasaProtocol(IJarvisDeviceProtocol):
    """TP-Link Kasa/Tapo LAN protocol adapter."""

    protocol_name: str = "kasa"
    friendly_name: str = "TP-Link Kasa"
    supported_domains: list[str] = ["light", "switch", "fan"]
    connection_type: str = "lan"

    @property
    def supported_actions(self) -> list[IJarvisButton]:
        return [
            IJarvisButton(
                action="turn_on",
                label="Turn On",
                icon="power-plug",
            ),
            IJarvisButton(
                action="turn_off",
                label="Turn Off",
                icon="power-plug-off",
            ),
            IJarvisButton(
                action="toggle",
                label="Toggle",
                icon="toggle-switch",
            ),
        ]

    async def discover_devices(self, timeout: int = 5) -> list[DiscoveredDevice]:
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

            device_id: str = _slugify(alias) if alias else _slugify(mac)

            devices.append(
                DiscoveredDevice(
                    id=device_id,
                    name=alias or model or "Kasa Device",
                    domain=domain,
                    protocol=self.protocol_name,
                    ip=ip,
                    mac=mac,
                    model=model,
                    manufacturer="TP-Link",
                )
            )

        logger.info(f"Kasa discovery found {len(devices)} device(s)")
        return devices

    async def control_device(
        self, device: DiscoveredDevice, action: str, params: dict[str, Any] | None = None
    ) -> DeviceControlResult:
        try:
            from kasa import Discover
        except ImportError:
            return DeviceControlResult(
                success=False,
                message="python-kasa is not installed. Run: pip install python-kasa",
            )

        params = params or {}
        ip: str = device.ip or ""
        if not ip:
            return DeviceControlResult(success=False, message="No IP address for device")

        try:
            dev = await Discover.discover_single(ip)
            await dev.update()
        except Exception as e:
            return DeviceControlResult(success=False, message=f"Failed to connect to {ip}: {e}")

        try:
            if action == "turn_on":
                await dev.turn_on()
                await dev.update()
                return DeviceControlResult(success=True, message=f"{device.name} turned on")

            elif action == "turn_off":
                await dev.turn_off()
                await dev.update()
                return DeviceControlResult(success=True, message=f"{device.name} turned off")

            elif action == "toggle":
                if dev.is_on:
                    await dev.turn_off()
                    new_state = "off"
                else:
                    await dev.turn_on()
                    new_state = "on"
                await dev.update()
                return DeviceControlResult(success=True, message=f"{device.name} toggled {new_state}")

            elif action == "set_brightness":
                brightness: int = int(params.get("brightness", 100))
                brightness = max(0, min(100, brightness))
                if hasattr(dev, "set_brightness"):
                    await dev.set_brightness(brightness)
                    await dev.update()
                    return DeviceControlResult(
                        success=True, message=f"{device.name} brightness set to {brightness}%"
                    )
                return DeviceControlResult(
                    success=False, message=f"{device.name} does not support brightness"
                )

            else:
                return DeviceControlResult(success=False, message=f"Unsupported action: {action}")

        except Exception as e:
            return DeviceControlResult(success=False, message=f"Control failed: {e}")

    async def get_state(self, device: DiscoveredDevice) -> dict[str, Any]:
        try:
            from kasa import Discover
        except ImportError:
            return {"error": "python-kasa is not installed"}

        ip: str = device.ip or ""
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
