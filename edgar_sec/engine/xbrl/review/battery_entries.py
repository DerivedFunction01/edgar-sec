"""The battery entry set, composed from its per-tier entry modules.

Every entry's expected value was verified against its filing — by fact
name and extracted facts where unambiguous, otherwise rendered text.
"""

from __future__ import annotations

from edgar_sec.engine.xbrl.review.battery_entries_basic import BASIC_SET
from edgar_sec.engine.xbrl.review.battery_entries_complex import COMPLEX_SET
from edgar_sec.engine.xbrl.review.battery_entries_textbook import TEXTBOOK_SET
from edgar_sec.engine.xbrl.review.battery_entry import BatteryEntry

BATTERY_SET: tuple[BatteryEntry, ...] = BASIC_SET + TEXTBOOK_SET + COMPLEX_SET
