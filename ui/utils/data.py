"""
Data access for the Streamlit app: load the precomputed analytics JSON from S3.
"""

import json
import config as c
import streamlit as st
from botocore.exceptions import ClientError


@st.cache_data(ttl=c.ANALYTICS_CACHE_TTL, show_spinner=False)
def load_analytics():
    """
    Read analytics/scoreboard.json from S3.

    Returns the parsed dict, or None if the object doesn't exist yet
    (e.g. no export has been processed).
    """
    try:
        obj = c.s3.get_object(Bucket=c.S3_BUCKET, Key=c.ANALYTICS_KEY)
        return json.loads(obj["Body"].read().decode("utf-8"))
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NoSuchBucket"):
            return None
        raise


def refresh_analytics():
    """Clear the cache so the next load_analytics() hits S3 again."""
    load_analytics.clear()
