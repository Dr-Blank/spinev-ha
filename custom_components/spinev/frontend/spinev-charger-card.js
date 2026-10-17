/**
 * Spin EV Charger card.
 *
 * Combines a charger's entities into one card: state, power, a scene of the
 * charger and the car that follows the session, start/stop, the current limit
 * and the session figures. Entities are found through the device, so the only
 * required configuration is which charger to show.
 *
 * Plain custom element with no build step and no dependency on Home
 * Assistant's internal ha-* elements, which are not a stable API.
 */

const CARD_TYPE = "spinev-charger-card";
const INTEGRATION = "spinev";

/**
 * How each role is found among the device's entities. A role names either the
 * entity's translation key or, for entities named by their device class, the
 * device class of an entity that has no translation key.
 */
const ROLES = {
  status: { domain: "sensor", key: "state" },
  charging: { domain: "binary_sensor", key: "charging" },
  session: { domain: "switch", key: "charging" },
  vehicle: { domain: "binary_sensor", key: "vehicle_connected" },
  problem: { domain: "binary_sensor", deviceClass: "problem" },
  power: { domain: "sensor", deviceClass: "power" },
  current: { domain: "sensor", deviceClass: "current" },
  voltage: { domain: "sensor", deviceClass: "voltage" },
  sessionEnergy: { domain: "sensor", key: "session_energy" },
  sessionDuration: { domain: "sensor", key: "session_duration" },
  lifetimeEnergy: { domain: "sensor", key: "lifetime_energy" },
  currentLimit: { domain: "number", key: "current_limit" },
  startDelay: { domain: "number", key: "random_delay" },
  restart: { domain: "button", deviceClass: "restart" },
  syncClock: { domain: "button", key: "sync_clock" },
  loadBalancing: { domain: "binary_sensor", key: "load_balancing" },
  gridCurrentLimit: { domain: "sensor", key: "grid_current_limit" },
  maxGridPower: { domain: "sensor", key: "max_grid_power" },
};

const STATS = ["sessionEnergy", "sessionDuration"];
const DETAILS = [
  "voltage",
  "lifetimeEnergy",
  "loadBalancing",
  "gridCurrentLimit",
  "maxGridPower",
];

const STRINGS = {
  start: "Start charging",
  stop: "Stop charging",
  restart: "Restart",
  sync_clock: "Sync clock",
  confirm: "Tap again to confirm",
  restarts_charger: "Restarts the charger",
  plug_in: "Plug in a vehicle to start",
  clear_fault: "Restart clears the fault once its cause is gone",
  limit_locked: "Stop charging to change the current limit",
  settings: "Settings and details",
  no_device: "Pick a Spin EV charger in the card settings",
};

/** Seconds a destructive button stays armed waiting for the second tap. */
const ARM_SECONDS = 4;

/** Charging animation tuning. Every timing below is derived from these. */
const ANIMATION = {
  /** Packets on the cable at once; a fraction leaves a partial gap. */
  packetsOnCable: 2.5,
  /** Packet length, in percent of the cable. */
  packetLength: 8,
  /** Seconds one packet takes along the cable, at low and at full current. */
  cableSeconds: [6, 3.5],
  /** Share of the time between two arrivals the car glow takes to sweep. */
  sweepShare: 0.8,
  /** Width of the glow band, in drawing units; the car is 156 long. */
  sweepWidth: 36,
};

const PACKET_SPACING = 100 / ANIMATION.packetsOnCable;
/** Where in the cable cycle a packet's front reaches the car. */
const ARRIVAL_PHASE =
  ((100 - ANIMATION.packetLength) % PACKET_SPACING) / PACKET_SPACING;

const CAR_BODY =
  "M152 92 V70 Q152 64 158 62 L186 44 Q190 41 196 41 H240 Q246 41 250 44 L274 62 " +
  "L298 66 Q308 68 308 78 V88 Q308 92 304 92 H294 A18 18 0 0 0 258 92 H208 " +
  "A18 18 0 0 0 172 92 H156 Q152 92 152 92 Z";
const CABLE_PLUGGED = "M56 88 C76 132 136 124 148 78";
const CABLE_STOWED = "M56 88 C62 104 76 104 76 92";
const BOLT = "M42 47 L35 58 H40 L38 67 L45 56 H40 Z";

