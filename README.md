# Automate Pulse Pro for Home Assistant

Control **Rollease Acmeda Automate** blinds and shades from Home Assistant through an **Automate Pulse 2 / Pulse PRO hub**, over your local network. No cloud and no account needed.

> **Unofficial.** This is a community project. It is not made, supported or endorsed by Rollease Acmeda. "Automate" and the Automate logo are trademarks of Rollease Acmeda.

## Features
- Open, close, stop and set the position of each blind
- **Names from the Automate app** are used automatically
- Position sensor for each blind (0 % = closed, 100 % = open). Many battery motors don't report their position; for those the position is taken from the commands Home Assistant sends
- Battery level and battery voltage for battery motors. Mains (AC) motors are detected and get no battery sensors
- **Signal strength** and **online status** for each blind, read from the hub's WebSocket (diagnostic)
- **Last blind report** sensor on the hub, so you can see (and automate on) the hub no longer hearing your motors
- **Automatic hub restart** with a smart plug when the hub stops hearing the blinds, plus a **Restart hub** button
- One shared connection to the hub, which reconnects by itself if the hub stops answering
- Blinds are found automatically, and the hub itself is filtered out
- Change the hub's IP address later without losing anything (**Reconfigure**)

## Compatibility
| | |
| --- | --- |
| **Hubs** | Automate Pulse 2 and Pulse PRO. Anything with the local ASCII interface on TCP port **1487**. Tested on a Pulse PRO with firmware 1.3.0 |
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
| Signal strength | `sensor.kitchen_signal_strength` | Radio signal between hub and blind in dBm (diagnostic). Around -90 dBm or lower is weak |
| Online | `binary_sensor.kitchen_online` | Whether the hub considers the blind online (diagnostic) |

The hub device gets one sensor as well:

| Entity | Description |
| --- | --- |
| Last blind report | When a motor's own reply last reached the hub: a position report or a command confirmation. Battery replies don't count, because the hub answers those from memory |
| Restart hub | Power cycles the hub with the smart plug. Only there when a smart plug is set in the options |

**Adding a new blind:** pair it in the Automate app, then open the integration's menu and choose **Reload**. Blinds found earlier are remembered, so a blind that is asleep when Home Assistant starts keeps its entities. They show as unavailable until it responds.

**Hub got a new IP address?** Open the integration's menu (three dots) and choose **Reconfigure**.

## Options
Go to **Settings > Devices & services > Automate Pulse Pro > Configure**:

| Option | What it's for |
| --- | --- |
| Extra blind IDs | Add blinds that discovery missed, e.g. `ABC, X1Y` |
| Blind IDs to ignore | Hide devices you don't want in Home Assistant |
| Position check interval | How often (in seconds) blinds that report their position are asked for it. The default is 60. Blinds that don't answer are only asked once an hour. Positions are also re-checked after every command |
| Reverse position | Turn this on if your blinds show the position the wrong way round (fully open shows 0 %) |
| Read signal strength and online status | On by default. Reads the hub's WebSocket (port 443, the interface the Automate app uses) every 5 minutes. Only reads, never sends commands. Turn it off if your hub doesn't offer it; blind control doesn't depend on it |
| Smart plug that powers the hub | Optional. Turns on automatic restarts (see Troubleshooting) and adds a **Restart hub** button |
| Restart the hub after ... minutes | How long no blind may report before the hub is restarted. Default 30. At least three position checks are always waited for |
| Battery empty / full voltage | Leave both at 0 for automatic (9.6-12.6 V for 12 V packs, 6.4-8.4 V for 8.4 V packs). If the battery % looks wrong, compare it with the *Battery voltage* sensor and set the range yourself |

## Troubleshooting
### The hub stops hearing the motors
This is the most common problem, and it's on the hub's side, not in Home Assistant. The hub keeps **sending** commands, so the blinds still move, but the motors' **replies** stop reaching it. You'll see:
- positions don't follow the remote or the app, and position queries get `Enl` in the debug log
- battery values that never change (the hub keeps answering with an old stored reading, sometimes weeks old)
- **Online** is off for every blind, and **Last blind report** stops changing

**Fix:** restart the hub (unplug it for 30 seconds). The integration reconnects by itself and asks every blind again. Afterwards the blinds report in, and battery values can jump to their real level.

