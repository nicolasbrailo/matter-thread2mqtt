file(GLOB_RECURSE srcs "*.c")
idf_component_register(SRCS "${srcs}"
                    PRIV_REQUIRES bt nvs_flash esp_driver_usb_serial_jtag
                    INCLUDE_DIRS ".")