const TEMPLATE = `
<style>
  :host {
    --spinev-charging-color: var(--state-sensor-battery-high-color, var(--success-color, #43a047));
    --spinev-paused-color: var(--warning-color, #ffa600);
    --spinev-fault-color: var(--error-color, #db4437);
    --spinev-connected-color: var(--primary-color, #03a9f4);
    --spinev-idle-color: var(--secondary-text-color, #727272);
    --spinev-accent: var(--spinev-idle-color);
    --spinev-control-bg: rgba(var(--rgb-primary-text-color, 33, 33, 33), 0.06);
    --spinev-radius: var(--ha-border-radius-lg, 12px);
    display: block;
  }
  ha-card {
    display: block;
    padding: 16px;
    overflow: hidden;
    height: 100%;
    box-sizing: border-box;
    container-type: inline-size;
  }
  .mode-charging { --spinev-accent: var(--spinev-charging-color); }
  .mode-paused { --spinev-accent: var(--spinev-paused-color); }
  .mode-fault { --spinev-accent: var(--spinev-fault-color); }
  .mode-connected { --spinev-accent: var(--spinev-connected-color); }

  [role="button"] { cursor: pointer; }
  [role="button"]:focus-visible, button:focus-visible, input:focus-visible {
    outline: 2px solid var(--primary-color);
    outline-offset: 2px;
    border-radius: 4px;
  }

  .top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
  }
  .titles { min-width: 0; }
  .name, .since, .chip, .unit, .label {
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-s, 12px);
  }
  .name {
    font-weight: var(--ha-font-weight-medium, 500);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .name, .label {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .status {
    margin-top: 4px;
    font-size: var(--ha-font-size-2xl, 24px);
    line-height: 1.2;
    text-wrap: balance;
    color: var(--spinev-accent);
    transition: color 0.3s;
  }
  .mode-idle .status, .mode-offline .status { color: var(--primary-text-color); }
  .since { margin-top: 2px; }
  .figures { text-align: end; flex: none; }
  .power {
    font-size: var(--ha-font-size-2xl, 24px);
    line-height: 1.2;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 2px;
    margin-top: 6px;
    white-space: nowrap;
  }
  .chip ha-icon { --mdc-icon-size: 18px; color: var(--spinev-accent); }

  .alert {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
    padding: 8px 12px;
    border-radius: var(--spinev-radius);
    color: var(--spinev-fault-color);
    background: color-mix(in srgb, var(--spinev-fault-color) 12%, transparent);
    font-size: var(--ha-font-size-s, 12px);
  }

  svg {
    display: block;
    width: 100%;
    max-height: 150px;
    margin: 12px 0 8px;
    overflow: visible;
  }
  .ground { stroke: var(--divider-color); stroke-width: 2; stroke-linecap: round; }
  .line {
    fill: none;
    stroke: var(--primary-text-color);
    stroke-width: 2;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .fill { fill: var(--spinev-control-bg); }
  .led { fill: var(--spinev-accent); transition: fill 0.3s; }
  .bolt { fill: var(--spinev-accent); transition: fill 0.3s; }
  .charge {
    fill: var(--spinev-accent);
    opacity: 0.28;
    transform-box: fill-box;
    transform-origin: left;
    transform: scaleX(var(--spinev-soc, 0));
    transition: transform 1s ease, fill 0.3s;
  }
  .edge {
    stroke: var(--spinev-accent);
    stroke-width: 2;
    opacity: 0;
    transform: translateX(calc(var(--spinev-soc, 0) * 156px));
    transition: transform 1s ease;
  }
  .cable { transition: stroke 0.3s; }
  .mode-charging .cable { stroke: color-mix(in srgb, var(--spinev-accent) 55%, var(--primary-text-color)); }
  .sweep {
    fill: url(#sweepGlow);
    opacity: 0;
    transform: translateX(-${ANIMATION.sweepWidth}px);
  }
  .flow {
    fill: none;
    stroke: var(--spinev-accent);
    stroke-width: 4;
    stroke-linecap: round;
    stroke-dasharray: ${ANIMATION.packetLength} ${PACKET_SPACING - ANIMATION.packetLength};
    opacity: 0;
    filter: drop-shadow(0 0 3px var(--spinev-accent));
  }
  .port { fill: var(--spinev-accent); opacity: 0; }
  .charger, .plugged, .stowed, .car { transition: opacity 0.5s, transform 0.8s cubic-bezier(0.3, 1.2, 0.6, 1); }
  .stowed { opacity: 0; }
  .car { transform: translateX(10px); opacity: 0.12; }
  .plugged { opacity: 0; }
  .vehicle .car {
    transform: none;
    opacity: 1;
  }
  .vehicle .plugged { opacity: 1; }
  ha-card:not(.vehicle) .stowed { opacity: 1; }
  .mode-offline .charger, .mode-offline .stowed { opacity: 0.35; }

  /* One cycle is the time between two packets reaching the car. The port
     flash and the glow are shifted so each starts as a packet arrives. */
  .mode-charging .flow { opacity: 1; animation: flow var(--spinev-cycle, 2s) linear infinite; }
  .mode-charging .port, .mode-charging .sweep {
    animation-duration: var(--spinev-cycle, 2s);
    animation-iteration-count: infinite;
    animation-delay: calc(var(--spinev-cycle, 2s) * ${-(1 - ARRIVAL_PHASE).toFixed(4)});
  }
  .mode-charging .port {
    filter: drop-shadow(0 0 4px var(--spinev-accent));
    animation-name: port;
    animation-timing-function: ease-out;
  }
  .mode-charging:not(.no-soc) .edge { opacity: 0.8; }
  .mode-charging .sweep { animation-name: sweep; animation-timing-function: linear; }
  .mode-charging .bolt { animation: pulse 2s ease-in-out infinite; }
  .mode-paused .led { animation: pulse 3s ease-in-out infinite; }
  .mode-fault .led, .mode-fault .bolt { animation: blink 1s steps(2, jump-none) infinite; }
  .mode-offline .led { animation: pulse 1.2s ease-in-out infinite; }

  @keyframes flow {
    from { stroke-dashoffset: 0; }
    to { stroke-dashoffset: -${PACKET_SPACING}; }
  }
  @keyframes port {
    from { opacity: 1; }
    40%, to { opacity: 0.55; }
  }
  @keyframes pulse { 50% { opacity: 0.3; } }
  @keyframes blink { 50% { opacity: 0.2; } }
  @keyframes sweep {
    from {
      transform: translateX(-${ANIMATION.sweepWidth}px);
      opacity: 0;
      animation-timing-function: cubic-bezier(0.45, 0, 0.35, 1);
    }
    ${ANIMATION.sweepShare * 15}%, ${ANIMATION.sweepShare * 85}% { opacity: 1; }
    ${ANIMATION.sweepShare * 100}%, to {
      transform: translateX(calc(var(--spinev-sweep, 1) * 156px));
      opacity: 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    * { animation: none !important; transition: none !important; }
    .mode-charging .flow { stroke-dasharray: none; opacity: 0.6; }
  }

  .controls { display: flex; gap: 8px; }
  .control {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    min-width: 48px;
    height: 48px;
    padding: 0 16px;
    box-sizing: border-box;
    border: none;
    border-radius: var(--spinev-radius);
    background: var(--spinev-control-bg);
    color: var(--primary-text-color);
    font: inherit;
    font-size: var(--ha-font-size-m, 14px);
    font-weight: var(--ha-font-weight-medium, 500);
    cursor: pointer;
    transition: background 0.2s, color 0.2s, opacity 0.2s;
    -webkit-tap-highlight-color: transparent;
  }
  .control:hover:not(:disabled) { background: rgba(var(--rgb-primary-text-color, 33, 33, 33), 0.12); }
  .control:disabled { opacity: 0.4; cursor: default; }
  .control.primary {
    flex: 1;
    background: color-mix(in srgb, var(--spinev-accent) 20%, transparent);
    color: var(--spinev-accent);
  }
  .mode-idle .control.primary, .mode-offline .control.primary {
    color: var(--primary-text-color);
    background: var(--spinev-control-bg);
  }
  .control.armed {
    background: color-mix(in srgb, var(--spinev-fault-color) 20%, transparent);
    color: var(--spinev-fault-color);
  }
  .hint {
    margin-top: 6px;
    font-size: var(--ha-font-size-s, 12px);
    color: var(--secondary-text-color);
  }
  .hint:empty { display: none; }

  .stats {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-top: 16px;
  }
  .stat {
    padding: 8px 10px;
    border-radius: var(--spinev-radius);
    background: var(--spinev-control-bg);
    min-width: 0;
  }
  .stat .value {
    margin-top: 2px;
    font-size: var(--ha-font-size-l, 16px);
    font-weight: var(--ha-font-weight-medium, 500);
    font-variant-numeric: tabular-nums;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .limit { margin-top: 16px; }
  .limit-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 8px;
    margin-bottom: 8px;
    font-size: var(--ha-font-size-m, 14px);
  }
  .limit-head .label { font-size: inherit; }
  .limit-head .lock { --mdc-icon-size: 16px; color: var(--secondary-text-color); margin-right: auto; }
  .limit-head .value {
    font-weight: var(--ha-font-weight-medium, 500);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }
  input[type="range"] {
    --pct: 0%;
    --live: 0%;
    -webkit-appearance: none;
    appearance: none;
    display: block;
    width: 100%;
    height: 42px;
    margin: 0;
    border-radius: var(--spinev-radius);
    background: linear-gradient(
      to right,
      var(--spinev-accent) 0 var(--live),
      color-mix(in srgb, var(--spinev-connected-color) 40%, transparent) var(--live) var(--pct),
      var(--spinev-control-bg) var(--pct) 100%
    );
    cursor: pointer;
  }
  input[type="range"]:disabled { cursor: not-allowed; }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 4px;
    height: 24px;
    border-radius: 2px;
    background: var(--primary-text-color);
  }
  input[type="range"]::-moz-range-thumb {
    width: 4px;
    height: 24px;
    border: none;
    border-radius: 2px;
    background: var(--primary-text-color);
  }

  details { margin-top: 12px; }
  summary {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 0;
    color: var(--secondary-text-color);
    font-size: var(--ha-font-size-m, 14px);
    cursor: pointer;
    list-style: none;
  }
  summary::-webkit-details-marker { display: none; }
  summary ha-icon { transition: transform 0.2s; }
  details[open] summary ha-icon { transform: rotate(180deg); }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    min-height: 40px;
  }
  .row .label { font-size: var(--ha-font-size-m, 14px); color: var(--primary-text-color); }
  .row .value { white-space: nowrap; color: var(--secondary-text-color); }
  .row .control { height: 36px; padding: 0 12px; }
  .empty { padding: 24px; text-align: center; color: var(--secondary-text-color); }
  [hidden] { display: none !important; }
</style>
<ha-card>
  <div class="empty" id="empty" hidden></div>
  <div id="body">
    <div class="top">
      <div class="titles">
        <div class="name" id="name"></div>
        <div class="status" id="status" role="button" tabindex="0"></div>
        <div class="since" id="since"></div>
      </div>
      <div class="figures">
        <div class="power" id="power" role="button" tabindex="0"></div>
        <div class="chip" id="battery" role="button" tabindex="0" hidden>
          <ha-icon id="batteryIcon"></ha-icon><span id="batteryValue"></span>
        </div>
      </div>
    </div>
    <div class="alert" id="alert" role="button" tabindex="0" hidden>
      <ha-icon icon="mdi:alert-circle"></ha-icon><span id="alertText"></span>
    </div>
    <svg class="scene" viewBox="0 0 320 112" aria-hidden="true">
      <defs>
        <clipPath id="carClip"><path d="${CAR_BODY}"></path></clipPath>
        <clipPath id="chargeClip"><rect id="chargeClipRect" x="152" y="38" width="156" height="58"></rect></clipPath>
        <linearGradient id="sweepGlow">
          <stop offset="0" stop-color="#fff" stop-opacity="0"></stop>
          <stop offset="0.7" stop-color="#fff" stop-opacity="0.45"></stop>
          <stop offset="1" stop-color="#fff" stop-opacity="0"></stop>
        </linearGradient>
      </defs>
      <line class="ground" x1="8" y1="108" x2="312" y2="108"></line>
      <g class="car">
        <path class="fill" d="${CAR_BODY}"></path>
        <g clip-path="url(#carClip)">
          <rect class="charge" x="152" y="38" width="156" height="58"></rect>
          <line class="edge" x1="152" y1="38" x2="152" y2="96"></line>
          <g clip-path="url(#chargeClip)">
            <rect class="sweep" x="152" y="38" width="${ANIMATION.sweepWidth}" height="58"></rect>
          </g>
        </g>
        <path class="line" d="${CAR_BODY}"></path>
        <path class="line" d="M180 62 L194 48 Q196 46 199 46 H216 V62 Z M222 46 H238 Q243 46 246 49 L262 62 H222 Z"></path>
        <circle class="line" cx="190" cy="94" r="13"></circle>
        <circle class="line" cx="276" cy="94" r="13"></circle>
      </g>
      <g class="plugged">
        <path class="line cable" d="${CABLE_PLUGGED}"></path>
        <path class="flow" d="${CABLE_PLUGGED}" pathLength="100"></path>
        <rect class="line fill" x="142" y="66" width="11" height="14" rx="3"></rect>
        <circle class="port" cx="147.5" cy="73" r="2.5"></circle>
      </g>
      <g class="stowed">
        <path class="line" d="${CABLE_STOWED}"></path>
        <rect class="line fill" x="71" y="78" width="11" height="14" rx="3"></rect>
      </g>
      <g class="charger">
        <line class="line" x1="40" y1="96" x2="40" y2="108"></line>
        <rect class="line fill" x="20" y="14" width="40" height="82" rx="10"></rect>
        <rect class="led" x="30" y="26" width="20" height="4" rx="2"></rect>
        <path class="bolt" d="${BOLT}"></path>
      </g>
    </svg>
    <div class="controls">
      <button class="control primary" id="toggle" type="button">
        <ha-icon id="toggleIcon" icon="mdi:play"></ha-icon><span id="toggleLabel"></span>
      </button>
      <button class="control" id="restart" type="button">
        <ha-icon icon="mdi:restart"></ha-icon>
      </button>
    </div>
    <div class="hint" id="hint" aria-live="polite"></div>
    <div class="stats" id="stats"></div>
    <div class="limit" id="limit">
      <div class="limit-head">
        <span class="label" id="limitLabel" role="button" tabindex="0"></span>
        <ha-icon class="lock" id="limitLock" icon="mdi:lock-outline"></ha-icon>
        <span class="value" id="limitValue"></span>
      </div>
      <input type="range" id="limitSlider" />
    </div>
    <details id="details">
      <summary><span>${STRINGS.settings}</span><ha-icon icon="mdi:chevron-down"></ha-icon></summary>
      <div id="rows"></div>
      <div class="row" id="delayRow" role="button" tabindex="0">
        <span class="label" id="delayLabel"></span>
        <span class="value" id="delayValue"></span>
      </div>
      <div class="row" id="syncRow">
        <span class="label" id="syncLabel"></span>
        <button class="control" id="sync" type="button">
          <ha-icon icon="mdi:clock-check-outline"></ha-icon>
        </button>
      </div>
    </details>
  </div>
</ha-card>
`;