**If it keeps happening:** the hub can't be restarted in software (there is no restart command, not even in the app), so connect it to a **smart plug** and choose that plug in the integration options. The integration then:
- switches the plug off for 30 seconds and back on when no blind has reported for 30 minutes (adjustable)
- restarts at most once every 3 hours, and pauses after 24 hours without any report (until a blind reports again), so a hub that doesn't recover isn't restarted over and over
- only restarts if a blind has reported at least once, so hubs whose blinds never report are left alone
- logs every restart as a warning and fires the event `automate_pulse_pro_hub_restarted` (with `host` and `reason`), which you can use for a notification

Pick a plug that works locally and **switches back on by itself after a power cut**.

Example notification:
```yaml
automation:
  - alias: Tell me when the Pulse hub was restarted
    triggers:
      - trigger: event
        event_type: automate_pulse_pro_hub_restarted
    actions:
      - action: notify.notify
        data:
          message: "The Pulse hub ({{ trigger.event.data.host }}) was restarted ({{ trigger.event.data.reason }})."
```

A weak radio link has the same symptoms for individual blinds. Check **Signal strength**: around -90 dBm or lower is weak. Moving the hub to a more central, higher spot helps, and so can a repeater. Note that the hub only updates the signal value when it hears the motor, so it can be old too.

### Other problems
- **Blind shows as unavailable:** the blind hasn't replied for a while. Check that it's in range of the hub and its battery is charged. If **all** blinds go unavailable, the integration reconnects to the hub by itself after about two minutes. The log shows `reconnecting` when that happens.
- **Battery level doesn't change after charging:** the hub answers battery queries from its memory, and only updates that when the motor reports in. Move the blind once after charging; the integration reads the battery again 1 and 3 minutes after every command. If it still doesn't change, see *The hub stops hearing the motors* above.
- **Position doesn't follow the remote or the app:** the blind isn't answering position queries (the debug log shows `Enl` replies), so Home Assistant only knows the position from its own commands. Often this is the hub not hearing the motors (see above).
- **Signal strength and Online show unavailable:** the hub's WebSocket couldn't be read (the log says why). Blind control is not affected. Turn the option off if your hub doesn't offer it.
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

## Changes in 2.2.3
- **Automatic hub restart with a smart plug.** Choose the plug in the options. When no blind has reported for 30 minutes (adjustable), the hub is switched off for 30 seconds and on again, at most once every 3 hours. Pauses after 24 hours without any report.
- New **Restart hub** button on the hub device (when a smart plug is set).
- New event `automate_pulse_pro_hub_restarted` for notifications.

## Changes in 2.2.2
- **Positions are read again.** Position replies take 3.6 to 3.9 seconds to come back through the hub, but the integration only waited 3 seconds, so every reply counted as "no answer". It now waits up to 8 seconds.
- **Blinds that start answering are picked up automatically**, for example after a hub restart. A blind that reports by itself or confirms a command is asked for its position from then on. After a reconnect, every blind is asked again. Blinds that don't answer are retried every hour instead of every 6 hours.
- **Blinds that stop answering** go back to the hourly retry after 3 unanswered queries in a row, so they don't keep the hub's radio busy.
- **Command confirmations** from the motors (e.g. `o,R88`) are recognised.
- New diagnostic sensors **Signal strength** and **Online** for each blind, read every 5 minutes from the hub's WebSocket (read-only). Can be turned off in the options.
- New diagnostic sensor **Last blind report** on the hub device, to see (and automate on) when the hub stops hearing the motors.
- New troubleshooting section on the hub no longer hearing the motors, with an automatic restart using a smart plug.

## Changes in 2.2.1
- **No more reconnecting every few minutes.** Blinds that don't answer position queries get the reply `Enl` from the hub. That reply now counts as a sign of life, and a cheap heartbeat checks the connection instead.
- **Commands react faster.** Every unanswered position query blocked the hub's radio for about 3.7 seconds, so commands had to wait behind up to 40 seconds of queries. Blinds that don't report their position are now only asked every 6 hours.
- **Blinds no longer go unavailable** just because they don't answer queries. They are available while the hub is connected.
- **Battery is read again 1 and 3 minutes after every command**, and every 10 minutes instead of 30. The hub answers these from memory, so this costs nothing.
- **Position direction fixed.** The hub works in "percent closed" (the same as other Automate integrations). Setting a blind to 25 % now really leaves it 25 % open. The *Reverse position* option is still there for motors that differ.
- The last known position is restored after a restart, and blinds without position feedback are shown with both open and close buttons.

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
