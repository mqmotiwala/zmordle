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


def build_payload(items):
    p1, p2 = PLAYERS
    summary = {
        f"{p1}_wins": 0, f"{p2}_wins": 0, "ties": 0, "shared": 0,
        f"{p1}_only": 0, f"{p2}_only": 0, "total_puzzles": len(items),
    }
    running = []
    table_rows = []
    cum = {p1: 0, p2: 0}

    for item in sorted(items, key=lambda it: int(it["puzzle"])):
        puzzle = int(item["puzzle"])
        has1, has2 = _has(item, p1), _has(item, p2)

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

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "players": PLAYER_DISPLAY,
        "player_order": PLAYERS,
        "summary": summary,
        "latest": latest,
        "running": running,
        "table": table_rows,
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
