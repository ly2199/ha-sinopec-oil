"""Text entity of the built-in refuel form (note)."""
from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .button import SIGNAL_FORM_SUBMITTED
from .coordinator import SinopecOilRuntimeData
from .form import claim_form_platform, form_device, get_form_state


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the form text entity (only once across entries)."""
    if not claim_form_platform(hass, entry.entry_id, "text"):
        return
    runtime: SinopecOilRuntimeData = entry.runtime_data
    async_add_entities([NoteText(runtime)])


class NoteText(CoordinatorEntity, TextEntity):
    """备注。"""

    _attr_has_entity_name = True
    _attr_name = "备注"
    _attr_icon = "mdi:note-text"
    _attr_native_max = 255
    _attr_unique_id = "refuel_form_note"

    def __init__(self, runtime: SinopecOilRuntimeData) -> None:
        """Initialize."""
        super().__init__(runtime.refuel_coordinator)
        self._attr_device_info = form_device()

    async def async_added_to_hass(self) -> None:
        """Clear when the form resets."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_FORM_SUBMITTED, self._refresh
            )
        )

    async def _refresh(self, *_args) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return get_form_state(self.hass).note or None

    async def async_set_value(self, value: str) -> None:
        """Handle user input."""
        get_form_state(self.hass).note = value
        self.async_write_ha_state()
