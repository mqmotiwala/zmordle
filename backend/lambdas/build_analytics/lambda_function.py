"""
build-analytics-wordle-scoreboard

Scans the results table and produces a single, UI-friendly analytics JSON object
in S3 (analytics/scoreboard.json). Invoked asynchronously by the update-scores
Lambda after every export is processed.

Computes:
  - head-to-head summary (W/L/T over puzzles BOTH players completed)
  - cumulative-wins series per player (for the running score plot)
  - per-puzzle table
  - freshness info (latest reported puzzle + date + days ago)
"""

import os
import json
import boto3
import logging
from datetime import date, datetime, timezone

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")

TABLE_NAME = os.environ.get("RESULTS_TABLE", "results-wordle-scoreboard")
BUCKET = os.environ.get("BUCKET", "aws-wordle-scoreboard")
ANALYTICS_KEY = os.environ.get("ANALYTICS_KEY", "analytics/scoreboard.json")

# player id -> WhatsApp display name (keep in sync with the parser's SENDER_TO_PLAYER)
PLAYER_DISPLAY = {
    "mufi": "Mufaddal Motiwala",
    "zahra": "Zahra Babarwala",
}
PLAYERS = sorted(PLAYER_DISPLAY)  # ['mufi', 'zahra']

# Short names used in the shareable summary. Keep in sync with PLAYER_DISPLAY in
# ui/config.py, since the app renders the summary text this Lambda produces.
PLAYER_SHORT = {
    "mufi": "Mufaddal",
    "zahra": "Zahra",
}

# Keep in sync with APP_TITLE in ui/config.py; both surface in the summary and
# the app header.
APP_NAME = "zmordle"
APP_URL = "https://zmordle.up.railway.app/"


def _scan_all(table):
    items = []
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _disp(guesses, is_fail):
    return "X" if is_fail else str(int(guesses))


def _has(item, player):
    return f"{player}_guesses" in item and item.get(f"{player}_guesses") is not None


# --- streaks -----------------------------------------------------------------
def _head_to_head(rows, player_order):
    """
    Keep only the games both players have played, ordered oldest -> newest.

    Ordering is by puzzle number, so this is a sequence of games rather than of
    dates - calendar gaps between puzzles carry no meaning here.
    """
    p1, p2 = player_order
    games = [r for r in rows if r.get(p1) is not None and r.get(p2) is not None]
    return sorted(games, key=lambda r: int(r["puzzle"]))


def _streaks(rows, player_order):
    """
    Measure win streaks in games, walking head-to-head puzzles oldest -> newest.

    Streaks are counted per game, never per date. A streak only advances on a
    puzzle both players finished, so a puzzle only one of them played is skipped
    over rather than treated as a break - as are any calendar gaps between
    puzzles. Ordering comes from the puzzle number; dates never enter into it.

    A tie ends a streak.

    Each run is reported with the puzzle it started and ended on. Where a player
    has several runs of their best length, the earliest one is kept - that's the
    run that set the record.

    Returns a dict with:
      longest -> {"length": int, "runs": [run, ...]} or None, where runs holds
                 one entry per player level on that length
      current -> the run still alive, or None
      last_winner -> winner of the most recent head-to-head puzzle, or None

    A run is {"player": id, "length": int, "start": puzzle, "end": puzzle}.
    """
    best = {p: None for p in player_order}  # each player's record run
    run_player, run_len, run_start, run_end = None, 0, None, None
    last_winner = None

    for row in _head_to_head(rows, player_order):
        puzzle = int(row["puzzle"])
        winner = row.get("winner")
        last_winner = winner

        if winner in best:
            if winner == run_player:
                run_len += 1
            else:
                run_player, run_len, run_start = winner, 1, puzzle
            run_end = puzzle

            # strictly greater, so a later run of equal length doesn't displace
            # the one that set the record
            if best[winner] is None or run_len > best[winner]["length"]:
                best[winner] = {
                    "player": winner, "length": run_len,
                    "start": run_start, "end": run_end,
                }
        else:  # a tie (or an unrecognised winner) resets the run
            run_player, run_len, run_start, run_end = None, 0, None, None

    top = max((run["length"] for run in best.values() if run), default=0)
    longest = (
        {
            "length": top,
            "runs": [best[p] for p in player_order
                     if best[p] and best[p]["length"] == top],
        }
        if top
        else None
    )
    current = (
        {"player": run_player, "length": run_len, "start": run_start, "end": run_end}
        if run_player
        else None
    )

    return {"longest": longest, "current": current, "last_winner": last_winner}


