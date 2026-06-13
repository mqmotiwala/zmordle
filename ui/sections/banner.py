"""
Freshness banner: communicates how recent the reported results are.
"""

from datetime import date
import streamlit as st
import utils.css as css


def _humanize_days(days_ago):
    if days_ago is None:
        return ""
    if days_ago <= 0:
        return "today"
    if days_ago == 1:
        return "yesterday"
    return f"{days_ago} days ago"


def _format_date(iso_str):
    try:
        return date.fromisoformat(iso_str).strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        # %-d isn't supported on Windows; fall back to a portable format
        try:
            return date.fromisoformat(iso_str).strftime("%B %d, %Y")
        except (ValueError, TypeError):
            return iso_str or "unknown date"


def show_banner(analytics):
    latest = (analytics or {}).get("latest")

    if not latest or not latest.get("puzzle"):
        st.warning("No results have been reported yet. Upload a chat export to get started.")
        return

    puzzle = latest["puzzle"]
    when = _format_date(latest.get("date"))
    rel = _humanize_days(latest.get("days_ago"))
    rel_suffix = f" — {rel}" if rel else ""

    css.markdown(
        f"📅 {css.underline('Last reported puzzle')}: "
        f"Wordle {puzzle:,} on {when}{rel_suffix}."
    )
    css.divider()