/** Find the device's entity for each role. */
function resolveEntities(hass, deviceId) {
  const found = {};
  for (const entry of Object.values(hass.entities)) {
    if (entry.device_id !== deviceId || entry.platform !== INTEGRATION) continue;
    const domain = entry.entity_id.split(".")[0];
    const deviceClass = hass.states[entry.entity_id]?.attributes.device_class;
    for (const [role, spec] of Object.entries(ROLES)) {
      if (spec.domain !== domain || found[role]) continue;
      const matches = spec.key
        ? entry.translation_key === spec.key
        : !entry.translation_key && deviceClass === spec.deviceClass;
      if (matches) found[role] = entry.entity_id;
    }
  }
  return found;
}

/** The charger's device, but only when there is exactly one to choose. */
function onlyDevice(hass) {
  const devices = new Set(
    Object.values(hass.entities)
      .filter((entry) => entry.platform === INTEGRATION && entry.device_id)
      .map((entry) => entry.device_id),
  );
  return devices.size === 1 ? [...devices][0] : undefined;
}

function isOn(stateObj) {
  return stateObj?.state === "on";
}

function isUsable(stateObj) {
  return !!stateObj && stateObj.state !== "unavailable" && stateObj.state !== "unknown";
}

/** A button's state is when it was last pressed, so unknown is normal. */
function isPressable(stateObj) {
  return !!stateObj && stateObj.state !== "unavailable";
}

