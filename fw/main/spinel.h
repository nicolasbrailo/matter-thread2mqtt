#pragma once

// Bring up the OpenThread RCP (OT stack + native 802.15.4 radio). S1: no Spinel
// host transport yet (host_connection_mode = NONE) -- this only validates that the
// radio inits and coexists with the BLE controller. The Spinel<->mux bridge is S2.
// Call after mux_init() (so OT logs are muxed) and bt_init() (NVS already up).
void spinel_init(void);
