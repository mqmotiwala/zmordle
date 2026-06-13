"""
Wordle Scoreboard — Streamlit front end.

Reads a precomputed analytics JSON from S3 (produced by the build-analytics
Lambda) and renders the head-to-head scoreboard.
"""

import config as c
import streamlit as st
import utils.data as data

from sections.header import show_header
from sections.banner import show_banner
from sections.scoreboard import show_scoreboard

st.set_page_config(**c.STREAMLIT_PAGE_CONFIG)

show_header()

analytics = data.load_analytics()

show_banner(analytics)

if analytics:
    show_scoreboard(analytics)
