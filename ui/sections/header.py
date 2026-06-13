"""
Top of the app: highlighted title and tagline.
"""

import config as c
import utils.css as css
import streamlit as st


def show_header():
    with st.container(gap=None):
        css.markdown(f"## {css.highlight(c.APP_TITLE, tilt=-2)} {c.APP_ICON}")
        css.markdown(f"##### {c.APP_TAGLINE}")
        css.divider()
