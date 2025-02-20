"""Module to handle syncing between the local calendar and CalDAV calendar."""

from dataclasses import dataclass, asdict
import datetime
from datetime import datetime, timedelta
from hashlib import sha256
import logging
import re

from homeassistant.components.calendar import CalendarEntity
from homeassistant.core import HomeAssistant

from .const import DEFAULT_DAYS_TO_SYNC, HASH_LENGTH

HASH_REGEX = re.compile(r"\[([a-z0-9]{8})\]", re.IGNORECASE)

_LOGGER = logging.getLogger(__name__)


@dataclass
class SyncDateRange:
    """A dataclass for start and end dates for syncing."""

    start: datetime
    days_to_sync: int

    @property
    def end(self) -> datetime:
        """Return the end datetime."""
        return self.start + timedelta(days=self.days_to_sync)


class Event:
    """An event class to assist in managing dependent events."""

    def __init__(self, data: dict) -> None:
        """Initialize event object.

        Args:
            data (dict): event data from home assistant service call

        """
        if not isinstance(data, dict):
            raise TypeError(data)
        self._data: dict = data
        self._hashed_value: str | None = None
        self._summary: str | None = None
        self._description: str | None = None
        self._location: str | None = None
        self._start_date: str | None = None
        self._end_date: str | None = None
        self._start_date_time: str | None = None
        self._end_date_time: str | None = None
        self._uid: str | None = None
        self._rrule: str | None = None
        self._recurrence_id: str | None = None
        self._set_hashed_value()

    def add_hash_to_description(
        self,
        description: str | None,
        hashed_value: str,
    ) -> str | None:
        """Modify description by adding hashed value to it."""
        hashed_description = None
        if description:
            hashed_description = f"{description} \n[{hashed_value}]"
        else:
            hashed_description = f"[{hashed_value}]"

        return hashed_description

    def get_data_for_event_creation(self) -> dict:
        """Get event data in the format to create a new HA event."""
        data = {}
        if self.is_all_day:
            data["start_date"] = self.start
            data["end_date"] = self.end
        else:
            data["start_date_time"] = self.start
            data["end_date_time"] = self.end
        data["summary"] = self.title
        data["description"] = self.add_hash_to_description(
            description=self.description,
            hashed_value=self.hashed_value,
        )
        if self.location is not None:
            data["location"] = self.location
        return data

    @property
    def is_all_day(self) -> bool:
        """Is event an all day event."""
        return not isinstance(self.data["start"], datetime)

    @property
    def hashed_value(self) -> str:
        """Return the hashed value of the event."""
        return self._hashed_value

    @property
    def data(self) -> dict:
        """Return the event data."""
        return self._data

    @property
    def title(self) -> str | None:
        """Return the event's title aka summary."""
        return self._data.get("summary", None)

    @property
    def description(self) -> str | None:
        """Return the event's description."""
        return self._data.get("description", None)

    @description.setter
    def description(self, value) -> None:
        self._description = value

    @property
    def location(self) -> str | None:
        """Return the event's location."""
        return self._data.get("location", None)

    @property
    def start(self) -> str | None:
        """Return the event's start date or datetime."""
        return self._data.get("start", None)

    @property
    def end(self) -> str | None:
        """Return the event's end date or datetime."""
        return self._data.get("end", None)

    @property
    def start_date_time(self) -> str | None:
        """Return the event's start date time only, if applicable."""
        if self.is_all_day:
            return None
        return self.start

    @property
    def end_date_time(self) -> str | None:
        """Return the event's end date time only, if applicable."""
        if self.is_all_day:
            return None
        return self.end

    @property
    def start_date(self) -> str | None:
        """Return the event's start date only, if applicable."""
        if self.is_all_day:
            return self.start
        return None

    @property
    def end_date(self) -> str | None:
        """Return the event's end date only, if applicable."""
        if self.is_all_day:
            return self.end
        return None

    @property
    def uid(self) -> str | None:
        """Return the event's uid."""
        return self.data["uid"]

    @uid.setter
    def uid(self, value) -> None:
        """Set the event's uid."""
        self._data["uid"] = value

    @property
    def rrule(self) -> str | None:
        """Return the event's rrule."""
        return self.data["rrule"]

    @property
    def recurrence_id(self) -> str | None:
        """Return the event's recurrence id."""
        return self.data["recurrence_id"]

    def _set_hashed_value(self) -> None:
        raise NotImplementedError


