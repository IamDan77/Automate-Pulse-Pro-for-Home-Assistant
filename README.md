# Automate Pulse Pro for Home Assistant

Control **Rollease Acmeda Automate** blinds and shades from Home Assistant through an **Automate Pulse 2 / Pulse PRO hub**, over your local network. No cloud and no account needed.

> **Unofficial.** This is a community project. It is not made, supported or endorsed by Rollease Acmeda. "Automate" and the Automate logo are trademarks of Rollease Acmeda.

## Features
- Open, close, stop and set the position of each blind
- **Names from the Automate app** are used automatically
- Position sensor for each blind (0 % = closed, 100 % = open)
- Battery level and battery voltage for battery motors. Mains (AC) motors are detected and get no battery sensors
- One shared connection to the hub, which reconnects by itself if the hub stops answering
- Blinds are found automatically, and the hub itself is filtered out
- Change the hub's IP address later without losing anything (**Reconfigure**)

## Compatibility
| | |
| --- | --- |
| **Hubs** | Automate Pulse 2 and Pulse PRO. Anything with the local ASCII interface on TCP port **1487** |
| **Not supported** | The original Pulse (v1) hub. It doesn't offer the port 1487 interface |
| **Motors** | Automate ARC motors: battery (DC) and mains (AC) |
| **Home Assistant** | 2024.12 or newer |
| **Several hubs** | Yes. Add the integration once per hub |

## Before you start
1. Add all your blinds to the **Automate app** first, and give them names there.
2. Give the hub a **fixed IP address** (a DHCP reservation in your router).

## Installation

