# Matter/Thread 2 MQTT — ESP32-C6 firmware

Expose one ESP32-C6 to a Linux host over a **single USB-Serial-JTAG link** as both
a **BLE controller** (Linux/BlueZ is the host) and a **Thread/Spinel RCP**. A mux
frames several logical channels onto the one link; the Linux driver
(`host_driver/host.c`) demuxes and presents real OS interfaces (an `hciN` via
`/dev/vhci`; a Spinel PTY, planned).

## Layout

- `main/mux.c` / `mux.h` — the multiplexer: USB link, framing, TX/RX, `ESP_LOG` capture.
- `main/app_bt.c` / `bt.h` — BLE controller + VHCI↔mux bridge; holds `app_main()`.
- `host_driver/host.c` — Linux driver: demux, `/dev/vhci` BT bridge, log printer
  (built with `host_driver/Makefile`).

## Build / run

Firmware:
```
source ~/.espressif/v6.0/esp-idf/export.sh
idf.py set-target esp32c6
idf.py build flash monitor
```
Host driver:
```
make -C host_driver
sudo host_driver/host /dev/ttyACM0   # native-USB CDC; root needed for /dev/vhci
```
The maintainer builds/flashes/tests on hardware — make code changes and hand off;
don't run build/flash yourself unless asked. IDF console/logs go to **UART0** (a
separate physical port), so they never pollute the mux on the USB link.

## Bring up / test the BT adapter

Flash the firmware, then on the Linux host:

```
sudo hciconfig list                       # See available devices
sudo hciconfig hci0 down                  # take the onboard/built-in adapter out of the way
                                          #   (or: rfkill block <onboard id>)
sudo host_driver/host /dev/ttyACM0        # note the "vhci: created hciN" line -> our index
sudo btmon                                # confirm the Espressif controller (CC:8D:A2:…) comes up
bluetoothctl                              # onboard is down -> ours is the only/default adapter (no select needed)
  power on
  scan on                                 # nearby BLE devices appear
```

Identify ours vs the onboard: the host driver prints the index; `hciconfig -a` shows
`Bus: Virtual` and the Espressif address for ours; in `btmon` ours is the
`= Open Index: CC:8D:A2:…` block.

To keep **both** adapters up instead of downing the onboard, target ours by index
(no MAC needed) — `btmgmt` is index-native:
```
sudo btmgmt --index hci1 power on
sudo btmgmt --index hci1 find -l          # LE scan
```
(or, in bluetoothctl: `select $(hciconfig hci1 | grep -oE '([0-9A-F]{2}:){5}[0-9A-F]{2}')`).

To pair a stress-test device, put a **BLE mouse** in pairing mode and pair it from
`bluetoothctl` (or the GNOME Bluetooth panel, which uses the only present adapter
once the onboard is down).

Sanity check it's really flowing through us: with a scan or the mouse active,
`Ctrl-C` the host driver → the adapter (`hciN`) tears down, the scan/mouse dies.
Audio (A2DP) won't work — the C6 is BLE-only.

## Design (the decisions that matter)

**Frame:** `[type u8][len u16 LE][payload][tail "/mt2mqtt\0" (9B)]`.

| type | name | dir | notes |
|---|---|---|---|
| 4 | SYNC | both | handshake — not implemented (deferred) |
| 5 | PING | host↔fw | liveness |
| 6 | LOG | fw→host | `ESP_LOG` lines, droppable |
| 7 | BT | both | opaque H4 HCI |
| 8 | SPINEL | both | opaque HDLC-Spinel — planned |

**Two TX policies, one serializer.** All USB writes go through `mux_write_locked()`
under a priority-inheriting mutex (frames never interleave):
- **Droppable / async** (logs, ping): `mux_tx()` → queue → low-prio `mux_tx_task`
  → bounded 100 ms write, drop on timeout. Bounded on purpose — avoids hoarding a
  since-boot backlog while no host drains (`cdc_acm` only drains once the port is
  opened, else a blocking write dumps seconds of stale history at connect time).
- **Reliable / sync** (BT, Spinel): `mux_tx_bt()` / `mux_tx_spinel()` write
  straight to USB under the mutex, blocking the (high-priority) caller as
  backpressure, up to a **1 s finite timeout**, then degrade to drop. Priority
  ordering means a flood of logs can't starve them.

