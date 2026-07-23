import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN

class PulseProConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Automate Pulse PRO."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step where the user enters connection details."""
        errors = {}
        if user_input is not None:
            # Create the integration entry in the UI database
            return self.async_create_entry(
                title=f"Pulse PRO ({user_input['host']})", 
                data=user_input
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("host", default="192.168.1.21"): str,
                vol.Required("port", default=1487): int,
            }),
            errors=errors,
        )