### With HACS (recommended)
1. Install [HACS](https://hacs.xyz) if you don't already have it.
2. Open HACS, click the menu (three dots, top right) and choose **Custom repositories**.
3. Paste `https://github.com/IamDan77/Automate-Pulse-Pro-for-Home-Assistant` and choose the category **Integration**.
4. Click **Add**, find **Automate Pulse Pro** in the list and install it.
5. Restart Home Assistant.

### Manually
1. Download the latest release.
2. Copy the `custom_components/automate_pulse_pro` folder (note the **underscores**) into your Home Assistant `config/custom_components/` folder.
3. Restart Home Assistant.

## Setup
1. Go to **Settings > Devices & services > Add integration** and search for **Automate Pulse Pro**.
2. Enter the hub's IP address. Leave the port at **1487**.
3. Home Assistant checks that it can reach the hub and finds your blinds. With many blinds this can take 10-20 seconds.

Each blind becomes a device, named as in the Automate app, with these entities:

| Entity | Example | Description |
| --- | --- | --- |
| Cover | `cover.kitchen` | The blind itself |
| Position | `sensor.kitchen_position` | 0 % = closed, 100 % = open |
| Battery | `sensor.kitchen_battery` | Battery level in %. Battery motors only |
| Battery voltage | `sensor.kitchen_battery_voltage` | Raw voltage (diagnostic). Battery motors only |

**Adding a new blind:** pair it in the Automate app, then open the integration's menu and choose **Reload**. Blinds found earlier are remembered, so a blind that is asleep when Home Assistant starts keeps its entities. They show as unavailable until it responds.

**Hub got a new IP address?** Open the integration's menu (three dots) and choose **Reconfigure**.

## Options
Go to **Settings > Devices & services > Automate Pulse Pro > Configure**:

| Option | What it's for |
| --- | --- |
| Extra blind IDs | Add blinds that discovery missed, e.g. `ABC, X1Y` |
| Blind IDs to ignore | Hide devices you don't want in Home Assistant |
| Position check interval | How often (in seconds) each blind is asked for its position. The default is 60. Positions are also re-checked after every command |
| Reverse position | Turn this on if your blinds show the position the wrong way round (fully open shows 0 %) |
| Battery empty / full voltage | Leave both at 0 for automatic (9.6-12.6 V for 12 V packs, 6.4-8.4 V for 8.4 V packs). If the battery % looks wrong, compare it with the *Battery voltage* sensor and set the range yourself |

## Troubleshooting
- **Blind shows as unavailable:** the blind hasn't replied for a while. Check that it's in range of the hub and its battery is charged. If **all** blinds go unavailable, the integration reconnects to the hub by itself after about two minutes. The log shows `reconnecting` when that happens.
- **Battery shows unknown:** the voltage doesn't match a known pack. Set the voltage range in Options.
- **Position is the wrong way round:** turn on **Reverse position** in Options.
- **Other apps or systems use the hub too:** the hub can drop a connection when another one connects. The integration reconnects automatically, but avoid having several local integrations connected to the same hub.
- **Turn on debug logging** to see every message sent to and received from the hub:
  ```yaml
  logger:
    logs:
      custom_components.automate_pulse_pro: debug
  ```
  Please include a debug log when you [open an issue](https://github.com/IamDan77/Automate-Pulse-Pro-for-Home-Assistant/issues).

## Upgrading from version 1.0
Install the update through HACS and restart Home Assistant. Your blinds keep their entity IDs, history and the names and rooms you gave them, so your automations keep working. What's new:
- A **Pulse PRO hub** device appears, with the blinds linked to it.
- Each blind gets two new sensors: **Position** and **Battery voltage**.
- Battery percentages use a corrected range, so they look different from version 1. Version 1 showed 0 % for most 12 V packs.
- The hub itself is recognised and no longer added as a blind.

## Contributing
Issues and pull requests are welcome. Version 1 was vibe coded using Gemini; version 2 is a rewrite.

## Changes in 2.2.0
- **Works with other people's hubs out of the box:** the hub itself is recognised from the version reply (motors answer `vD`/`vA`), so it is no longer added as a blind, whatever its ID. Older versions could add it (e.g. `BR1`); it is now removed automatically.
- **Names from the Automate app** are used for new devices. Names you set in Home Assistant are kept.
- **Mains (AC) motors** are detected and no longer get battery sensors.
- **Reconfigure:** change the hub's IP address or port without removing the integration.
- New option **Reverse position** for motors that report the position the other way round.
- Fully open and fully closed now send the open/close command, so blinds reach their end positions (the position command only goes up to 99 %).
- Modern entity naming: entity names are added to the device name (e.g. "Kitchen Battery"). Existing entity IDs don't change.
- The blind ID is shown as the serial number on the device page.

## Changes in 2.1.3 (not released separately)
- Fixed blinds staying unavailable until the integration was reloaded. The check that reconnects a connection that has stopped working counted every message from the hub, including ones that are not blind replies. So when the hub kept the connection open but stopped passing on blind replies, the integration never reconnected. Now only position and battery replies from blinds count. After two polls with no blind reply, it reconnects by itself.
- Reconnects are now logged as warnings, so you can see them in the normal log.
- Brand icon and logo moved to the `brand/` folder, so Home Assistant 2026.3 and newer shows them.

## Changes in 2.1.2 (not released separately)
- Discovery now waits long enough for every blind to answer the position query. The hub relays queries over RF one blind at a time, so with many blinds the 3-second wait was too short and none were recognised. This caused the "None of the devices ... answered a position query" warning and added the hub itself as a blind. If no blind answers at all, they are all asked a second time. With many blinds the integration can take 10-20 seconds to start; that is normal.
- Removed the deprecated `via_device` device link (it stops working in Home Assistant 2027.8). Blind devices are now linked to the hub with `via_device_id`. Existing devices, entities and history are kept.

## Changes in 2.1.1
- Fixed all blinds going unavailable and staying that way when the hub stops answering without closing the connection (for example after another app or a test command connects to it, or after a Wi-Fi blip). The integration now notices when no blind has answered for two polls and reconnects by itself.
- TCP keepalive on the hub connection, so a hub that reboots or drops off the network is detected within about a minute.
- Polling and reconnecting can no longer stop permanently after an unexpected error. The error is logged instead.

## Changes in 2.1.0
- New position sensor for each blind (0 % = closed, 100 % = open), so the position can be shown on dashboards, graphed in history and used in automations.

## Changes in 2.0.1
- Fixed battery reading 0 % on every blind: 12 V packs report about 10.4 V in normal use, below the old 11.0 V "empty" value. The automatic range is now 9.6-12.6 V (12 V packs) and 6.4-8.4 V (8.4 V packs).
- Hub replies with extra leading characters (e.g. `!!KCPpVc01038,R62`) are now read correctly.

## Changes in 2.0.0
- Removed the hard-coded fallback blind (`WSG`). If the hub can't be reached at startup, Home Assistant now retries instead of adding a fake blind.
- One shared, automatically reconnecting connection replaces a new connection per entity per poll.
- Blinds show as **unavailable** when the hub or blind stops responding, and as **unknown** until their first reading, instead of a made-up 50%.
- Setup now tests the connection, prevents adding the same hub twice, and has no pre-filled IP address.
- The hub is no longer identified by the hard-coded ID `BR1`. Only devices that answer a position query are added, and you can add or ignore IDs in Options.
- The battery range is detected automatically or can be set yourself. There is a new voltage diagnostic sensor.
- Fixed the folder name in the manual install instructions.
- Existing blinds keep the same entity IDs, so automations and history are not affected.
