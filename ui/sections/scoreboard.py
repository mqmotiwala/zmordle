"""
Scoreboard section: overall W/L/T metrics, running-score plot, results table.
"""

from datetime import timedelta

import config as c
import pandas as pd
import streamlit as st
import utils.css as css
import utils.plotters as plotters


def _puzzle_date(puzzle):
    """Back-calculate a puzzle's calendar date from the known anchor."""
    delta = int(puzzle) - c.WORDLE_ANCHOR_NUMBER
    return c.WORDLE_ANCHOR_DATE + timedelta(days=delta)


def show_scoreboard(analytics):
    if not analytics:
        return

    summary = analytics.get("summary", {})
    player_order = analytics.get("player_order", sorted(c.PLAYER_DISPLAY))
    p1, p2 = player_order
    name1 = c.PLAYER_DISPLAY.get(p1, p1)
    name2 = c.PLAYER_DISPLAY.get(p2, p2)

    wins1 = summary.get(f"{p1}_wins", 0)
    wins2 = summary.get(f"{p2}_wins", 0)
    ties = summary.get("ties", 0)
    shared = summary.get("shared", 0)

    # --- overall W/L/T metrics ---
    lead = wins1 - wins2
    if lead > 0:
        leader_delta = f"{name1} leads by {lead}"
    elif lead < 0:
        leader_delta = f"{name2} leads by {abs(lead)}"
    else:
        leader_delta = "All square"

    with st.container(horizontal=True, gap="small", horizontal_alignment="distribute"):
        st.metric(
            "Head-to-head puzzles", shared,
            delta=leader_delta, delta_color="off", border=False,
        )
        st.metric(f"{name1} wins", wins1, border=False)
        st.metric(f"{name2} wins", wins2, border=False)
        st.metric("Ties", ties, border=False)

    css.divider()

    # --- running score plot ---
    running = analytics.get("running", [])
    css.header("Running score", lvl=4)
    if running:
        with st.container(border=True):
            st.plotly_chart(
                plotters.running_score_chart(running, player_order),
                width="stretch",
            )
    else:
        st.caption("Not enough shared puzzles yet to plot a running score.")

    css.empty_space()

    # --- per-puzzle table ---
    rows = analytics.get("table", [])
    css.header("Per-puzzle results", lvl=4)
    if rows:
        with st.expander("Show all puzzles", expanded=True):
            df = pd.DataFrame(rows).sort_values("puzzle", ascending=False)
            df["date"] = pd.to_datetime(df["puzzle"].map(_puzzle_date))
            df["winner"] = df["winner"].map(
                lambda w: "Tie" if w == "tie" else c.PLAYER_DISPLAY.get(w, w)
            )
            df = df.rename(columns={
                "puzzle": "Wordle #",
                "date": "Date",
                p1: name1,
                p2: name2,
                "winner": "Winner",
            })
            df = df[["Wordle #", "Date", name1, name2, "Winner"]]
            st.dataframe(
                df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Wordle #": st.column_config.NumberColumn(format="%d"),
                    "Date": st.column_config.DateColumn(
                        format=c.PREFERRED_DATE_FORMAT_MOMENTJS
                    ),
                },
            )
    else:
        st.caption("No head-to-head puzzles to show yet.")
