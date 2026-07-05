"""Generate a Google Calendar-subscribable .ics feed of Pokemon GO events.

Data source: ScrapedDuck (https://github.com/bigfoott/ScrapedDuck), which
scrapes LeekDuck event listings. Stdlib only by design - see the spec in
docs/superpowers/specs/.
"""

import json
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

EVENTS_URL = "https://raw.githubusercontent.com/bigfoott/ScrapedDuck/data/events.min.json"
REPO_ROOT = Path(__file__).parent
