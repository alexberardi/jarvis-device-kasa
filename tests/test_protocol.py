"""Tests for KasaProtocol against the jarvis-command-sdk device protocol interface.

python-kasa is replaced by a fake ``kasa`` module so the tests need no network
and no real devices.
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest
from jarvis_command_sdk import DeviceControlResult, DiscoveredDevice, IJarvisButton

from device_families.kasa.protocol import KasaProtocol


class FakeDevice:
    def __init__(
        self,
        alias: str = "Living Room Lamp",
        mac: str = "AA:BB:CC:DD:EE:FF",
        model: str = "KL130",
        device_type: str = "DeviceType.Bulb",
        is_on: bool = False,
        brightness: int | None = 40,
    ) -> None:
        self.alias = alias
        self.mac = mac
        self.model = model
        self.device_type = device_type
        self.is_on = is_on
        if brightness is not None:
            self.brightness = brightness
        self.calls: list[Any] = []

    async def update(self) -> None:
        self.calls.append("update")

    async def turn_on(self) -> None:
        self.calls.append("turn_on")
        self.is_on = True

    async def turn_off(self) -> None:
        self.calls.append("turn_off")
        self.is_on = False

    async def set_brightness(self, value: int) -> None:
        self.calls.append(("set_brightness", value))
        self.brightness = value


class FakePlug(FakeDevice):
    """A plug: no brightness support."""

    def __init__(self, **kw: Any) -> None:
        kw.setdefault("alias", "Coffee Maker")
        kw.setdefault("model", "HS103")
        kw.setdefault("device_type", "DeviceType.Plug")
        super().__init__(brightness=None, **kw)

    def __getattribute__(self, name: str) -> Any:
        # Plugs have no set_brightness, so hasattr() must report False.
        if name == "set_brightness":
            raise AttributeError(name)
        return super().__getattribute__(name)


@pytest.fixture
def fake_kasa(monkeypatch: pytest.MonkeyPatch) -> dict[str, FakeDevice]:
    """Install a fake ``kasa`` module; returns the ip -> device map it serves."""
    devices: dict[str, FakeDevice] = {}

    class Discover:
        @staticmethod
        async def discover(timeout: float = 5) -> dict[str, FakeDevice]:
            return dict(devices)

        @staticmethod
        async def discover_single(host: str) -> FakeDevice:
            if host not in devices:
                raise OSError(f"no device at {host}")
            return devices[host]

    module = types.ModuleType("kasa")
    module.Discover = Discover  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "kasa", module)
    return devices


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_instantiates_and_builds_supported_actions() -> None:
    protocol = KasaProtocol()
    actions = protocol.supported_actions
    assert actions and all(isinstance(a, IJarvisButton) for a in actions)
    assert [a.button_action for a in actions] == ["turn_on", "turn_off", "toggle"]
    for a in actions:
        assert a.button_type in ("primary", "secondary", "destructive")
        assert a.to_dict()["button_text"]


def test_discover_builds_devices(fake_kasa: dict[str, FakeDevice]) -> None:
    fake_kasa["192.168.1.10"] = FakeDevice()
    fake_kasa["192.168.1.11"] = FakePlug()

    found = run(KasaProtocol().discover(timeout=1))

    assert all(isinstance(d, DiscoveredDevice) for d in found)
    by_ip = {d.local_ip: d for d in found}
    bulb = by_ip["192.168.1.10"]
    assert bulb.entity_id == "living_room_lamp"
    assert bulb.name == "Living Room Lamp"
    assert bulb.domain == "light"
    assert bulb.protocol == "kasa"
    assert bulb.manufacturer == "TP-Link"
    assert bulb.model == "KL130"
    assert bulb.mac_address == "AA:BB:CC:DD:EE:FF"
    plug = by_ip["192.168.1.11"]
    assert plug.entity_id == "coffee_maker"
    assert plug.domain == "switch"


def test_discover_without_alias_uses_mac_slug(fake_kasa: dict[str, FakeDevice]) -> None:
    fake_kasa["192.168.1.12"] = FakeDevice(alias="")
    (device,) = run(KasaProtocol().discover())
    assert device.entity_id == "aa_bb_cc_dd_ee_ff"


def test_control_turn_on_and_off(fake_kasa: dict[str, FakeDevice]) -> None:
    dev = fake_kasa["192.168.1.10"] = FakeDevice(is_on=False)
    protocol = KasaProtocol()

    result = run(protocol.control("192.168.1.10", "turn_on"))
    assert isinstance(result, DeviceControlResult)
    assert result.success and result.error is None
    assert result.action == "turn_on"
    assert result.entity_id == "living_room_lamp"
    assert dev.is_on

    result = run(protocol.control("192.168.1.10", "turn_off"))
    assert result.success and not dev.is_on


def test_control_toggle(fake_kasa: dict[str, FakeDevice]) -> None:
    dev = fake_kasa["192.168.1.10"] = FakeDevice(is_on=True)
    result = run(KasaProtocol().control("192.168.1.10", "toggle"))
    assert result.success and result.action == "toggle"
    assert not dev.is_on


def test_control_set_brightness_clamps(fake_kasa: dict[str, FakeDevice]) -> None:
    dev = fake_kasa["192.168.1.10"] = FakeDevice()
    result = run(KasaProtocol().control("192.168.1.10", "set_brightness", {"brightness": 150}))
    assert result.success
    assert ("set_brightness", 100) in dev.calls


def test_control_set_brightness_unsupported(fake_kasa: dict[str, FakeDevice]) -> None:
    fake_kasa["192.168.1.11"] = FakePlug()
    result = run(KasaProtocol().control("192.168.1.11", "set_brightness", {"brightness": 50}))
    assert not result.success
    assert result.error and "brightness" in result.error


def test_control_unknown_action(fake_kasa: dict[str, FakeDevice]) -> None:
    fake_kasa["192.168.1.10"] = FakeDevice()
    result = run(KasaProtocol().control("192.168.1.10", "explode"))
    assert not result.success
    assert result.action == "explode"
    assert result.error and "explode" in result.error


def test_control_unreachable_device(fake_kasa: dict[str, FakeDevice]) -> None:
    result = run(KasaProtocol().control("192.168.1.99", "turn_on"))
    assert not result.success
    assert result.entity_id == "192.168.1.99"
    assert result.error and "192.168.1.99" in result.error


def test_get_state(fake_kasa: dict[str, FakeDevice]) -> None:
    fake_kasa["192.168.1.10"] = FakeDevice(is_on=True, brightness=40)
    fake_kasa["192.168.1.11"] = FakePlug(is_on=False)
    protocol = KasaProtocol()

    assert run(protocol.get_state("192.168.1.10")) == {"state": "on", "brightness": 40}
    assert run(protocol.get_state("192.168.1.11")) == {"state": "off"}


def test_get_state_unreachable(fake_kasa: dict[str, FakeDevice]) -> None:
    state = run(KasaProtocol().get_state("192.168.1.99"))
    assert state is not None and "error" in state
