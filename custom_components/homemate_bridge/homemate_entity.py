"""Homemate entity."""
from homeassistant.helpers.entity import Entity, DeviceInfo
from .homemate import HomemateTCPHandler
from .const import DOMAIN
import logging
import asyncio

_LOGGER = logging.getLogger(__name__)


class HomemateEntity(Entity):
    """Representation of a homemate entity."""

    # Our dummy class is PUSH, so we tell HA that it should not be polled
    should_poll = False
    # The supported features of a cover are done using a bitmask. Using the constants
    # imported above, we can tell HA the features that are supported by this entity.
    # If the supported features were dynamic (ie: different depending on the external
    # device it connected to), then this should be function with an @property decorator.

    def __init__(self, handler: HomemateTCPHandler) -> None:
        """Initialize the eitity."""
        # Usual setup is done here. Callbacks are added in async_added_to_hass.
        self.handler = handler

    def update_handler(self, handler: HomemateTCPHandler) -> None:
        if self.handler:
            self.handler.remove_callback(self.async_write_ha_state)
        self.handler = handler
        self.handler.register_callback(self.async_write_ha_state)

    async def async_added_to_hass(self) -> None:
        """Run when this Entity has been added to HA."""
        # Importantly for a push integration, the module that will be getting updates
        # needs to notify HA of changes. The dummy device has a registercallback
        # method, so to this we add the 'self.async_write_ha_state' method, to be
        # called where ever there are changes.
        # The call back registration is done once this entity is registered with HA
        # (rather than in the __init__)
        self.handler.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass."""
        # The opposite of async_added_to_hass. Remove any registered call backs here.
        self.handler.remove_callback(self.async_write_ha_state)

    # A unique_id for this entity with in this domain. This means for example if you
    # have a sensor on this cover, you must ensure the value returned is unique,
    # which is done here by appending "_cover". For more information, see:
    # https://developers.home-assistant.io/docs/entity_registry_index/#unique-id-requirements
    # Note: This is NOT used to generate the user visible Entity ID used in automations.
    # @property
    # def unique_id(self) -> str:
    #     """Return Unique ID string."""
    #     return f"{self.handler.uid}_cover"

    # Information about the devices that is partially visible in the UI.
    # The most critical thing here is to give this entity a name so it is displayed
    # as a "device" in the HA UI. This name is used on the Devices overview table,
    # and the initial screen when the device is added (rather than the entity name
    # property below). You can then associate other Entities (eg: a battery
    # sensor) with this device, so it shows more like a unified element in the UI.
    # For example, an associated battery sensor will be displayed in the right most
    # column in the Configuration > Devices view for a device.
    # To associate an entity with this device, the device_info must also return an
    # identical "identifiers" attribute, but not return a name attribute.
    # See the sensors.py file for the corresponding example setup.
    # Additional meta data can also be returned here, including sw_version (displayed
    # as Firmware), model and manufacturer (displayed as <model> by <manufacturer>)
    # shown on the device info screen. The Manufacturer and model also have their
    # respective columns on the Devices overview table. Note: Many of these must be
    # set when the device is first added, and they are not always automatically
    # refreshed by HA from it's internal cache.
    # For more information see:
    # https://developers.home-assistant.io/docs/device_registry_index/#device-properties
    @property
    def device_info(self) -> DeviceInfo:
        """Information about this entity/device."""
        return {
            "identifiers": {(DOMAIN, self.handler.uid)},
            # If desired, the name for the device could be different to the entity
            "name": self.handler.device_name,
            "sw_version": self.handler.softwareVersion,
            "model": self.handler.modelId,
            "manufacturer": "Orvibo",
        }

    # This is the name for this *entity*, the "name" attribute from "device_info"
    # is used as the device name for device screens in the UI. This name is used on
    # entity screens, and used to build the Entity ID that's used is automations etc.
    # @property
    # def name(self) -> str:
    #     """Return the name of the roller."""
    #     return self.handler.device_name

    # This property is important to let HA know if this entity is online or not.
    # If an entity is offline (return False), the UI will refelect this.
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True


class EntityUpdater:
    """Homemate entities updater."""

    def __init__(self, data_queue, add_entities, entity_class):
        """Initiate entity updater."""
        _LOGGER.debug("Homemate entity updater initialization")
        self.dataqueue = data_queue
        self.add_entities = add_entities
        self.entities = {}
        self.entity_class = entity_class
        _LOGGER.debug("Homemate entity updater initialized")

    async def async_run(self, hass):
        """Entities updater loop."""
        _LOGGER.debug("Homemate entity updater loop started!")
        while True:
            try:
                handler: HomemateTCPHandler = await asyncio.wait_for(
                    self.dataqueue.get(), 1
                )
                if handler is None:
                    _LOGGER.debug("Entities updater loop stopped")
                    return True
                if handler.uid in self.entities:
                    self.entities[handler.uid].update_handler(handler)
                else:
                    entity = self.entity_class(handler)
                    self.add_entities([entity])
                    self.entities[handler.uid] = entity
                self.dataqueue.task_done()
            except asyncio.TimeoutError:
                pass
