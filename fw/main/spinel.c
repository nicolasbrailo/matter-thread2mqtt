/*
 * OpenThread RCP bring-up.
 *
 * The Linux host runs the full OpenThread stack; this firmware is the radio
 * co-processor, exchanging Spinel with the host. Eventually that Spinel stream
 * rides the USB mux as MUX_MSG_SPINEL (S2). For now (S1) we start OT with NO host
 * transport (host_connection_mode = NONE) just to confirm the 802.15.4 radio comes
 * up and coexists with the BLE controller.
 *
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 */

#include "esp_err.h"
#include "esp_event.h"
#include "esp_log.h"

#include "esp_openthread.h"
#include "esp_openthread_types.h"
#include "esp_vfs_eventfd.h"

#include "esp_ot_config.h"
#include "spinel.h"

static const char *tag = "SPINEL";

void spinel_init(void) {
  // OT uses eventfds for its task queue and the radio driver.
  esp_vfs_eventfd_config_t eventfd_config = {.max_fds = 2};
  ESP_ERROR_CHECK(esp_vfs_eventfd_register(&eventfd_config));

  // OT posts OPENTHREAD_EVENT_* on the default event loop; create it if nobody
  // else has (bt_init() doesn't). NVS is already initialized by bt_init().
  esp_err_t err = esp_event_loop_create_default();
  if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
    ESP_ERROR_CHECK(err);
  }

  // static: esp_openthread_start may retain the pointer beyond this call.
  static esp_openthread_config_t config = {
      .netif_config = {0}, // radio-only RCP: no netif
      .platform_config = {
          .radio_config = ESP_OPENTHREAD_DEFAULT_RADIO_CONFIG(),
          .host_config  = ESP_OPENTHREAD_DEFAULT_HOST_CONFIG(), // NONE for S1; mux bridge in S2
          .port_config  = ESP_OPENTHREAD_DEFAULT_PORT_CONFIG(),
      },
  };

  // Inits the OT stack + radio and spawns its own mainloop task (non-blocking).
  ESP_ERROR_CHECK(esp_openthread_start(&config));
  ESP_LOGI(tag, "OpenThread RCP started (radio up, host transport NONE)");
}
