"""Constants for the Automate Pulse PRO integration."""

DOMAIN = "automate_pulse_pro"

DEFAULT_PORT = 1487

# Config entry data
CONF_BLINDS = "blinds"  # Blind IDs discovered so far (kept between restarts)
CONF_NAMES = "names"  # Blind names from the Automate app, by ID
CONF_MAINS = "mains_blinds"  # Blinds with a mains (AC) motor: no battery

# Options
CONF_EXTRA_BLINDS = "extra_blinds"
CONF_EXCLUDED_BLINDS = "excluded_blinds"
CONF_POSITION_INTERVAL = "position_interval"
CONF_BATTERY_MIN_V = "battery_min_voltage"
CONF_BATTERY_MAX_V = "battery_max_voltage"
CONF_INVERT_POSITION = "invert_position"
CONF_USE_WEBSOCKET = "use_websocket"
CONF_RESTART_SWITCH = "restart_switch"  # smart plug that powers the hub
CONF_RESTART_AFTER = "restart_after"  # minutes without a blind report

DEFAULT_USE_WEBSOCKET = True
DEFAULT_RESTART_AFTER = 30
MIN_RESTART_AFTER = 10
MAX_RESTART_AFTER = 1440

DEFAULT_POSITION_INTERVAL = 60  # seconds
MIN_POSITION_INTERVAL = 15
MAX_POSITION_INTERVAL = 3600

# Hub protocol (ASCII). Commands are sent as "!<ID><action>;"
CMD_DISCOVER = "!000v?;"
ACTION_QUERY_POSITION = "r?"
ACTION_QUERY_VOLTAGE = "pVc?"
ACTION_QUERY_NAME = "NAME?"
ACTION_OPEN = "o"
ACTION_CLOSE = "c"
ACTION_STOP = "s"
ACTION_MOVE = "m"

# Timings (seconds)
CONNECT_TIMEOUT = 5.0
REQUEST_TIMEOUT = 3.0
# Position replies are relayed by the hub over RF and take about 3.6-3.9 s
# (measured on a Pulse PRO), so they need a longer wait than other requests.
# "Enl" (blind didn't answer) arrives after about 3.7 s as well.
POSITION_TIMEOUT = 8.0
PROBE_TIMEOUT = 3.0  # base wait for position replies during discovery
PROBE_PER_BLIND = 1.0  # extra wait per blind: the hub asks blinds one by one over RF
PROBE_MAX = 20.0
PROBE_QUIET = 3.0  # stop waiting once no new reply has come in for this long
NAME_TIMEOUT = 3.0  # wait for blind names (stored on the hub, so they come back fast)
PROBE_SETTLE = 1.0  # pause after the version query before asking for positions
COMMAND_GAP = 0.15  # pause between commands so the hub is not flooded
DISCOVERY_QUIET = 2.0  # stop listening once the hub has been quiet this long
DISCOVERY_MAX = 8.0
RECONNECT_MIN_DELAY = 5.0
RECONNECT_MAX_DELAY = 120.0
BATTERY_INTERVAL = 600  # the hub answers voltage queries itself, so this is cheap
FOLLOW_UP_DELAYS = (3, 15, 40)  # re-read position this long after a command
VOLTAGE_FOLLOW_UP_DELAYS = (60, 180)  # re-read voltage after a command
# Blinds that don't answer position queries (the hub replies "Enl") are only
# asked again this often, so they don't keep the hub's radio busy. A blind
# that reports by itself (e.g. after the hub restarts) is picked up at once.
POSITION_RETRY_INTERVAL = 3600
# A blind that used to answer goes back to the slow retry after this many
# unanswered position queries in a row
POSITION_FAILURES_BEFORE_RETRY = 3
HEARTBEAT_TIMEOUT = 5.0
SILENT_ROUNDS_BEFORE_RECONNECT = 2  # polls with no reply at all before reconnecting

# Battery profiles used when no voltage range is set in the options:
# (use if voltage is above, empty voltage, full voltage)
# 12 V packs report around 10.4 V in normal use, so "empty" must be well below
# that (v1 used 11.0 V, which made every blind read 0 %).
BATTERY_PROFILES = (
    (8.8, 9.6, 12.6),  # 12 V (3-cell) packs: 3.2-4.2 V per cell
    (5.0, 6.4, 8.4),  # 8.4 V (2-cell) packs: 3.2-4.2 V per cell
)

# Listener key for entities that belong to the hub rather than to one blind
HUB_LISTENER = "__hub__"

# WebSocket interface of the hub (the one the Automate app uses). Only used to
# read signal strength and online status; everything else goes over port 1487.
WS_PORT = 443
WS_PATH = "/rpc"
WS_INTERVAL = 300  # seconds between reads; the hub serialises its whole state
WS_TIMEOUT = 15.0
WS_STALE_AFTER = 3 * WS_INTERVAL  # sensors go unavailable without fresh data

# Automatic hub restart with a smart plug
RESTART_OFF_TIME = 30  # seconds the plug stays off
RESTART_LOCKOUT = 3 * 3600  # at most one automatic restart this often
# Stop restarting once no blind has reported for this long: either restarts
# don't help, or the blinds on this hub never report (nothing to fix)
RESTART_GIVE_UP = 24 * 3600
RESTART_CHECK_INTERVAL = 60
EVENT_HUB_RESTARTED = f"{DOMAIN}_hub_restarted"
