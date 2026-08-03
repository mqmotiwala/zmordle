"""
share-import-wordle-scoreboard

Public entry point for pushing a WhatsApp chat export straight from an Android
share sheet into the ingest pipeline, skipping the browser upload entirely.

    Android share -> this function's Function URL -> s3://BUCKET/exports/*.txt
    -> existing S3 notification -> update-scores -> build-analytics

Accepts either a plain .txt export or a .zip containing one, since WhatsApp's
"without media" export is zipped on some Android versions. The export bytes are
written to S3 unchanged, so downstream parsing is byte-for-byte identical to a
browser upload and no new failure modes are introduced.

Security: the Function URL is configured with AuthType NONE, meaning anyone who
knows the URL can reach it. The X-Api-Key header, compared in constant time
against the SHARE_SECRET environment variable, is the ONLY thing protecting the
ingest path. Requests are rejected before any body is read or written, and the
function fails closed if SHARE_SECRET is unset.
"""

import base64
import hmac
import io
import json
import logging
import os
import re
import time
import zipfile
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")

BUCKET = os.environ.get("BUCKET", "aws-wordle-scoreboard")
EXPORT_PREFIX = os.environ.get("EXPORT_PREFIX", "exports/")
ANALYTICS_KEY = os.environ.get("ANALYTICS_KEY", "analytics/scoreboard.json")
SHARE_SECRET = os.environ.get("SHARE_SECRET", "")

# How long to wait for update-scores -> build-analytics to land a fresh
# analytics object before giving up and returning a plain receipt instead.
WAIT_SECONDS = 25
POLL_EVERY = 1.5

# Lambda Function URLs cap request payloads at roughly this size anyway.
MAX_BYTES = 6 * 1024 * 1024

ZIP_MAGIC = b"PK\x03\x04"

# Sanity check only, to catch "wrong file shared" before it enters the pipeline.
# The real parsing lives in update-scores.
RESULT_TOKEN = re.compile(rb"Wordle\s+[\d,]+\s+[1-6X]/6", re.IGNORECASE)


def _text(status, message):
    """Plain-text response, so the Android shortcut can display or share it."""
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/plain; charset=utf-8"},
        "body": message,
    }


def _method(event):
    return event.get("requestContext", {}).get("http", {}).get("method", "").upper()


def _header(event, name):
    """Function URL headers arrive lower-cased."""
    return (event.get("headers") or {}).get(name.lower(), "") or ""


def _authorized(event):
    if not SHARE_SECRET:
        logger.error("SHARE_SECRET is not configured; refusing all requests")
        return False
    return hmac.compare_digest(_header(event, "X-Api-Key"), SHARE_SECRET)


def _body_bytes(event):
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return body.encode("utf-8")


def _extract_export(raw):
    """
    Return (export_bytes, description) for a raw upload.

    Handles a bare .txt or a .zip holding one. Bytes are returned untouched.
    """
    if not raw.startswith(ZIP_MAGIC):
        return raw, "plain text"

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        txts = [n for n in zf.namelist() if n.lower().endswith(".txt")]
        if not txts:
            raise ValueError(f"zip has no .txt inside (contains: {zf.namelist()})")
        # A WhatsApp export holds a single chat transcript; if somehow there are
        # several, the largest is the transcript.
        name = max(txts, key=lambda n: zf.getinfo(n).file_size)
        return zf.read(name), f"unzipped {name!r}"


def _read_analytics():
    """Current analytics payload, or None if it isn't there yet."""
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=ANALYTICS_KEY)
        return json.loads(obj["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
    except (ValueError, KeyError):
        logger.exception("Analytics object is present but unreadable")
        return None


def _wait_for_summary(previous_stamp):
    """
    Poll the analytics object until the pipeline regenerates it, then return its
    shareable summary text. Returns None if it doesn't refresh in time.

    Polling rather than invoking the chain synchronously keeps this function to
    read-only S3 access and avoids a second, duplicate pipeline run alongside
    the one the S3 notification already triggers.
    """
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(POLL_EVERY)
        payload = _read_analytics()
        if not payload:
            continue
        if payload.get("generated_at") != previous_stamp:
            summary = payload.get("whatsapp_summary")
            if summary:
                return summary
            logger.warning("Analytics refreshed but carries no whatsapp_summary")
            return None
    logger.warning(f"Analytics did not refresh within {WAIT_SECONDS}s")
    return None


def lambda_handler(event, context):
    method = _method(event)
    if method not in ("POST", "PUT"):
        return _text(405, f"Send the export with POST, not {method or 'that'}.")

    if not _authorized(event):
        logger.warning("Rejected a request with a missing or invalid X-Api-Key")
        return _text(401, "Unauthorized.")

    raw = _body_bytes(event)
    if not raw:
        return _text(400, "Empty body - no file came through.")
    if len(raw) > MAX_BYTES:
        return _text(413, f"That file is too big ({len(raw):,} bytes).")

    try:
        export, source = _extract_export(raw)
    except (zipfile.BadZipFile, ValueError) as e:
        logger.exception("Could not extract the export")
        return _text(400, f"Could not read that file: {e}")

    # Validate BEFORE writing, so a wrong file never reaches the pipeline.
    hits = len(RESULT_TOKEN.findall(export))
    if hits == 0:
        logger.warning(f"No Wordle results in upload ({len(export)} bytes, {source})")
        return _text(
            422,
            "No Wordle results found in that file, so nothing was imported.\n"
            "Make sure you shared the exported chat transcript.",
        )

    # Note the current analytics stamp first, so we can tell when the pipeline
    # has finished reprocessing rather than reading a stale summary back.
    current = _read_analytics() or {}
    previous_stamp = current.get("generated_at")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    key = f"{EXPORT_PREFIX}{stamp}-share.txt"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=export,
        ContentType="text/plain; charset=utf-8",
    )
    logger.info(
        f"Wrote s3://{BUCKET}/{key} ({len(export)} bytes, {source}, {hits} results)"
    )

    summary = _wait_for_summary(previous_stamp)
    if summary:
        logger.info("Returning refreshed summary")
        return _text(200, summary)

    # The import is still in flight; it will land on its own shortly.
    return _text(
        200,
        f"Imported {hits} results ({len(export):,} bytes).\n"
        "The scoreboard is still updating - check the app in a moment.",
    )
