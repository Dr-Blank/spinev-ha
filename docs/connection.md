# Setup can't find or reach the charger

Adding the integration ends with **No Spin EV charger was found** (older wording: *No devices found on the network*), or setup fails with **Failed to connect**. Both mean the Bluetooth side did not work out. Three things have to be true at the same time.

## 1. The charger is powered on

The charger only advertises over Bluetooth LE while it has mains power. A unit on a switched circuit, or one that has tripped its breaker, is completely invisible to Home Assistant. After powering it up, give it 30–60 seconds to start advertising before you retry.

## 2. Nothing else is talking to it

The charger accepts **one Bluetooth client at a time**. While the Exicom / Spin phone app is connected, or another Home Assistant instance holds the link, setup here cannot get in.

- Close the phone app fully. Backgrounding it is usually not enough — swipe it away, or turn the phone's Bluetooth off, so it actually drops the link.
- If you just disconnected the app, wait about 30 seconds for the charger to time the old connection out before retrying.
- Only one Home Assistant install should have the integration configured for a given charger.

## 3. Home Assistant has Bluetooth in range of the charger

Home Assistant needs a **connectable** Bluetooth interface within radio range of the charger — a few metres, one wall at most. That is either:

- a Bluetooth adapter on the Home Assistant host (a built-in radio or a USB dongle), or
- an **ESPHome Bluetooth proxy**: an ESP32 board running the [Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy.html) component, adopted into Home Assistant, and mounted near the charger. Ready-made firmware is at <https://esphome.io/projects/> under *Bluetooth Proxy*.

A proxy is the usual answer here, because the charger is outside or in a garage and the Home Assistant host is not. One ESP32 sitting near the charger is enough; Home Assistant reaches the charger through it automatically once it is adopted.

To check what Home Assistant can see, open **Settings → Devices & services → Bluetooth**, use the **⋮** menu → **Advertisement monitor**, and look for the charger. Its advertised name is a leading space, a 12‑digit serial, an underscore and four hex characters, for example ` 000000000000_1a2b`. If that name never appears, the problem is range, the adapter or the proxy — not this integration. If it appears but setup still fails, work through step 2 again.

## Still stuck

- The service UUID the charger uses (`49535343-…`) is a generic serial‑over‑BLE tunnel that many unrelated devices also advertise. The 12‑digit‑serial name above is what tells a charger apart, so confirm you are looking at that.
- Open an issue with a [diagnostics download](https://www.home-assistant.io/docs/configuration/troubleshooting/#download-diagnostics) from the Bluetooth integration and, if you have one, the ESPHome proxy logs.
