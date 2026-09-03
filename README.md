# Spin EV Charger for Home Assistant

[![HACS: custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Release](https://img.shields.io/github/v/release/Dr-Blank/spinev-ha?display_name=tag)](https://github.com/Dr-Blank/spinev-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Control an Exicom Spin EV charger over Bluetooth LE, locally, with no vendor
cloud and no account.

The charger is reached through any Bluetooth adapter or ESPHome Bluetooth
proxy that Home Assistant already knows about, so the charger does not have to
be near the Home Assistant host.

## Supported devices

Exicom Spin wall chargers that advertise over Bluetooth LE, including the
single phase Spin Air. Three phase units report the same registers.

## Entities

| Entity | Notes |
| --- | --- |
| State | Available, Idle, Starting, Charging, Paused by charger, Paused by vehicle, Finishing, Fault, Starting up or Unavailable |
| Charging (binary sensor) | On while power is flowing or about to |
| Charging (switch) | Start and stop charging. On for the whole session, including while it is paused |
| Vehicle connected | On while a vehicle is plugged in |
| Session suspended | On while a session is open but paused, by either end. Diagnostic |
| Problem | On while the charger reports an alarm, with the alarm names as an attribute |
| Power | Active power, in watts |
| Current | Output current, in amps |
| Voltage | Line voltage, disabled by default |
| Current limit | The configured charging limit, adjustable |
| Timezone offset hours / minutes | The charger's UTC offset, adjustable |
| Start delay | Delay before charging starts, 0 to 1800s, adjustable |
| Apply config | Button that sends the config values that were changed |
| Sync clock | Button that sets the charger's clock to the current time |
| Restart | Button that restarts the charger, which clears a fault without cutting its power |
| Refresh | Button that re-reads the charger now, discarding unapplied config edits. Diagnostic |
| Load balancing | On while the charger shares its supply with the installation. Diagnostic |
| Grid current limit | What the grid supply can deliver, in amps. Diagnostic |
| Grid current headroom | Margin kept below the grid current limit. Diagnostic |
| Current reduction step | How much charging current is cut when the grid limit is neared. Diagnostic |
| Maximum grid power | Ceiling on total grid power for the installation. Diagnostic |
| Load balancing source / priority | Raw setting values, disabled by default |
| Session energy | Energy delivered in the current session |
| Session time | Duration of the current session |
| Lifetime energy | Total energy delivered |
| Lifetime charging time | Total charging time, diagnostic |

### Changing configuration

The config numbers are a draft. Nothing reaches the charger until **Apply
config** is pressed, and only the values that actually changed are sent.
**Refresh** re-reads the charger and throws the draft away.

Applying a timezone or start delay change **restarts the charger**, which ends
any session in progress; the charger is left alone for 45 seconds afterwards
and then re-read. A current limit on its own is not committed, so it takes
effect without a restart — but the charger refuses a current limit change
during a session, the same as its own app does, so stop charging first.

## Installation

### HACS (recommended)

This is a custom repository, so HACS has to be told about it once. After that
it updates like any other HACS integration.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Dr-Blank&repository=spinev-ha&category=integration)

Click the badge above, then **Download**. It fills the repository in for you.

If the badge does not work, add it by hand:

1. **HACS > ⋮ (top right) > Custom repositories**.
2. Repository `https://github.com/Dr-Blank/spinev-ha`, type **Integration**,
   then **Add**.
3. Search HACS for **Spin EV Charger** and **Download** it.

Either way, **restart Home Assistant** afterwards — custom integrations are
only loaded at startup.

### Manual

Copy `custom_components/spinev` into your Home Assistant `config/custom_components/`
directory and restart Home Assistant.

### Setup

The charger is picked up by Bluetooth discovery and appears under
**Settings > Devices & services**. If it does not, add it with
**Add integration > Spin EV Charger**.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=spinev)

Nothing else is needed: no account and no API key.

### Updating

HACS shows an update when a new release is tagged. Download it and restart
Home Assistant.

## Configuration

The charger accepts one Bluetooth client at a time. Home Assistant and the
phone app cannot both be connected, so **Configure** on the integration offers
two ways to hold the link:

- **Reconnect each poll** (default) frees the charger between polls, so the
  phone app can be used in the gaps. Each poll costs about a second more, and
  more reconnects means more transient Bluetooth failures.
- **Stay connected** keeps the link open. Polls are faster and fail less, but
  the phone app cannot connect at all while the integration is enabled.

Also configurable: the poll interval, separately for while a vehicle is
charging (default 60s) and while idle (default 300s). The idle interval should
stay at least as long as the charging interval — it exists to give the phone
app long uncontested stretches when nothing needs watching closely. Each poll
reads about a dozen registers in sequence and takes roughly a second.

Changing any option reloads the integration.

## Removal

Delete the integration from **Settings > Devices & services**. Disabling,
deleting or reloading it disconnects from the charger and hands it back to the
phone app. A Home Assistant crash or a hard power cut does not, in which case
the link is released when the charger or the Bluetooth proxy times it out.

## Known limitations

- Only the first alarm bank is decoded.
- Charging session history stored on the charger is not exposed.
- Charger states above Charging exist but have no confirmed meaning, and are
  reported as unknown.

## Troubleshooting

**The charger is never discovered.** Discovery needs a connectable adapter or
proxy in range. Check under **Settings > Devices & services > Bluetooth** that
the charger's address is being seen.

**Setup fails with "Failed to connect".** Something else holds the charger.
Close the phone app fully and retry.

**Entities go unavailable during charging.** The link is being dropped, most
often because of range or because the phone app took it. Move a Bluetooth
proxy closer, or switch the connection mode to **Stay connected**.

## Built on

[`spinev-ble`](https://github.com/Dr-Blank/spinev-ble), the Python library
that speaks the charger's protocol.
