"""Datetime entity of the built-in refuel form (refuel time)."""
from __future__ import annotations

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .button import SIGNAL_FORM_SUBMITTED
from .coordinator import SinopecOilRuntimeData
from .form import form_device, get_form_state


async def async_setup_entry(hass, entry, async_add_entities: AddEntitiesCallback):
    """Set up the form datetime entity (only once across entries)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("form_created"):
        return
    domain_data["form_created"] = True
    runtime: SinopecOilRuntimeData = entry.runtime_data
    async_add_entities([RefuelDatetime(hass, runtime)])


class RefuelDatetime(CoordinatorEntity, DateTimeEntity):
    """加油时间（默认当前，可改为历史时间以匹配历史油价）。"""

    _attr_has_entity_name = True
    _attr_name = "加油时间"
    _attr_icon = "mdi:calendar-clock"
    _attr_unique_id = "refuel_form_datetime"

    def __init__(self, hass: HomeAssistant, runtime: SinopecOilRuntimeData) -> None:
        """Initialize."""
        super().__init__(runtime.refuel_coordinator)
        self.hass = hass
        self._runtime = runtime
        self._attr_device_info = form_device()

    async def async_added_to_hass(self) -> None:
        """Reset to now when the form resets."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_FORM_SUBMITTED, self._refresh
            )
        )

    async def _refresh(self, *_args) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self):
        return get_form_state(self.hass).when

    async def async_set_value(self, value) -> None:
        """Handle user input."""
        get_form_state(self.hass).when = value or dt_util.now()
        self.async_write_ha_state()