# --- shareable summary -------------------------------------------------------
def _fmt_avg(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "—"


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _names(players):
    """Join one or more player ids into a display string."""
    return " & ".join(PLAYER_SHORT.get(p, p) for p in players)


def _streak_span(run):
    """The puzzles a run started and ended on: 'Wordle 1,866-1,868'."""
    start, end = run["start"], run["end"]
    if start == end:
        return f"Wordle {start:,}"
    return f"Wordle {start:,}-{end:,}"


def _whatsapp_summary(summary, streaks):
    """
    Build a plain-text recap of the scoreboard, ready to paste into WhatsApp.

    Uses WhatsApp's markup - *bold* for the title, _italics_ for section headers
    and the streak span - which renders as formatting once pasted into a chat.
    Built as blocks: lines inside a block sit together, and blocks are separated
    by one blank line.

    Lives here rather than in the UI so that the app, and the response the
    share-import endpoint hands back to the phone, are byte-identical.
    """
    p1, p2 = PLAYERS
    name1 = PLAYER_SHORT.get(p1, p1)
    name2 = PLAYER_SHORT.get(p2, p2)

    wins1 = summary.get(f"{p1}_wins", 0)
    wins2 = summary.get(f"{p2}_wins", 0)
    shared = summary.get("shared", 0)
    avg1 = _fmt_avg(summary.get(f"{p1}_avg_guesses"))
    avg2 = _fmt_avg(summary.get(f"{p2}_avg_guesses"))

    lead = wins1 - wins2
    if lead > 0:
        standing = f"🏆 {name1} leads by {lead}"
    elif lead < 0:
        standing = f"🏆 {name2} leads by {abs(lead)}"
    else:
        standing = "🤝 All square"

    blocks = [
        [f"*{APP_NAME}*"],
        [f"_Results of {_plural(shared, 'game')}_", standing],
    ]

    longest, current = streaks["longest"], streaks["current"]
    if longest:
        block = ["_Streaks_"]
        if current:
            block.append(
                f"🔥 Current • {_names([current['player']])} {current['length']}"
            )
        # one Longest line per player, when they're level on the longest run
        for run in longest["runs"]:
            block.append(f"📈 Longest • {_names([run['player']])} {run['length']}")
            block.append(f"_{_streak_span(run)}_")
        blocks.append(block)

    blocks.append([
        "_Average Score_",
        f"{avg1} • {name1}",
        f"{avg2} • {name2}",
    ])

    blocks.append([f"_{APP_URL}_"])

    return "\n\n".join("\n".join(block) for block in blocks)


def build_payload(items):
    p1, p2 = PLAYERS
    summary = {
        f"{p1}_wins": 0, f"{p2}_wins": 0, "ties": 0, "shared": 0,
        f"{p1}_only": 0, f"{p2}_only": 0, "total_puzzles": len(items),
    }
    running = []
    table_rows = []
    cum = {p1: 0, p2: 0}
    guess_sum = {p1: 0, p2: 0}
    guess_cnt = {p1: 0, p2: 0}

    for item in sorted(items, key=lambda it: int(it["puzzle"])):
        puzzle = int(item["puzzle"])
        has1, has2 = _has(item, p1), _has(item, p2)

        # accumulate each player's turns across every puzzle they played
        # (fails are already stored as 7, so they count as 7 turns)
        for player in (p1, p2):
            if _has(item, player):
                guess_sum[player] += int(item[f"{player}_guesses"])
                guess_cnt[player] += 1

        if has1 and has2:
            summary["shared"] += 1
            g1 = int(item[f"{p1}_guesses"])
            g2 = int(item[f"{p2}_guesses"])
            if g1 < g2:
                winner = p1
                summary[f"{p1}_wins"] += 1
                cum[p1] += 1
            elif g2 < g1:
                winner = p2
                summary[f"{p2}_wins"] += 1
                cum[p2] += 1
            else:
                winner = "tie"
                summary["ties"] += 1

            running.append({"puzzle": puzzle, p1: cum[p1], p2: cum[p2]})
            table_rows.append({
                "puzzle": puzzle,
                p1: _disp(g1, item.get(f"{p1}_is_fail")),
                p2: _disp(g2, item.get(f"{p2}_is_fail")),
                "winner": winner,
            })
        elif has1:
            summary[f"{p1}_only"] += 1
        elif has2:
            summary[f"{p2}_only"] += 1

    latest = _compute_latest(items)

    # per-player average turns over all puzzles they played (X/6 counts as 7)
    for player in (p1, p2):
        cnt = guess_cnt[player]
        summary[f"{player}_played"] = cnt
        summary[f"{player}_avg_guesses"] = round(guess_sum[player] / cnt, 2) if cnt else None

    streaks = _streaks(table_rows, PLAYERS)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "players": PLAYER_DISPLAY,
        "players_short": PLAYER_SHORT,
        "player_order": PLAYERS,
        "summary": summary,
        "latest": latest,
        "streaks": streaks,
        "running": running,
        "table": table_rows,
        # Precomputed so the app and the share-import response can't drift apart.
        "whatsapp_summary": _whatsapp_summary(summary, streaks),
    }


def _compute_latest(items):
    """Find the most recently reported result -> puzzle, date, days_ago."""
    best = None  # (reported_date_str, puzzle)
    for item in items:
        for player in PLAYERS:
            if not _has(item, player):
                continue
            reported = item.get(f"{player}_reported_at") or ""
            if not reported:
                continue
            cand = (reported, int(item["puzzle"]))
            if best is None or cand > best:
                best = cand

    if best is None:
        return None

    reported_str, puzzle = best
    days_ago = None
    try:
        reported_date = date.fromisoformat(reported_str)
        days_ago = (date.today() - reported_date).days
    except (ValueError, TypeError):
        pass

    return {"puzzle": puzzle, "date": reported_str, "days_ago": days_ago}


def lambda_handler(event, context):
    logger.info("build-analytics triggered")
    table = ddb.Table(TABLE_NAME)
    items = _scan_all(table)
    logger.info(f"Scanned {len(items)} puzzle items")

    payload = build_payload(items)

    s3.put_object(
        Bucket=BUCKET,
        Key=ANALYTICS_KEY,
        Body=json.dumps(payload, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    logger.info(f"Wrote analytics to s3://{BUCKET}/{ANALYTICS_KEY}")
    logger.info("SUCCESS")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "shared": payload["summary"]["shared"],
            "analytics_key": ANALYTICS_KEY,
        }),
    }
