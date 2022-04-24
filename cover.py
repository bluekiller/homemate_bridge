"""Platform for sensor integration."""
from __future__ import annotations

from typing import Any

# These constants are relevant to the type of entity we are using.
# See below for how they are used.
from homeassistant.components.cover import (
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    SUPPORT_STOP,
    CoverEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, DATA_HANDLER_QUEUES
from .homemate_entity import EntityUpdater, HomemateEntity

import logging

_LOGGER = logging.getLogger(__name__)

# This function is called as part of the __init__.async_setup_entry (via the
# hass.config_entries.async_forward_entry_setup call)
async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Setup entry"""
    _LOGGER.debug("Setup cover entry, conf: %s", config_entry)
    updater = EntityUpdater(
        hass.data[DOMAIN][DATA_HANDLER_QUEUES]["cover"].async_q,
        async_add_entities,
        HomemateCover,
    )
    hass.loop.create_task(updater.async_run(hass))
    _LOGGER.debug("Cover entry setup finished")
    return True


# This entire class could be written to extend a base class to ensure common attributes
# are kept identical/in sync. It's broken apart here between the Cover and Sensors to
# be explicit about what is returned, and the comments outline where the overlap is.
class HomemateCover(HomemateEntity, CoverEntity):
    """Representation of a homemate cover."""

    # The supported features of a cover are done using a bitmask. Using the constants
    # imported above, we can tell HA the features that are supported by this entity.
    # If the supported features were dynamic (ie: different depending on the external
    # device it connected to), then this should be function with an @property decorator.
    supported_features = SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_STOP

    # A unique_id for this entity with in this domain. This means for example if you
    # have a sensor on this cover, you must ensure the value returned is unique,
    # which is done here by appending "_cover". For more information, see:
    # https://developers.home-assistant.io/docs/entity_registry_index/#unique-id-requirements
    # Note: This is NOT used to generate the user visible Entity ID used in automations.
    @property
    def unique_id(self) -> str:
        """Return Unique ID string."""
        return f"{self.handler.uid}_cover"

    # This is the name for this *entity*, the "name" attribute from "device_info"
    # is used as the device name for device screens in the UI. This name is used on
    # entity screens, and used to build the Entity ID that's used is automations etc.
    @property
    def name(self) -> str:
        """Return the name of the roller."""
        return f"{self.handler.device_name} Cover"

    # The follwing properties are how HA knows the current state of the device.
    # These must return a value from memory, not make a live query to the device/hub
    # etc when called (hence they are properties). For a push based integration,
    # HA is notified of changes via the async_write_ha_state call. See the __init__
    # method for hos this is implemented in this example.
    # The properties that are expected for a cover are based on the supported_features
    # property of the object. In the case of a cover, see the following for more
    # details: https://developers.home-assistant.io/docs/core/entity/cover/
    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed, same as position 0."""
        return self.handler.position == 100

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing or not."""
        return self.handler.moving < 0

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening or not."""
        return self.handler.moving > 0

    @property
    def current_cover_position(self):
        """Return the current position of the cover."""
        _LOGGER.debug("current_cover_position: %s", self.handler.position)
        return 100 - self.handler.position

    # These methods allow HA to tell the actual device what to do. In this case, move
    # the cover to the desired position, or open and close it all the way.
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self.handler.order_state_change({"cover": "up"})

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self.handler.order_state_change({"cover": "down"})

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.handler.order_state_change({"cover": "stop"})
