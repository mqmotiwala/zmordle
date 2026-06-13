"""
Upload section: ingest a WhatsApp chat export directly into the pipeline.

Dropping a .txt export here uploads it to S3 under the `exports/` prefix, which
triggers the update-scores -> build-analytics Lambda chain. We then wait briefly
for the analytics JSON to regenerate and refresh the view.
"""

import time

import config as c
import utils.css as css
import utils.data as data
import streamlit as st

HELP_TEXT = (
    "Wordle result updates have to be manually ingested, since WhatsApp API does "
    "not support non-business accounts. Use the file uploader to ingest chat "
    "exports directly."
)


def _wait_for_refresh(prev_generated_at, attempts=12, interval=2):
    """Poll S3 until the analytics JSON is regenerated (or we time out)."""
    for _ in range(attempts):
        time.sleep(interval)
        data.refresh_analytics()
        latest = data.load_analytics()
        if latest and latest.get("generated_at") != prev_generated_at:
            return True
    return False


def show_upload(analytics):
    uploaded = st.file_uploader(
        "Ingest a WhatsApp chat export",
        type=["txt"],
        help=HELP_TEXT,
        key="chat_export_uploader",
    )

    if uploaded is not None:
        # only ingest a newly selected file once (the uploader persists across reruns)
        signature = (uploaded.name, uploaded.size)
        if st.session_state.get("_ingested_signature") != signature:
            prev_generated_at = (analytics or {}).get("generated_at")
            with st.spinner("Ingesting export and updating the scoreboard…"):
                c.s3.put_object(
                    Bucket=c.S3_BUCKET,
                    Key=f"exports/{uploaded.name}",
                    Body=uploaded.getvalue(),
                )
                refreshed = _wait_for_refresh(prev_generated_at)

            st.session_state["_ingested_signature"] = signature
            if refreshed:
                st.success(f"Ingested **{uploaded.name}** — scoreboard updated.")
                st.rerun()
            else:
                st.warning(
                    f"Uploaded **{uploaded.name}**, but the scoreboard hasn't "
                    "updated yet. Give it a moment and refresh."
                )

    css.divider()
