# jarvis-device-kasa

TP-Link Kasa/Tapo smart device protocol adapter for [Jarvis](https://github.com/alexberardi/jarvis-node-setup).

## Install

```bash
python scripts/command_store.py install --url https://github.com/alexberardi/jarvis-device-kasa
```

## Supported Devices

- Smart plugs
- Smart bulbs
- Smart switches
- Smart dimmers
- Smart light strips
- Smart fans

## Secrets

No secrets required — works over LAN.

## Structure

```
device_families/kasa/protocol.py   # Device protocol adapter
```
