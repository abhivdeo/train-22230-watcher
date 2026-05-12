"""
Configuration. Edit only this file to change train/date/route/class.
"""

# --- WHAT TO WATCH --------------------------------------------------------
TRAIN_NUMBER = "22230"           # CSMT Vande Bharat
SOURCE_NAME = "MADGAON - MAO"    # Type-ahead text used on IRCTC
SOURCE_CODE = "MAO"
DEST_NAME = "THANE - TNA"        # Type-ahead text used on IRCTC
DEST_CODE = "TNA"
JOURNEY_DATE_DDMMYYYY = "16/06/2026"  # IRCTC display format
JOURNEY_DATE_ISO = "2026-06-16"       # ISO for fallback APIs
TRAVEL_CLASS_CODE = "EC"         # EC = Exec Chair Car
TRAVEL_CLASS_LABEL = "Exec. Chair Car (EC)"
QUOTA_CODE = "GN"
QUOTA_LABEL = "GENERAL"

# --- BEHAVIOUR ------------------------------------------------------------
# Headless run timing (seconds)
PAGE_LOAD_TIMEOUT = 120
ACTION_TIMEOUT = 30

# Where state is stored
STATE_FILE = ".state.json"

# Where screenshots are written (Actions uploads as artifact)
SCREENSHOT_DIR = "screenshots"
