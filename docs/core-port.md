# Porting to Home Assistant core

The integration is written to core standards, so a port is mostly a file copy.
This is what still has to change, and how to split it across pull requests.

## Manifest deltas

`manifest.json` is HACS-shaped here and core-shaped there. When copying:

| Key | Custom component | Core |
| --- | --- | --- |
| `version` | `"0.2.0"` — required by HACS | **remove**, hassfest rejects it |
| `issue_tracker` | this repository | **remove**, core uses its own |
| `documentation` | this repository | `https://www.home-assistant.io/integrations/spinev` |
| `requirements` | `spinev-ble[bleak]==0.2.0` | same, but core already pins `bleak`, so the extra resolves to a no-op and reviewers may ask to drop it |

Nothing else in the manifest changes.

## Files that do not travel

- `translations/en.json` — core builds it from `strings.json` at release time,
  and `[%key:...%]` references are resolved there. `script/generate_translations.py`
  exists only because a custom component has no such build step.
- `script/`, `hacs.json`, `pyproject.toml`, `.github/` — repository plumbing.

Tests move from `tests/` to `tests/components/spinev/`, and the imports change
from `custom_components.spinev` to `homeassistant.components.spinev` and from
`pytest_homeassistant_custom_component` to `tests.common`. The
`auto_enable_custom_integrations` fixture in `conftest.py` is dropped.

## Companion pull requests

A new integration needs three, cross-linked:

1. `home-assistant/core` — the integration itself
2. `home-assistant/brands` — logo and icon for the `spinev` domain
3. `home-assistant/home-assistant.io` — the documentation page

The `brands` rule in `quality_scale.yaml` stays `todo` until the brands pull
request merges.

## Suggested pull request split

Reviewers prefer small pull requests, and a new integration is reviewed
fastest when the first one has no contentious surface.

**PR 1 — read only.** `manifest.json`, `__init__.py`, `const.py`,
`coordinator.py`, `entity.py`, `sensor.py`, `config_flow.py`, `strings.json`,
`quality_scale.yaml`, `icons.json`, and `test_config_flow.py` (100% coverage is
a hard gate), `test_init.py`, `test_sensor.py`. Trim `SENSORS` to `state`,
`power`, `current`, `session_energy` and `lifetime_energy`; leave the rest and
the whole of `LOAD_BALANCING_SENSORS` for PR 2. Drop the options flow from this
one as well, so the first review is purely about setup and reading.

**PR 2** — the remaining sensors, `binary_sensor.py`, `diagnostics.py`.

**PR 3** — `switch.py`, the write path on the coordinator, and the connection
mode options flow.

**PR 4** — `number.py`, `button.py`.

## Known review points

- **The Bluetooth matcher is a service UUID only.** `49535343-fe7d-4ae5-8fa9-9fafd205e455`
  is the generic Microchip/ISSC transparent UART service, shared with many
  unrelated devices. A `local_name` matcher cannot narrow it: core forbids
  wildcards in the first three characters of a `local_name` pattern
  (`homeassistant/components/bluetooth/match.py`), and the advertised name is
  twelve arbitrary digits followed by `_XXXX`. `async_step_bluetooth` aborts
  with `not_supported` on a name mismatch, so no flow is ever shown for another
  vendor's device. `iron_os` and `iseo_argo_ble` set the same precedent. Say
  this in the pull request description before a reviewer has to ask.

  If Exicom serials turn out to share a fixed prefix, replace it with a
  combined `service_uuid` + `local_name` matcher and this point goes away.

- **The connection mode option is not a polling interval.** Core rejects
  user-configurable scan intervals; this option chooses whether Home Assistant
  holds the charger's single Bluetooth slot permanently. Holding it locks
  everyone else out, which some owners want, and frees the phone app when it is
  not held. The poll interval itself is fixed and adapts to the session.

- **The config numbers debounce their writes.** `homeassistant.helpers.debounce.Debouncer`
  holds a value for three seconds so a dragged slider costs one Bluetooth write
  rather than one per step. `flux_led`'s `FluxConfigNumber` is the same pattern
  on the same helper, and `qbus` debounces state requests for the same reason.
  The cost is that the write leaves after the action has returned, so a failure
  is logged rather than raised; the entity drops the value it was showing so
  the failure stays visible. Note this next to the `action-exceptions` rule.

- **The charger's timezone register cannot express a negative UTC offset.** It
  is an unsigned `HH MM` pair, so `async_set_timezone` refuses anything west of
  UTC. `Sync clock` therefore writes only the clock, using Home Assistant's
  configured time zone. Fixing this belongs in `spinev-ble`, not here.
