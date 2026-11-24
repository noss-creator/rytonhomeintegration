"""Constants for Ryton Home Automations."""

DOMAIN = "ryton_home_automations"

# A schedule file in Home Assistant's configuration folder, in the format of
# SCHEDULE_FORMAT.md. This is the way in for a house with no internet.
DEFAULT_SCHEDULE_FILE = "ryton_schedule.json"

# Where houses fetch their schedule. The publishable key is meant to be
# shipped: on its own it reaches nothing but the five house functions, and
# each of those needs the house's own key. No secret key ever belongs here.
WEBSITE_URL = "https://qdaslreocgcfnpdcthdu.supabase.co"
WEBSITE_PUBLISHABLE_KEY = "sb_publishable_67DMd_cFyWxFEoe9tvtneA_UxGIEGlB"

# What the house keeps from pairing, in its config entry.
CONF_HOUSE_ID = "house_id"
CONF_HOUSE_NAME = "house_name"
CONF_HOUSE_KEY = "house_key"
CONF_PAIRING_CODE = "pairing_code"

SYNC_MINUTES = 15
