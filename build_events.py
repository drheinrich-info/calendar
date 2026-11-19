#!/usr/bin/env python3
"""
Build events.json from a Google Calendar iCal (ICS) feed.

Usage:
    ICS_URL="https://calendar.google.com/calendar/ical/.../basic.ics" \
        python3 tools/build_events.py
    python3 tools/build_events.py /path/to/calendar.ics
    python3 tools/build_events.py https://.../basic.ics [output_path]

The source is taken from argv[1] if given, otherwise from the ICS_URL
environment variable. The source may be an http(s) URL or a local file path.
Output defaults to ./events.json (override with argv[2] or OUTPUT env var).

Output: a JSON array, sorted by start, of
    {"title", "start", "end", "location", "allDay"}
with timed values as ISO 8601 in Asia/Tokyo (+09:00). When an event's
description contains a FANY ticket URL (https://ticket.fany.lol/...),
the first such URL is added as "url"; the field is omitted otherwise.

Window: events whose start falls from 14 days before today to 150 days
after today (Asia/Tokyo) are kept.

Limitations:
  * Recurrences (RRULE) are NOT expanded. Only the first/master occurrence
    of a recurring event is emitted. icalendar alone has no recurrence
    expansion utility; add `dateutil.rrule` handling here if the source
    calendar starts using recurring events.
  * Events without DTSTART are skipped; a missing DTEND is synthesised
    (+1 hour for timed events, +1 day for all-day events).
"""

import json
import os
import re
import sys
import urllib.request
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from icalendar import Calendar

TOKYO = ZoneInfo("Asia/Tokyo")
WINDOW_BEFORE = timedelta(days=14)
WINDOW_AFTER = timedelta(days=150)
DEFAULT_TIMED_DURATION = timedelta(hours=1)

# First FANY ticket URL in an event description. The URL runs until
# whitespace or a character that commonly delimits it in Japanese text.
FANY_URL_RE = re.compile(r"https://ticket\.fany\.lol/[^\s<>\"'」）】]*")


def load_ics(source: str) -> bytes:
    if source.startswith(("http://", "https://")):
        req = urllib.request.Request(source, headers={"User-Agent": "dr-heinrich-widget/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    with open(source, "rb") as fh:
        return fh.read()


def to_tokyo(value):
    """Convert an iCal DTSTART/DTEND value to (aware datetime in Tokyo, all_day)."""
    # All-day events come through as datetime.date (not datetime).
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, time.min, tzinfo=TOKYO), True
    if value.tzinfo is None:
        # Floating time: the source calendar is a Tokyo calendar, so
        # interpret naive datetimes as Asia/Tokyo local time.
        return value.replace(tzinfo=TOKYO), False
    return value.astimezone(TOKYO), False


def main(argv):
    source = argv[1] if len(argv) > 1 else os.environ.get("ICS_URL", "")
    if not source:
        print("error: no ICS source (pass a path/URL argument or set ICS_URL)", file=sys.stderr)
        return 2
    output = argv[2] if len(argv) > 2 else os.environ.get("OUTPUT", "events.json")

    today_tokyo = datetime.now(TOKYO).date()
    window_start = datetime.combine(today_tokyo - WINDOW_BEFORE, time.min, tzinfo=TOKYO)
    window_end = datetime.combine(today_tokyo + WINDOW_AFTER, time.max, tzinfo=TOKYO)

    cal = Calendar.from_ical(load_ics(source))

    events = []
    for component in cal.walk("VEVENT"):
        raw_start = component.get("DTSTART")
        if raw_start is None:
            continue
        start, all_day = to_tokyo(raw_start.dt)

        raw_end = component.get("DTEND")
        if raw_end is not None:
            end, _ = to_tokyo(raw_end.dt)
        elif all_day:
            end = start + timedelta(days=1)
        else:
            end = start + DEFAULT_TIMED_DURATION

        if not (window_start <= start <= window_end):
            continue

        event = {
            "title": str(component.get("SUMMARY", "")).strip(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "location": str(component.get("LOCATION", "")).strip(),
            "allDay": all_day,
        }

        # Link target for the SCHEDULE list: the first FANY ticket URL
        # found in the description, if any.
        description = str(component.get("DESCRIPTION", ""))
        match = FANY_URL_RE.search(description)
        if match:
            event["url"] = match.group(0)

        events.append(event)

    events.sort(key=lambda e: (e["start"], e["title"]))

    with open(output, "w", encoding="utf-8") as fh:
        json.dump(events, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(f"wrote {len(events)} events to {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