class ChildEvent(Event):
    """Event for a Child calendar."""

    def _set_hashed_value(self) -> str | None:
        """Extract the hashed_value from the event description field. None, if not found."""
        hashed_value = None
        if description := self.description:
            if match := HASH_REGEX.match(description):
                hashed_value = match.group(1)
        self._hashed_value = hashed_value


class ParentEvent(Event):
    """Event for a Parent calendar."""

    def create_child_event(self) -> ChildEvent:
        """Create a `ChildEvent` from the event data."""
        child_data = self.get_data_for_child_event()
        child_event = ChildEvent(child_data)
        # add hash to description
        if description := child_event.description:
            child_event.description = description + f" [{self.hashed_value}]"
        else:
            child_event.description = f" [{self.hashed_value}]"
        return child_event

    def _set_hashed_value(self):
        """Calculate the hashed value of the event data."""
        data = f"{self.data}".encode()
        hashed_value = sha256(data).hexdigest()
        self._hashed_value = hashed_value[:HASH_LENGTH]

    def get_data_for_child_event(self) -> dict:
        """Create a dict of data for use in ChildEvent creation."""
        event_data: dict = {}
        event_data["start"] = self.start
        event_data["end"] = self.end
        event_data["summary"] = self.title
        if description := self.description:
            # append the hashed_value to the description, which is where we will look for
            # the hashed value when attempting to sync events
            hashed_description = f"{description} [{self.hashed_value}]"
            event_data["description"] = hashed_description
        else:
            event_data["description"] = f"[{self.hashed_value}]"

        if location := self.location:
            event_data["location"] = location
        return event_data


class Calendar:
    """Calendar object to manage Events."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        sync_date_range: SyncDateRange,
        cal_type: str,
    ) -> None:
        """Initialize Calendar object."""
        self._hass = hass
        self._entity_id = entity_id
        self._sync_date_range = sync_date_range
        self._type = cal_type
        self._events: list[Event] = []
        self._hash_map = {}
        self._entity: CalendarEntity = hass.data.get("calendar").get_entity(
            self.entity_id
        )

    async def async_setup(self) -> None:
        """Set up async stuff."""
        if self.entity:
            await self.async_load_events()
        else:
            _LOGGER.error("Could not load Entity for %s", self.entity_id)

    @property
    def entity(self) -> CalendarEntity:
        """Return the entity."""
        return self._entity

    @property
    def events(self) -> list[Event]:
        """Return the events."""
        return self._events

    @events.setter
    def events(self, value: list[Event]):
        self._events = value

    @property
    def hash_map(self) -> dict:
        """Return the hash map."""
        return self._hash_map

    @property
    def entity_id(self) -> str:
        """Return the entity_id."""
        return self._entity_id

    @property
    def type(self) -> str:
        """Return the calendar type."""
        return self._type

    @property
    def hash_set(self) -> set[str]:
        """Return the hashes."""
        return set(self.hash_map.keys())

    def remove_events_to_ignore(self) -> None:
        """Remove events from that need to be ignored."""
        raise NotImplementedError

    async def async_load_events(self):
        """Get events using hass object and load into calendar object."""
        cal = self._hass.data.get("calendar").get_entity(self.entity_id)
        if cal:
            # TODO: fix case where caldav entities report an ongoing event in get events
            # but local calendar entities do not.
            events_data = await cal.async_get_events(
                self._hass,
                self._sync_date_range.start,
                self._sync_date_range.end,
            )
            for event_data in events_data:
                event = None
                if self.type == "parent":
                    event = ParentEvent(asdict(event_data))
                else:
                    event = ChildEvent(asdict(event_data))
                self._events.append(event)

        if self.type == "parent":
            self.remove_events_to_ignore()
        self._create_hash_map()
        return True

    def _create_hash_map(self):
        for event in self.events:
            # not all events will have hashes
            # ex: events created manually in local cal
            if (hashed_value := event.hashed_value) is not None:
                self.hash_map[hashed_value] = event

    def get_event_with_hash(self, hashed_value: str) -> Event | None:
        """Get the Event with the corresponding hash, if any."""
        return self.hash_map.get(hashed_value, None)

    def is_event_in_calendar_with_hash(self, hashed_value: str) -> bool:
        """Indicate if event with hash is already in calendar."""
        return self.get_event_with_hash(hashed_value=hashed_value) is not None


class ParentCalendar(Calendar):
    """Parent calendar class."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        sync_date_range: SyncDateRange,
        ignore_string: str | None = None,
    ) -> None:
        """Initialize ParentCalendar object."""
        super().__init__(
            hass=hass,
            entity_id=entity_id,
            sync_date_range=sync_date_range,
            cal_type="parent",
        )
        self._ignore_string = ignore_string

    def remove_events_to_ignore(self) -> None:
        """Remove events whose title starts with the string we are to ignore."""
        self.events = [
            event
            for event in self.events
            if not event.title.startswith(self._ignore_string)
        ]


