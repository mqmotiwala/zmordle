"""
update-scores-wordle-scoreboard

Triggered by S3 ObjectCreated events when a new WhatsApp chat export lands under
the `exports/` prefix. Parses the FULL export, reconciles it against the current
DynamoDB state, and writes back only new/changed per-puzzle results.

Each export contains the entire chat history, so the vast majority of results
already exist in DDB. We do a full table scan into a local dict, diff against the
freshly parsed results, and only write the puzzles that actually changed.

On completion, asynchronously invokes the analytics Lambda to rebuild the
summary JSON the Streamlit app reads.
"""

import os
import json
import boto3
import logging
from urllib.parse import unquote_plus

from parser import parse_chat, SENDER_TO_PLAYER

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
ddb = boto3.resource("dynamodb")
lambda_client = boto3.client("lambda")

TABLE_NAME = os.environ.get("RESULTS_TABLE", "results-wordle-scoreboard")
EXPORT_PREFIX = os.environ.get("EXPORT_PREFIX", "exports/")
ANALYTICS_FUNCTION = os.environ.get(
    "ANALYTICS_FUNCTION", "build-analytics-wordle-scoreboard"
)

PLAYERS = sorted(SENDER_TO_PLAYER.values())  # ['mufi', 'zahra']

# per-player attribute names stored on each puzzle item
_ATTRS = ("guesses", "is_fail", "raw", "reported_at")


def _result_to_attrs(item, player, res):
    """Write a parsed Result's fields onto a puzzle item under the player prefix."""
    item[f"{player}_guesses"] = res.guesses
    item[f"{player}_is_fail"] = res.is_fail
    item[f"{player}_raw"] = res.raw
    item[f"{player}_reported_at"] = res.reported_at or ""


def _player_unchanged(existing, player, res):
    """True if DDB already holds this exact result for the player on this puzzle."""
    if existing is None:
        return False
    if f"{player}_guesses" not in existing:
        return False
    return (
        int(existing.get(f"{player}_guesses")) == res.guesses
        and bool(existing.get(f"{player}_is_fail")) == res.is_fail
    )


def _scan_all(table):
    """Full scan of the results table -> {puzzle(int): item dict}."""
    items = {}
    kwargs = {}
    while True:
        resp = table.scan(**kwargs)
        for it in resp.get("Items", []):
            items[int(it["puzzle"])] = it
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return items


def _read_export(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8", errors="replace")


def _iter_s3_records(event):
    """Yield (bucket, key) from an S3 trigger event, or a manual {bucket,key} event."""
    if "Records" in event:
        for rec in event["Records"]:
            s3rec = rec.get("s3", {})
            bucket = s3rec.get("bucket", {}).get("name")
            key = unquote_plus(s3rec.get("object", {}).get("key", ""))
            if bucket and key:
                yield bucket, key
    elif event.get("bucket") and event.get("key"):
        yield event["bucket"], unquote_plus(event["key"])


def lambda_handler(event, context):
    logger.info("update-scores triggered")
    logger.info(json.dumps(event))

    table = ddb.Table(TABLE_NAME)
    total_changed = 0
    processed_keys = []

    for bucket, key in _iter_s3_records(event):
        if EXPORT_PREFIX and not key.startswith(EXPORT_PREFIX):
            logger.info(f"Skipping {key} (outside '{EXPORT_PREFIX}')")
            continue

        logger.info(f"Processing export s3://{bucket}/{key}")
        text = _read_export(bucket, key)

        parsed, conflicts = parse_chat(text)
        if conflicts:
            logger.warning(f"{len(conflicts)} conflicting duplicate(s) in {key}")

        # group parsed results by puzzle
        by_puzzle = {}
        for (puzzle, player), res in parsed.items():
            by_puzzle.setdefault(puzzle, {})[player] = res

        existing = _scan_all(table)
        logger.info(
            f"Parsed {len(parsed)} results across {len(by_puzzle)} puzzles; "
            f"{len(existing)} puzzles already in DDB"
        )

        changed_items = []
        for puzzle, players in by_puzzle.items():
            current = existing.get(puzzle)
            # start from the existing item so we never clobber the other player
            item = dict(current) if current else {"puzzle": puzzle}
            item["puzzle"] = puzzle

            puzzle_changed = False
            for player, res in players.items():
                if not _player_unchanged(current, player, res):
                    _result_to_attrs(item, player, res)
                    puzzle_changed = True

            if puzzle_changed:
                changed_items.append(item)

        if changed_items:
            with table.batch_writer() as batch:
                for item in changed_items:
                    batch.put_item(Item=item)

        logger.info(f"Wrote {len(changed_items)} changed puzzle(s) from {key}")
        total_changed += len(changed_items)
        processed_keys.append(key)

    # rebuild analytics regardless of change count so freshness stays accurate
    if processed_keys:
        try:
            lambda_client.invoke(
                FunctionName=ANALYTICS_FUNCTION,
                InvocationType="Event",  # async fire-and-forget
                Payload=json.dumps({"reason": "update-scores", "keys": processed_keys}).encode(),
            )
            logger.info(f"Invoked {ANALYTICS_FUNCTION}")
        except Exception as e:
            logger.exception(f"Failed to invoke analytics Lambda: {e}")

    logger.info("SUCCESS")
    return {
        "statusCode": 200,
        "body": json.dumps({
            "changed_puzzles": total_changed,
            "processed_keys": processed_keys,
        }),
    }
