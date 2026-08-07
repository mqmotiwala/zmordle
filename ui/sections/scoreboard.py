"""
Scoreboard section: overall W/L/T metrics, running-score plot, results table.

Streak figures and the shareable summary text are computed by the
build-analytics Lambda and read straight off the analytics payload, so that this
app and the share-import endpoint's reply to the phone can never drift apart.
"""

from datetime import timedelta

import config as c
import pandas as pd
import streamlit as st
import utils.css as css
import utils.plotters as plotters
from st_copy import copy_button


def _puzzle_date(puzzle):
    """Back-calculate a puzzle's calendar date from the known anchor."""
    delta = int(puzzle) - c.WORDLE_ANCHOR_NUMBER
    return c.WORDLE_ANCHOR_DATE + timedelta(days=delta)


def _fmt_avg(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "—"


def _names(players):
    """Join one or more player ids into a display string."""
    return " & ".join(c.PLAYER_DISPLAY.get(p, p) for p in players)


def _show_copy_metrics(analytics):
    """A labelled copy icon that puts the shareable summary on the clipboard."""
    summary_text = analytics.get("whatsapp_summary")
    if not summary_text:
        return

    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        # 'copied' is a trigger value: True only on the rerun the click caused,
        # so the toast fires once per press rather than on every rerun, and
        # repeat presses still register.
        copied = copy_button(
            summary_text,
            tooltip="Copy metrics",
            copied_label="Copied!",
            key="copy_metrics",
        )
        st.markdown("Copy metrics")

    if copied:
        st.toast("Copied to clipboard!", icon="📋")
    elif copied is False:
        # The Clipboard API needs a secure context and refuses without one.
        st.toast("Couldn't reach the clipboard.", icon="⚠️")


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
    avg1 = summary.get(f"{p1}_avg_guesses")
    avg2 = summary.get(f"{p2}_avg_guesses")

    avg_help = (
        "Average turns per puzzle played. An unsolved puzzle (X/6) counts as 7 turns."
    )

    lead = wins1 - wins2
    if lead > 0:
        leader_delta = f"{name1} leads by {lead}"
    elif lead < 0:
        leader_delta = f"{name2} leads by {abs(lead)}"
    else:
        leader_delta = "All square"

    streaks = analytics.get("streaks") or {}
    longest, current = streaks.get("longest"), streaks.get("current")

    longest_value = longest["length"] if longest else "—"
    longest_delta = (
        _names([run["player"] for run in longest["runs"]]) if longest else None
    )

    current_value = current["length"] if current else "—"
    if current:
        current_delta = _names([current["player"]])
    elif streaks.get("last_winner") == "tie":
        current_delta = "Ended by a tie"
    else:
        current_delta = None

    # --- overall W/L/T metrics ---
    with st.container(horizontal=True, gap="small", horizontal_alignment="distribute"):
        st.metric(
            "Head-to-head puzzles", shared,
            delta=leader_delta, delta_color="off", delta_arrow="off",
            border=False,
        )
        st.metric(f"{name1} wins", wins1, border=False)
        st.metric(f"{name2} wins", wins2, border=False)
        st.metric("Ties", ties, border=False)

    # --- form metrics: average turns + streaks ---
    with st.container(horizontal=True, gap="small", horizontal_alignment="distribute"):
        st.metric(f"{name1} avg turns", _fmt_avg(avg1), help=avg_help, border=False)
        st.metric(f"{name2} avg turns", _fmt_avg(avg2), help=avg_help, border=False)
        st.metric(
            "Longest win streak", longest_value,
            delta=longest_delta, delta_color="off", delta_arrow="off", border=False,
        )

        st.metric(
            "Current streak", current_value,
            delta=current_delta, delta_color="off", delta_arrow="off", border=False,
        )

    # --- copy the shareable recap ---
    _show_copy_metrics(analytics)

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