class ChildCalendar(Calendar):
    """Child calendar class."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        sync_date_range: SyncDateRange,
        keywords: list[str],
    ) -> None:
        """Initialize ChildCalendar object."""
        super().__init__(
            hass=hass,
            entity_id=entity_id,
            sync_date_range=sync_date_range,
            cal_type="child",
        )
        self._keywords = keywords
        reg_string = r"\b(" + f"{'|'.join(keywords)}" + r")\b"
        self._regex_pattern = re.compile(reg_string, re.IGNORECASE | re.MULTILINE)

    @property
    def keywords(self) -> list[str]:
        """Return the keywods."""
        return self._keywords

    def is_a_keyword_match(self, title: str) -> bool:
        """Determine if a keyword is found in `title`."""
        return bool(self._regex_pattern.search(title))

    async def _async_delete_event_from_ha(self, hashed_value: str):
        """Delete the child event from home assistant with matching `hashed_value`."""
        event = self.get_event_with_hash(hashed_value=hashed_value)
        await self.entity.async_delete_event(event.uid)

    async def async_delete_event_from_ha(self, values: str | set[str]):
        """Delete the child event from home assistant with matching `hashed_value`."""
        if isinstance(values, set):
            values_to_remove = self.overlapping_hashes(values)
            for value in values_to_remove:
                await self._async_delete_event_from_ha(hashed_value=value)
        elif isinstance(values, str):
            if values in self.hash_set:
                await self._async_delete_event_from_ha(hashed_value=values)
        else:
            raise TypeError

    async def _async_add_event_to_ha(self, event: ParentEvent) -> None:
        """Add the `ParentEvent` to the `ChildCalendar` in HA."""
        _LOGGER.debug(event.get_data_for_event_creation())
        # await self.entity.async_create_event(event.get_data_for_event_creation())
        payload = {}
        payload = event.get_data_for_event_creation()
        payload["entity_id"] = self.entity_id
        _LOGGER.debug("about to create event with payload %s", payload)
        await self._hass.services.async_call(
            "calendar",
            "create_event",
            payload,
            blocking=True,
        )
        _LOGGER.debug("calendar event creation completed")

    async def async_add_event(self, event: ParentEvent) -> None:
        """Add the `ParentEvent` to the `ChildCalendar` in HA and in this object."""
        await self._async_add_event_to_ha(event=event)
        child_event = event.create_child_event()
        self._hash_map[child_event.hashed_value] = child_event
        self.events.append(child_event)
        _LOGGER.debug("child_event is %s", type(child_event))
        _LOGGER.debug(child_event)
        if not self.hash_map.get(child_event.hashed_value, None):
            _LOGGER.error(
                "Something went wrong. Attempt to add event to child calendar when it already exists"
            )
        # self.hash_map[child_event.hashed_value] = child_event
        # self.events.append(child_event)

    def overlapping_hashes(self, hashed_values: list[str]) -> list[str]:
        """Return list of hashed_values if they exist for this calendar."""
        return [
            hashed_value
            for hashed_value in hashed_values
            if hashed_value in self.hash_set
        ]


class SyncWorker:
    """Sync events from parent calendar to child calendar."""

    def __init__(self, hass: HomeAssistant, config: dict) -> None:
        """Initialize SyncWorker."""
        self._hass = hass
        self._config = config
        self._copy_all_map: dict = {}

        options = self._config.get("options", None)
        if options:
            days_to_sync = options.get("days_to_sync", DEFAULT_DAYS_TO_SYNC)
            self._ignore_event_if_title_starts_with = options.get(
                "ignore_event_if_title_starts_with", None
            )
        else:
            days_to_sync = DEFAULT_DAYS_TO_SYNC
            self._ignore_event_if_title_starts_with = None

        self._sync_date_range = SyncDateRange(
            start=datetime.now().astimezone(),
            days_to_sync=days_to_sync,
        )

        self._calendars: dict[str, list[Calendar]] = {"parent": [], "child": []}

    @property
    def config(self) -> dict:
        """Return the config."""
        return self._config

    @property
    def calendars(self) -> dict[str, list[Calendar]]:
        """Return the calendars."""
        return self._calendars

    @property
    def num_of_parent_calendars(self) -> int:
        """Return the number of parent calendars."""
        return len(self.calendars["parent"])

    @property
    def num_of_child_calendars(self) -> int:
        """Return the number of child calendars."""
        return len(self.calendars["child"])

    async def async_setup(self) -> None:
        """Set up async stuff."""
        # parse the parent calendars first
        if parent_cals := self.config["parent"]:
            for cal_config in parent_cals:
                entity_id = cal_config["entity_id"]
                calendar = ParentCalendar(
                    hass=self._hass,
                    entity_id=entity_id,
                    sync_date_range=self._sync_date_range,
                    ignore_string=self._ignore_event_if_title_starts_with,
                )
                await calendar.async_setup()
                self.calendars["parent"].append(calendar)

        if child_cals := self.config["child"]:
            for cal_config in child_cals:
                if copy_all_from := cal_config.get("copy_all_from", None):
                    self._copy_all_map[cal_config["entity_id"]] = copy_all_from[
                        "entity_id"
                    ]
                entity_id = cal_config["entity_id"]
                keywords = cal_config["keywords"]
                calendar = ChildCalendar(
                    hass=self._hass,
                    entity_id=entity_id,
                    sync_date_range=self._sync_date_range,
                    keywords=keywords,
                )
                await calendar.async_setup()
                self.calendars["child"].append(calendar)

        num_parent_cals = self.num_of_parent_calendars
        num_child_cals = self.num_of_child_calendars
        if (num_parent_cals == 0) or (num_child_cals == 0):
            msg = "There need to be >0 for each parent and child cals."
            msg += f"But got {num_parent_cals} parent, {num_child_cals} child."
            _LOGGER.error(msg)

    def _set_of_hashes_by_cal_type(self, cal_type: str) -> set:
        result = set()
        for cal in self.calendars[cal_type]:
            result.update(cal.hash_set)
        return result

    async def _async_remove_events_from_child_cals(self, event_hashes: list):
        """Remove events from child calendars."""
        for cal in self.calendars["child"]:
            await cal.async_delete_event_from_ha(event_hashes)

    async def _async_sync_parent_to_child(
        self, parent_cal: ParentCalendar, child_cal: ChildCalendar
    ):
        should_add_all_events: bool = (
            self._copy_all_map.get(child_cal.entity_id, None) == parent_cal.entity_id
        )
        for parent_event in parent_cal.events:
            if (
                child_cal.is_a_keyword_match(parent_event.title)
                or should_add_all_events
            ):
                # make sure the event doesn't already exist in child calendar
                if not child_cal.is_event_in_calendar_with_hash(
                    parent_event.hashed_value
                ):
                    await child_cal.async_add_event(parent_event)

    async def async_sync_calendars(self) -> None:
        """Sync ParentCalendar events to ChildCalenders."""
        # compare hashes
        parentset = self._set_of_hashes_by_cal_type("parent")
        childset = self._set_of_hashes_by_cal_type("child")
        need_removed = childset - parentset
        # need_added = parentset - childset
        # TODO: Need to reparse all events in case config has changed.
        # Can a previous config be saved to do a diff against?
        # TODO: getting events that already started are not returned
        # Need to figure out how to get events that are already started or
        # they get duplicated on the child calendar.
        await self._async_remove_events_from_child_cals(need_removed)
        for parent_cal in self.calendars["parent"]:
            for child_cal in self.calendars["child"]:
                await self._async_sync_parent_to_child(parent_cal, child_cal)


async def sync_family_calendar(hass: HomeAssistant, config: dict):
    """Sync the parent calendar events to child calendars based on criteria."""
    worker = SyncWorker(hass, config)
    await worker.async_setup()
    await worker.async_sync_calendars()