function clamp01(value) {
  return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
}

function batteryIcon(level, charging) {
  const base = charging ? "mdi:battery-charging" : "mdi:battery";
  const step = Math.round(level * 10) * 10;
  if (step === 0) return `${base}-outline`;
  if (step === 100) return charging ? `${base}-100` : base;
  return `${base}-${step}`;
}

function humanize(value) {
  const text = String(value).replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

class SpinEvChargerCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = TEMPLATE;
    this._el = (id) => this.shadowRoot.getElementById(id);
    this._card = this.shadowRoot.querySelector("ha-card");
    this._armed = null;
    this._sliding = false;
    this._bind();
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "device_id",
          required: true,
          selector: { device: { filter: { integration: INTEGRATION } } },
        },
        {
          name: "battery_entity",
          selector: { entity: { filter: { domain: "sensor", device_class: "battery" } } },
        },
        { name: "name", selector: { text: {} } },
        { name: "show_settings", default: true, selector: { boolean: {} } },
        { name: "confirm_restart", default: true, selector: { boolean: {} } },
      ],
      computeLabel: (schema) =>
        ({
          device_id: "Charger",
          battery_entity: "Vehicle battery",
          name: "Name",
          show_settings: "Show settings and details",
          confirm_restart: "Confirm before restarting",
        })[schema.name],
      computeHelper: (schema) =>
        ({
          battery_entity: "The car's state of charge, shown as the car filling up",
          confirm_restart:
            "Restart and sync clock both restart the charger, ending any session. When on, they need a second tap.",
        })[schema.name],
    };
  }

  static getStubConfig(hass) {
    const first = Object.values(hass.entities).find(
      (entry) => entry.platform === INTEGRATION && entry.device_id,
    );
    return { device_id: first?.device_id ?? "" };
  }

  setConfig(config) {
    if (!config || typeof config !== "object") throw new Error("Invalid configuration");
    this._config = { show_settings: true, confirm_restart: true, ...config };
    this._entities = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    const previous = this._hass;
    this._hass = hass;
    if (!this._config) return;
    if (previous?.entities !== hass.entities) this._entities = null;
    if (this._entities && !this._changed(previous)) return;
    this._render();
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 6, min_columns: 6, rows: "auto" };
  }

  connectedCallback() {
    this._tick = setInterval(() => this._renderSince(), 30000);
  }

  disconnectedCallback() {
    clearInterval(this._tick);
    this._disarm();
  }

  get _deviceId() {
    return this._config.device_id || onlyDevice(this._hass);
  }

  /** Whether any entity the card shows has a new state object. */
  _changed(previous) {
    if (!previous) return true;
    return Object.values(this._entities).some(
      (entityId) => entityId && previous.states[entityId] !== this._hass.states[entityId],
    );
  }

  _state(role) {
    const entityId = this._entities?.[role];
    return entityId ? this._hass.states[entityId] : undefined;
  }

  _bind() {
    const moreInfo = (el, role) => {
      const open = () => this._moreInfo(this._entities?.[role]);
      el.addEventListener("click", open);
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          open();
        }
      });
    };
    moreInfo(this._el("status"), "status");
    moreInfo(this._el("power"), "power");
    moreInfo(this._el("battery"), "battery");
    moreInfo(this._el("alert"), "problem");
    moreInfo(this._el("limitLabel"), "currentLimit");
    moreInfo(this._el("delayRow"), "startDelay");
    this._moreInfoOn = moreInfo;

    this._el("toggle").addEventListener("click", () => this._toggleSession());
    this._el("restart").addEventListener("click", (ev) =>
      this._armThenPress(ev.currentTarget, "restart"),
    );
    this._el("sync").addEventListener("click", (ev) => {
      ev.stopPropagation();
      this._armThenPress(ev.currentTarget, "syncClock");
    });

    const slider = this._el("limitSlider");
    slider.addEventListener("input", () => {
      this._sliding = true;
      this._paintSlider();
    });
    slider.addEventListener("change", () => {
      this._sliding = false;
      this._call("number", "set_value", "currentLimit", { value: Number(slider.value) });
    });
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    this.dispatchEvent(
      new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }),
    );
  }

  _notify(message) {
    this.dispatchEvent(
      new CustomEvent("hass-notification", { detail: { message }, bubbles: true, composed: true }),
    );
  }

  _call(domain, service, role, data = {}) {
    const entityId = this._entities?.[role];
    if (!entityId) return Promise.resolve();
    return this._hass
      .callService(domain, service, data, { entity_id: entityId })
      .catch((err) => this._notify(err.message ?? String(err)));
  }

  _toggleSession() {
    const active = isOn(this._state("session"));
    this._call("switch", active ? "turn_off" : "turn_on", "session");
  }

  /** Destructive buttons need a second tap, since both restart the charger. */
  _armThenPress(button, role) {
    if (this._armed === role || !this._config.confirm_restart) {
      this._disarm();
      this._renderControls(this._mode());
      this._call("button", "press", role);
      return;
    }
    this._disarm();
    this._armed = role;
    button.classList.add("armed");
    button.setAttribute("title", STRINGS.confirm);
    this._el("hint").textContent = `${STRINGS.confirm} · ${STRINGS.restarts_charger}`;
    this._armTimer = setTimeout(() => {
      this._disarm();
      if (this._hass && this._entities) this._renderControls(this._mode());
    }, ARM_SECONDS * 1000);
  }

  _disarm() {
    clearTimeout(this._armTimer);
    this._armed = null;
    for (const id of ["restart", "sync"]) {
      this._el(id).classList.remove("armed");
      this._el(id).removeAttribute("title");
    }
  }

  /** One of idle, connected, charging, paused, fault or offline. */
  _mode() {
    const status = this._state("status");
    if (!isUsable(status) || ["booting", "unavailable"].includes(status.state)) return "offline";
    if (isOn(this._state("problem")) || status.state === "fault") return "fault";
    if (status.state === "charging") return "charging";
    if (["ev_suspended", "evse_suspended"].includes(status.state)) return "paused";
    if (isOn(this._state("vehicle"))) return "connected";
    return "idle";
  }

  _render() {
    const hass = this._hass;
    const deviceId = this._deviceId;
    if (!this._entities && deviceId) {
      const found = resolveEntities(hass, deviceId);
      // Entities can arrive before their states at startup; resolve again later.
      if (found.status && hass.states[found.status]) {
        this._entities = { ...found, battery: this._config.battery_entity };
      }
    }

    const ready = !!this._entities;
    this._el("empty").hidden = ready;
    this._el("body").hidden = !ready;
    if (!ready) {
      this._el("empty").textContent = STRINGS.no_device;
      return;
    }

    const mode = this._mode();
    const vehicle = this._hasVehicle(mode);
    this._card.className = `mode-${mode}${vehicle ? " vehicle" : ""}`;

    const device = hass.devices?.[deviceId];
    this._el("name").textContent =
      this._config.name || device?.name_by_user || device?.name || "";
    this._el("status").textContent = hass.formatEntityState(this._state("status"));
    this._renderSince();
    this._renderFigures(mode);
    this._renderAlert();
    this._renderControls(mode);
    this._renderTiles(this._el("stats"), STATS, "stat");
    this._renderLimit(mode);
    this._renderDetails();
  }

  _renderSince() {
    const status = this._state("status");
    if (!status || !this._hass) return;
    const seconds = (new Date(status.last_changed).getTime() - Date.now()) / 1000;
    const units = [
      ["day", 86400],
      ["hour", 3600],
      ["minute", 60],
    ];
    const [unit, size] = units.find(([, s]) => Math.abs(seconds) >= s) ?? ["second", 1];
    this._rtf ??= new Intl.RelativeTimeFormat(this._hass.locale?.language, { numeric: "auto" });
    this._el("since").textContent = this._rtf.format(Math.round(seconds / size), unit);
  }

  _renderFigures(mode) {
    const power = this._state("power");
    this._el("power").hidden = !isUsable(power);
    if (isUsable(power)) this._el("power").textContent = this._hass.formatEntityState(power);

    const battery = this._state("battery");
    const level = isUsable(battery) ? clamp01(Number(battery.state) / 100) : null;
    this._el("battery").hidden = level === null;
    if (level !== null) {
      this._el("batteryValue").textContent = this._hass.formatEntityState(battery);
      this._el("batteryIcon").setAttribute("icon", batteryIcon(level, mode === "charging"));
    }
    this._card.classList.toggle("no-soc", level === null);
    this._card.style.setProperty("--spinev-soc", String(level ?? 0));
    // Without the car's charge the glow sweeps the whole car instead.
    const sweep = level ?? 1;
    this._card.style.setProperty("--spinev-sweep", String(sweep));
    this._el("chargeClipRect").setAttribute("width", String(156 * sweep));

    const current = this._state("current");
    const limit = this._state("currentLimit");
    let draw = 0;
    if (mode === "charging" && isUsable(current) && isUsable(limit) && Number(limit.state) > 0) {
      draw = clamp01(Number(current.state) / Number(limit.state));
    }
    const [slow, fast] = ANIMATION.cableSeconds;
    const cableSeconds = slow - draw * (slow - fast);
    this._card.style.setProperty(
      "--spinev-cycle",
      `${(cableSeconds / ANIMATION.packetsOnCable).toFixed(2)}s`,
    );
  }

  _renderAlert() {
    const problem = this._state("problem");
    const alarms = problem?.attributes.alarms ?? [];
    const show = isOn(problem);
    this._el("alert").hidden = !show;
    if (show) {
      this._el("alertText").textContent = alarms.length
        ? alarms.map(humanize).join(", ")
        : this._entityName(problem);
    }
  }

  _renderControls(mode) {
    const session = this._state("session");
    const active = isOn(session);
    const connected = this._hasVehicle(mode);
    const toggle = this._el("toggle");
    toggle.hidden = !session;
    toggle.disabled = !isUsable(session) || (!active && !connected);
    this._el("toggleIcon").setAttribute("icon", active ? "mdi:stop" : "mdi:play");
    this._el("toggleLabel").textContent = active ? STRINGS.stop : STRINGS.start;

    const restart = this._el("restart");
    restart.hidden = !this._entities.restart;
    restart.disabled = !isPressable(this._state("restart"));
    restart.setAttribute("aria-label", STRINGS.restart);

    if (this._armed) return;
    let hint = "";
    if (mode === "fault" && this._entities.restart) hint = STRINGS.clear_fault;
    else if (mode !== "offline" && !active && !connected) hint = STRINGS.plug_in;
    this._el("hint").textContent = hint;
  }

  /** A session in progress means a car is there, whatever the plug sensor last said. */
  _hasVehicle(mode) {
    return isOn(this._state("vehicle")) || mode === "charging" || mode === "paused";
  }

  /** Label and value tiles or rows for the roles the device has. */
  _renderTiles(container, roles, className) {
    const present = roles.filter((role) => this._state(role));
    if (container.dataset.roles !== present.join()) {
      container.dataset.roles = present.join();
      container.replaceChildren(
        ...present.map((role) => {
          const tile = document.createElement("div");
          tile.className = className;
          tile.dataset.role = role;
          tile.setAttribute("role", "button");
          tile.tabIndex = 0;
          const label = document.createElement("div");
          label.className = "label";
          const value = document.createElement("div");
          value.className = "value";
          tile.append(label, value);
          this._moreInfoOn(tile, role);
          return tile;
        }),
      );
    }
    for (const tile of container.children) {
      const stateObj = this._state(tile.dataset.role);
      tile.firstChild.textContent = this._entityName(stateObj);
      tile.lastChild.textContent = this._hass.formatEntityState(stateObj);
    }
  }

  _renderLimit(mode) {
    const limit = this._state("currentLimit");
    this._el("limit").hidden = !limit;
    if (!limit) return;
    const locked = isOn(this._state("session"));
    const slider = this._el("limitSlider");
    slider.min = limit.attributes.min ?? 0;
    slider.max = limit.attributes.max ?? 32;
    slider.step = limit.attributes.step ?? 1;
    slider.disabled = !isUsable(limit) || locked;
    slider.setAttribute("aria-label", this._entityName(limit));
    if (!this._sliding && isUsable(limit)) slider.value = limit.state;

    const current = this._state("current");
    this._live = mode === "charging" && isUsable(current) ? Number(current.state) : null;
    this._el("limitLabel").textContent = this._entityName(limit);
    this._el("limitLock").hidden = !locked;
    this._el("limitLock").setAttribute("title", STRINGS.limit_locked);
    slider.setAttribute("title", locked ? STRINGS.limit_locked : "");
    this._paintSlider();
  }

  _paintSlider() {
    const slider = this._el("limitSlider");
    const min = Number(slider.min);
    const max = Number(slider.max);
    const pct = (value) => (max > min ? clamp01((value - min) / (max - min)) * 100 : 0);
    slider.style.setProperty("--pct", `${pct(Number(slider.value))}%`);
    slider.style.setProperty("--live", `${this._live === null ? 0 : pct(this._live)}%`);

    const unit = this._state("currentLimit")?.attributes.unit_of_measurement ?? "";
    const live = this._live === null ? "" : `${this._live.toFixed(1)} / `;
    this._el("limitValue").textContent = `${live}${slider.value} ${unit}`.trim();
  }

  _renderDetails() {
    const details = this._el("details");
    details.hidden = !this._config.show_settings;
    if (details.hidden) return;
    this._renderTiles(this._el("rows"), DETAILS, "row");

    const delay = this._state("startDelay");
    this._el("delayRow").hidden = !delay;
    if (delay) {
      this._el("delayLabel").textContent = this._entityName(delay);
      this._el("delayValue").textContent = this._hass.formatEntityState(delay);
    }

    const sync = this._state("syncClock");
    this._el("syncRow").hidden = !sync;
    if (sync) {
      this._el("syncLabel").textContent = this._entityName(sync) || STRINGS.sync_clock;
      this._el("sync").disabled = !isPressable(sync);
      this._el("sync").setAttribute("aria-label", STRINGS.sync_clock);
    }
  }

  /** The entity's own name, without the device name in front. */
  _entityName(stateObj) {
    if (!stateObj) return "";
    const formatted = this._hass.formatEntityName?.(stateObj, { type: "entity" });
    if (formatted) return formatted;
    const full = stateObj.attributes.friendly_name ?? stateObj.entity_id;
    const device = this._hass.devices?.[this._deviceId];
    const prefix = device?.name_by_user || device?.name;
    return prefix && full.startsWith(`${prefix} `) ? full.slice(prefix.length + 1) : full;
  }
}

if (!customElements.get(CARD_TYPE)) {
  customElements.define(CARD_TYPE, SpinEvChargerCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: CARD_TYPE,
    name: "Spin EV Charger",
    description: "Charger state, start and stop, current limit and session figures in one card.",
    preview: true,
    documentationURL: "https://github.com/Dr-Blank/spinev-ha#dashboard-card",
  });
}
