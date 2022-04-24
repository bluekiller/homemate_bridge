"""The Homemate Bridge integration."""
from __future__ import annotations

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import CONF_DEVICES, CONF_IP_ADDRESS, CONF_NAME, CONF_UNIQUE_ID
from homeassistant.helpers import config_validation as cv

from threading import Thread


from .const import (
    CONF_BIND_ADDRESS,
    CONF_BIND_PORT,
    CONF_DEVICE_TYPE,
    DATA_HANDLERS,
    DATA_HANDLER_COVER,
    DATA_HANDLER_LIGHT,
    DATA_HANDLER_QUEUES,
    DATA_HANDLER_SWITCH,
    DOMAIN,
)
from .homemate import HomemateTCPHandler
import logging
import copy
import json
import socketserver
import voluptuous as vol
import janus
import socket

DEVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_IP_ADDRESS): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_DEVICE_TYPE): cv.string,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            vol.Schema(
                {
                    vol.Optional(CONF_BIND_ADDRESS): cv.string,
                    vol.Optional(CONF_BIND_PORT): cv.positive_int,
                    vol.Optional(CONF_DEVICES, default=[]): vol.All(
                        cv.ensure_list, [DEVICE_SCHEMA]
                    ),
                }
            ),
        )
    },
    extra=vol.ALLOW_EXTRA,
)

PLATFORMS: list[str] = ["light", "cover"]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Homemate Bridge component."""
    _LOGGER.debug("async_setup in __init__")
    if DOMAIN not in config:
        return True
    if DOMAIN in hass.data:
        return False
    # Save and set default for the YAML config
    config_yaml = json.loads(json.dumps(config[DOMAIN]))

    hass.async_add_job(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=copy.deepcopy(config_yaml),
        )
    )

    return True


class Server(socketserver.ThreadingTCPServer):
    """A server can reuse address"""

    allow_reuse_address = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Homemate Bridge from a config entry."""
    _LOGGER.debug("async_setup_entry in __init__, config: %s", entry.data)

    if not entry.unique_id:
        hass.config_entries.async_update_entry(entry, unique_id=entry.title)

    hass.data[DOMAIN] = {}
    hass.data[DOMAIN][DATA_HANDLER_QUEUES] = {
        DATA_HANDLER_LIGHT: janus.Queue(),
        DATA_HANDLER_COVER: janus.Queue(),
        DATA_HANDLER_SWITCH: janus.Queue(),
    }
    hass.data[DOMAIN][DATA_HANDLERS] = set()
    hass.data[DOMAIN][CONF_DEVICES] = {}

    address = entry.data[CONF_BIND_ADDRESS]
    port = entry.data[CONF_BIND_PORT]
    server = Server((address, port), HomemateTCPHandler)
    server.hass = hass

    _LOGGER.debug("Homemate Server listening at %s:%s", address, port)
    server_thread = Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    hass.data[DOMAIN]["server"] = server

    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("async_unload_entry in __init__, config: %s", entry.data)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        server: socketserver.ThreadingTCPServer = hass.data[DOMAIN]["server"]
        if server:
            _LOGGER.debug("Shutdown server")
            server.shutdown()
            for _ in hass.data[DOMAIN][DATA_HANDLERS].copy():
                _LOGGER.debug(
                    "Closing connetion to: %s:%s",
                    _.client_address[0],
                    _.client_address[1],
                )
                _.request.shutdown(socket.SHUT_RDWR)
                _.request.close()
            server.server_close()
        _LOGGER.debug("async_unload_entry done")
        hass.data[DOMAIN] = None
    return unload_ok
