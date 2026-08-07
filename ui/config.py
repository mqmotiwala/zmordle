"""
General configuration for the Wordle Scoreboard Streamlit app.
"""

import os
import boto3
import streamlit as st
from datetime import date
from dotenv import load_dotenv, find_dotenv

# load environment variables from the repo-root .env (searches upward from cwd)
load_dotenv(find_dotenv())


def env(key, default=None):
    var = os.getenv(key, default)
    if var is None:
        raise RuntimeError(f"Missing env var: {key}")
    return var


# --- AWS ---------------------------------------------------------------------
AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY")
AWS_REGION = env("AWS_REGION", "us-west-2")

S3_BUCKET = "aws-wordle-scoreboard"
ANALYTICS_KEY = "analytics/scoreboard.json"

s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    region_name=AWS_REGION,
)

# --- players / theming -------------------------------------------------------
# matches primaryColor in .streamlit/config.toml (Wordle "present" mustard yellow)
PRIMARY_COLOR = "#ffc425"

APP_TITLE = "zmordle"
APP_ICON = ""
APP_TAGLINE = "Zahra v Mufaddal | Who's really better at Wordle?"

# Anchor for back-calculating a puzzle's date (one puzzle per calendar day).
# Verified: Wordle #1820 was Saturday, June 13, 2026.
WORDLE_ANCHOR_NUMBER = 1820
WORDLE_ANCHOR_DATE = date(2026, 6, 13)

# moment.js format used by st.column_config.DateColumn
PREFERRED_DATE_FORMAT_MOMENTJS = "dddd, MMMM DD, YYYY"

# player id -> display name (keep in sync with the backend parser)
PLAYER_DISPLAY = {
    "mufi": "Mufaddal",
    "zahra": "Zahra",
}

# per-player line colors for the running-score plot
PLAYER_COLORS = {
    "mufi": "#1f77b4",
    "zahra": "#d62728",
}

# --- page config -------------------------------------------------------------
STREAMLIT_PAGE_CONFIG = {
    "page_title": APP_TITLE,
    "page_icon": APP_ICON,
    "layout": "wide",
    "initial_sidebar_state": "collapsed",
}

# cache TTL (seconds) for the analytics JSON read from S3
ANALYTICS_CACHE_TTL = 60
