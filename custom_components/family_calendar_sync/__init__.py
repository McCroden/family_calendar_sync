"""Family Calendar Sync integration."""

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .calendar_sync import sync_family_calendar
from .const import DOMAIN, SERVICE_SYNC

_LOGGER = logging.getLogger(__name__)


# Schema for the "options" section
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional("days_to_sync", default=7): cv.positive_int,
        vol.Optional("ignore_event_if_title_starts_with", default=""): cv.string,
    }
)

# Schema for each entry in the "parent" list.
PARENT_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
    }
)
COPY_ALL_FROM_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
    }
)
# Schema for each entry in the "child" list.
CHILD_SCHEMA = vol.Schema(
    {
        # "name" is optional for some child entries.
        vol.Required("entity_id"): cv.entity_id,
        vol.Required("keywords"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("copy_all_from"): COPY_ALL_FROM_SCHEMA,
    }
)

# Schema for the entire "family_calendar_sync" configuration.
FAMILY_CALENDAR_SYNC_SCHEMA = vol.Schema(
    {
        vol.Optional("options"): OPTIONS_SCHEMA,
        vol.Required("parent"): vol.All(cv.ensure_list, [PARENT_SCHEMA]),
        vol.Required("child"): vol.All(cv.ensure_list, [CHILD_SCHEMA]),
    }
)

# If this is the entire configuration file, you could wrap it as follows:
CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required("family_calendar_sync"): FAMILY_CALENDAR_SYNC_SCHEMA,
    },
    extra=vol.ALLOW_EXTRA,
)


# async def async_setup(hass: HomeAssistant, config: dict):
#     domain_config = config.get("family_calendar_sync")
#     if domain_config is None:
#         _LOGGER.warning("No config data found for family_calendar_sync service")
#         return True
#     await sync_family_calendar(
#         hass=hass,
#         config=domain_config,
#     )
#     hass.services.async_register(
#         DOMAIN, SERVICE_SYNC, sync_family_calendar, schema=vol.Schema({})
#     )
#     return True


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the Family Calendar Sync integration."""

    domain_config = config.get("family_calendar_sync")

    if domain_config is None:
        _LOGGER.warning("No config data found for family_calendar_sync service")
        return True

    # Optionally, run the sync on startup
    await sync_family_calendar(hass=hass, config=domain_config)

    # Define a service handler that wraps sync_family_calendar
    async def handle_sync_service(call):
        await sync_family_calendar(hass=hass, config=domain_config)

    # Register the service with the new handler
    hass.services.async_register(
        DOMAIN, SERVICE_SYNC, handle_sync_service, schema=vol.Schema({})
    )

    return True
