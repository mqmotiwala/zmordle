"""
Wordle head-to-head parser.

Parses a WhatsApp 'Export chat' .txt dump into per-(puzzle, player) results.

The puzzle number is the join key, NOT the date. Archive plays
(e.g. "Wordle 1,793 ...") are paired by puzzle number, so a live play and an
archive play of the same puzzle compare correctly.

Scoring rule (applied downstream, in the analytics Lambda):
  - guess count 1-6 from "Wordle N X/6"
  - X/6 (fail) scored as 7 (loses to any 1-6, ties another fail)
  - lower guess count wins; equal = tie
  - a puzzle only counts head-to-head if BOTH players have an entry
"""

import re
from datetime import datetime
from collections import namedtuple

# --- configuration: map WhatsApp sender names to short player ids ----------
SENDER_TO_PLAYER = {
    "Mufaddal Motiwala": "mufi",
    "Zahra Babarwala": "zahra",
}

FAIL_SCORE = 7  # X/6 treated as 7 guesses for comparison

# Line that begins a new message: "M/D/YY, H:MM AM/PM - Sender: text"
# Captures the timestamp, sender, and body.
MSG_RE = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4}, \d{1,2}:\d{2}\s?[AP]M) - ([^:]+?): (.*)$"
)

# A Wordle result token, anywhere in a line: "Wordle 1,790 4/6" or "... X/6"
RESULT_RE = re.compile(r"Wordle\s+([\d,]+)\s+([1-6X])/6", re.IGNORECASE)

# WhatsApp timestamp formats vary by locale; try the common US-style ones.
_TS_FORMATS = (
    "%m/%d/%y, %I:%M %p",
    "%m/%d/%Y, %I:%M %p",
    "%m/%d/%y, %I:%M%p",
    "%m/%d/%Y, %I:%M%p",
)

Result = namedtuple(
    "Result", ["puzzle", "player", "guesses", "is_fail", "raw", "reported_at"]
)


def _parse_timestamp(ts):
    """Parse a WhatsApp timestamp string into an ISO date (YYYY-MM-DD), or None."""
    ts = ts.strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(ts, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_chat(text):
    """
    Parse raw chat text into a dict: (puzzle, player) -> Result.

    Last-write-wins on duplicate (puzzle, player). Conflicting duplicates
    (same key, different guess count) are returned separately for inspection.
    """
    results = {}
    conflicts = []
    current_player = None   # player whose message we are currently inside
    current_date = None     # reported date (ISO) of the current message

    for line in text.splitlines():
        m = MSG_RE.match(line)
        if m:
            ts, sender, body = m.group(1), m.group(2).strip(), m.group(3)
            current_player = SENDER_TO_PLAYER.get(sender)  # None if unknown
            current_date = _parse_timestamp(ts)
            scan_text = body
        else:
            # continuation line of the current message (no date prefix)
            scan_text = line

        if current_player is None:
            continue  # message from someone we don't track / system line

        rm = RESULT_RE.search(scan_text)
        if not rm:
            continue

        puzzle = int(rm.group(1).replace(",", ""))
        gchar = rm.group(2).upper()
        is_fail = gchar == "X"
        guesses = FAIL_SCORE if is_fail else int(gchar)

        key = (puzzle, current_player)
        new = Result(
            puzzle, current_player, guesses, is_fail,
            scan_text.strip(), current_date
        )

        if key in results and results[key].guesses != guesses:
            conflicts.append((results[key], new))
        results[key] = new  # last write wins

    return results, conflicts