**Reliability = backpressure, not buffering.** Each stage blocks its producer when
full, chaining back to the true source (Linux via USB CDC flow control for
host→fw; the BLE controller's own buffer pool for fw→host). **Invariant:** exactly
one timeout in the chain is finite — the reliable TX write. The host→fw paths block
with `portMAX` and rely on that one to break a wedge; don't make it infinite.

**RX (host→fw):** USB read loop → stream buffer (blocking send) → `mux_rx_task`
reassembles whole frames and dispatches per channel.

**Host framing/resync (`host.c`):** raw mode + `tcflush` on open; `drain_on_open()`
swallows the post-open backlog; `process_frames()` resyncs by scanning for the tail
sync-word (never trusts a possibly-bogus `len`).

**BT bridge:** controller-only (no on-device host stack); HCI over VHCI
(`esp_vhci_host_*`), carrying opaque H4. host→ctrl is reassembled to whole packets
and paced by controller flow control; ctrl→host calls `mux_tx_bt()`. Host side:
`/dev/vhci` presents a real `hciN`. Frame cap `MUX_TX_MAX_PAYLOAD`=528 ≥ max H4 ACL
(`5 + CONFIG_BT_LE_ACL_BUF_SIZE` = 522), `_Static_assert`-guarded.

## Current state

**BT works end-to-end, validated on hardware.** BlueZ sees the ESP as an `hciN`
via `/dev/vhci`, LE scan finds devices, and a **BLE HID mouse stayed connected and
stable for minutes** (killing the host driver kills the adapter — proves traffic
really flows through it). No dropped HCI. **The C6 is BLE-only** — no BR/EDR, so
Classic audio (A2DP) is out of scope; stress-test with BLE devices/throughput.

Two open items, both deferred:
- `bt_rx_from_controller` **blocks inside the VHCI `notify_host_recv` callback** to
  backpressure the controller. Fine so far, but untested at high ACL rate; if
  events go missing under load that assumption is wrong and we'd need HCI
  controller-to-host flow control. (Throughput / DLE / 2M-PHY tuning also untested.)
- **SYNC handshake** deferred: drain+resync already gives clean framing. Only edge
  cases would benefit (plugged-but-not-reading 1 s stalls; clean reconnect).

## Next: Spinel / OpenThread RCP over the mux

Goal: fold the standalone RCP (`~/src/mt2m/ot_rcp`, `esp_ot_rcp.c`) into this
firmware so the device does BLE **and** Thread over the one mux. Two facts drive it:
- The RCP today uses `HOST_CONNECTION_MODE_RCP_USB` — **the same USB-Serial-JTAG the
  mux owns** — so OT must hand its Spinel stream to the mux instead of owning the link.
- Coexistence is **off** in the RCP build; BLE + 802.15.4 on the one radio needs SW
  coexistence enabled — the biggest risk.

**Architecture** (mirrors BT; Spinel is just another reliable channel):
- **Device transport seam:** OT does its own HDLC framing, so the mux carries an
  opaque HDLC-Spinel byte stream. Hook via OT-native `otNcpHdlcInit(send_cb)` +
  `otNcpHdlcReceive()`: `send_cb` → chunked `mux_tx_spinel()`; `MUX_MSG_SPINEL` RX →
  `otNcpHdlcReceive()` **under the OT lock** (`esp_openthread_lock_acquire/release`
  — OT is single-threaded; don't call it raw from `mux_rx_task`).
- **Host side:** a **PTY** (not `/dev/vhci` — no kernel virtual-spinel device exists;
  OT host tools want a serial device). `host.c` pumps PTY master ↔ `MUX_MSG_SPINEL`;
  point `ot-daemon`/`otbr-agent` at `spinel+hdlc+uart:///dev/pts/N`.
- Reuses the reliable-channel infra. Spinel may **chunk across frames** (it's a
  stream — no whole-packet-per-frame constraint like BT/VHCI).

**#1 unknown, resolve first:** esp_openthread exposes only `RCP_UART/SPI/USB` host
modes — no "give bytes to my callback" seam. Read the esp_openthread component
source for the cleanest insertion: ideally `host_connection_mode = NONE` then init
the NCP ourselves; fallback is supplying our own transport where it expects one.

**Phases:**
- **S0 — build/config merge: DONE & VERIFIED.** `main/CMakeLists.txt` (explicit
  `SRCS`, requires `openthread esp_event vfs`); `sdkconfig.defaults` enables
  `OPENTHREAD_ENABLED/RADIO`, `IEEE802154_ENABLED`, SW coexistence (already on),
  `FREERTOS_HZ` 100→1000, trims OT features, `OPENTHREAD_LOG_LEVEL_DYNAMIC=n`
  (see gotchas); custom `partitions.csv` gives the app the full 2 MB. Builds & fits.
- **S1 — OT alongside, transport NONE: DONE & VERIFIED.** `main/spinel.c/.h` +
  `main/esp_ot_config.h` (native radio, `HOST_CONNECTION_MODE_NONE`); `spinel_init()`
  registers the eventfd VFS + default event loop and calls `esp_openthread_start()`.
  `app_main` = `mux_init(); bt_init(); spinel_init(); mux_run();`. Confirmed on
  hardware: boots, `SPINEL: OpenThread RCP started` in the muxed logs, **BT mouse
  still works** with the radio + coexistence active. Radio is up but idle (NONE =
  nothing drives Spinel yet).
- **S2 — wire Spinel to mux: ← NEXT.** New `main/spinel_*` code: init the OT NCP
  HDLC transport ourselves (`otNcpHdlcInit(send_cb)`), `send_cb` → chunked
  `mux_tx_spinel()`; add `mux.c` `MUX_MSG_SPINEL` case → `spinel_rx_from_host()` →
  `otNcpHdlcReceive()` **under the OT lock** (`esp_openthread_lock_acquire/release`).
  **First sub-task (the #1 unknown above):** confirm in the esp_openthread source how
  to attach our own NCP when `host_connection_mode = NONE` — does `esp_openthread_start`
  leave the NCP unset for us to init, or do we need a different entry? Headers worth a
  look: `esp_openthread_spinel.h`, `esp_radio_spinel.h`, and the `otNcpHdlc*` OT core
  API. (Add the new `.c` to `main/CMakeLists.txt` SRCS.)
- **S3 — host PTY bridge:** `host_driver/host.c` grows a PTY pump + a third poll fd;
  prints the `/dev/pts/N` to point `ot-daemon`/`otbr-agent` at.
- **S4 — bring-up:** `ot-ctl`/`ot-daemon` form/join a network, ping a Thread node.
- **S5 — coex stress:** BT (mouse/scan) and Thread traffic at once; both stable.

## Gotchas

- Logs flow over the mux only **after** `mux_init()` installs the `ESP_LOG` hook;
  `app_main()` order is `mux_init(); bt_init(); [spinel_init();] mux_run();`.
  Pre-hook / bootloader logs go to UART0 only.
- The `ESP_LOG` hook, `mux_write_locked`, and the reliable senders must **never log
  on their own error paths** — reachable from the hook / under `g_tx_mutex` → recursion.
- **Head-of-line:** RX is one stream buffer + one `mux_rx_task`, so a backpressured
  reliable flow stalls other channels' RX too. Per-channel RX queues would fix it.
- `mux_rx_task` resync is still crude (flush-on-oversize); port the host's tail-scan
  resync if it matters.

### Build gotchas (ESP-IDF)
- **`sdkconfig.defaults` only seeds a *new* `sdkconfig`.** Editing it does nothing
  to an existing `sdkconfig` (and `idf.py reconfigure` won't re-apply it either).
  After changing defaults: `rm sdkconfig && idf.py set-target esp32c6 && idf.py build`
  (set-target also wipes the build dir, so library configs like OpenThread's actually
  rebuild). Or flip the option in `idf.py menuconfig`.
- **List `SRCS` explicitly in `main/CMakeLists.txt`** — IDF evaluates it in CMake
  script mode (requirement expansion), where `file(GLOB ... CONFIGURE_DEPENDS)` is
  illegal, and a plain `GLOB` silently misses files added since the last reconfigure
  (→ `undefined reference`). Add each new `.c` to the `SRCS` line.
- **`CONFIG_OPENTHREAD_LOG_LEVEL_DYNAMIC=n`** is required: with it on,
  `esp_openthread.cpp` calls `otLoggingSetLevel()`, which the OT lib here doesn't
  provide → link error. Static level still routes OT logs to `ESP_LOG`/the mux.
