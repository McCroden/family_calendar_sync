"""Family Calendar Sync integration."""

import logging

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir

from .calendar_sync import sync_family_calendar
from .const import (
    DOMAIN,
    SERVICE_SYNC,
    DEPRECATED_COPY_ALL_FROM_MAP_REMOVAL,
)

_LOGGER = logging.getLogger(__name__)

LEGACY_COPY_ALL_FROM_USED = False


class CopyAllFromList(list):
    """List subclass to mark deprecated map-based copy_all_from entries."""

    def __init__(self, iterable=(), deprecated: bool = False) -> None:
        super().__init__(iterable)
        # True when the user is still using the legacy map format:
        # copy_all_from:
        #   entity_id: calendar.parent
        self.deprecated = deprecated


def _normalize_copy_all_from(value):
    """Normalize copy_all_from to a list of entity_ids.

    Supports:

    Legacy (map):
      copy_all_from:
        entity_id: calendar.napoleon_dynamite

    New (list of strings):
      copy_all_from:
        - calendar.napoleon_dynamite
        - calendar.nomi_malone
    """
    global LEGACY_COPY_ALL_FROM_USED

    # Legacy map style
    if isinstance(value, dict):
        LEGACY_COPY_ALL_FROM_USED = True
        value = value.get("entity_id")

    # Accept a single string or a list; make sure we always end up with a list
    as_list = cv.ensure_list(value)
    return as_list


# Schema for the "options" section
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Optional("days_to_sync", default=7): cv.positive_int,
        vol.Optional("days_to_sync_past", default=0): cv.positive_int,
        vol.Optional("ignore_event_if_title_starts_with", default=""): cv.string,
    }
)

# Schema for each entry in the "parent" list.
PARENT_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
    }
)

#   - legacy map: { entity_id: "calendar.parent" }
#   - new list: ["calendar.parent1", "calendar.parent2"]
COPY_ALL_FROM_SCHEMA = vol.All(
    _normalize_copy_all_from,
    [cv.entity_id],
)
# Schema for each entry in the "child" list.
CHILD_SCHEMA = vol.Schema(
    {
        # "name" is optional for some child entries.
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("keywords", default=[]): vol.All(cv.ensure_list, [cv.string]),
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


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Family Calendar Sync integration."""

    domain_config = config.get("family_calendar_sync")

    if domain_config is None:
        _LOGGER.warning("No config data found for family_calendar_sync service")
        return True

    # Detect legacy map-based copy_all_from usage and create a Repairs issue
    if LEGACY_COPY_ALL_FROM_USED:
        ir.async_create_issue(
            hass,
            DOMAIN,
            "copy_all_from_map_deprecated",
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            breaks_in_ha_version=DEPRECATED_COPY_ALL_FROM_MAP_REMOVAL,
            translation_key="copy_all_from_map_deprecated",
            learn_more_url="https://github.com/McCroden/family_calendar_sync#migrating-copy_all_from",
        )

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
