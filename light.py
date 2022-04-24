"""Platform for light integration."""
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.light import LightEntity
from typing import Any
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
    _LOGGER.debug("Setup light entry, conf: %s", config_entry)
    updater = EntityUpdater(
        hass.data[DOMAIN][DATA_HANDLER_QUEUES]["light"].async_q,
        async_add_entities,
        HomemateLight,
    )
    hass.loop.create_task(updater.async_run(hass))
    _LOGGER.debug("Light entry setup finished")
    return True


class HomemateLight(HomemateEntity, LightEntity):
    """Representation of an homemate light."""

    # A unique_id for this entity with in this domain. This means for example if you
    # have a sensor on this cover, you must ensure the value returned is unique,
    # which is done here by appending "_cover". For more information, see:
    # https://developers.home-assistant.io/docs/entity_registry_index/#unique-id-requirements
    # Note: This is NOT used to generate the user visible Entity ID used in automations.
    @property
    def unique_id(self) -> str:
        """Return Unique ID string."""
        return f"{self.handler.uid}_light"

    # This is the name for this *entity*, the "name" attribute from "device_info"
    # is used as the device name for device screens in the UI. This name is used on
    # entity screens, and used to build the Entity ID that's used is automations etc.
    @property
    def name(self) -> str:
        """Return the name of the roller."""
        return f"{self.handler.device_name} Light"

    @property
    def is_on(self):
        """Return true if light is on."""
        return self.handler.switch_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Instruct the light to turn on.
        You can skip the brightness part if your light does not support
        brightness control.
        """
        await self.handler.order_state_change({"light": "on"})

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Instruct the light to turn off."""
        await self.handler.order_state_change({"light": "off"})
