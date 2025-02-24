
from homeassistant.helpers.entity import Entity

import logging

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class ResidentBedEntity(Entity):
    """Resident bed entity."""

    _attr_has_entity_name = True

    def __init__(self, device_address):
        self.device_address = device_address
