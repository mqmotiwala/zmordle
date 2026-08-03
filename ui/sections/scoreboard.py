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


def _fmt_avg(v):
    return f"{v:.2f}" if isinstance(v, (int, float)) else "—"


def _plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _names(players):
    """Join one or more player ids into a display string."""
    return " & ".join(c.PLAYER_DISPLAY.get(p, p) for p in players)


def _streak_span(run):
    """The puzzles a run started and ended on: 'Wordle 1,866-1,868'."""
    start, end = run["start"], run["end"]
    if start == end:
        return f"Wordle {start:,}"
    return f"Wordle {start:,}-{end:,}"


def _head_to_head(rows, player_order):
    """
    Keep only the games both players have played, ordered oldest -> newest.

    Ordering is by puzzle number, so this is a sequence of games rather than of
    dates — calendar gaps between puzzles carry no meaning here.
    """
    p1, p2 = player_order
    games = [r for r in rows if r.get(p1) is not None and r.get(p2) is not None]
    return sorted(games, key=lambda r: int(r["puzzle"]))


def _streaks(rows, player_order):
    """
    Measure win streaks in games, walking head-to-head puzzles oldest -> newest.

    Streaks are counted per game, never per date. A streak only advances on a
    puzzle both players finished, so a puzzle only one of them played is skipped
    over rather than treated as a break — as are any calendar gaps between
    puzzles. Ordering comes from the puzzle number; dates never enter into it.

    A tie ends a streak.

    Each run is reported with the puzzle it started and ended on. Where a player
    has several runs of their best length, the earliest one is kept — that's the
    run that set the record.

    Returns a dict with:
      longest -> {"length": int, "runs": [run, ...]} or None, where runs holds
                 one entry per player level on that length
      current -> the run still alive, or None
      last_winner -> winner of the most recent head-to-head puzzle, or None

    A run is {"player": id, "length": int, "start": puzzle, "end": puzzle}.
    """
    best = {p: None for p in player_order}  # each player's record run
    run_player, run_len, run_start, run_end = None, 0, None, None
    last_winner = None

    for row in _head_to_head(rows, player_order):
        puzzle = int(row["puzzle"])
        winner = row.get("winner")
        last_winner = winner

        if winner in best:
            if winner == run_player:
                run_len += 1
            else:
                run_player, run_len, run_start = winner, 1, puzzle
            run_end = puzzle

            # strictly greater, so a later run of equal length doesn't displace
            # the one that set the record
            if best[winner] is None or run_len > best[winner]["length"]:
                best[winner] = {
                    "player": winner, "length": run_len,
                    "start": run_start, "end": run_end,
                }
        else:  # a tie (or an unrecognised winner) resets the run
            run_player, run_len, run_start, run_end = None, 0, None, None

    top = max((run["length"] for run in best.values() if run), default=0)
    longest = (
        {
            "length": top,
            "runs": [best[p] for p in player_order
                     if best[p] and best[p]["length"] == top],
        }
        if top
        else None
    )
    current = (
        {"player": run_player, "length": run_len, "start": run_start, "end": run_end}
        if run_player
        else None
    )

    return {"longest": longest, "current": current, "last_winner": last_winner}


def _whatsapp_summary(analytics, player_order):
    """
    Build a plain-text recap of the scoreboard, ready to paste into WhatsApp.

    Uses WhatsApp's markup — *bold* for the title, _italics_ for section headers
    and the streak span — which shows as literal punctuation here but renders as
    formatting once pasted into a chat. Built as blocks: lines inside a block sit
    together, and blocks are separated by one blank line.
    """
    p1, p2 = player_order
    name1 = c.PLAYER_DISPLAY.get(p1, p1)
    name2 = c.PLAYER_DISPLAY.get(p2, p2)

    summary = analytics.get("summary", {})
    wins1 = summary.get(f"{p1}_wins", 0)
    wins2 = summary.get(f"{p2}_wins", 0)
    shared = summary.get("shared", 0)
    avg1 = _fmt_avg(summary.get(f"{p1}_avg_guesses"))
    avg2 = _fmt_avg(summary.get(f"{p2}_avg_guesses"))

    lead = wins1 - wins2
    if lead > 0:
        standing = f"🏆 {name1} leads by {lead}"
    elif lead < 0:
        standing = f"🏆 {name2} leads by {abs(lead)}"
    else:
        standing = "🤝 All square"

    blocks = [
        ["*Wordle Scoreboard*"],
        [f"_Results of {_plural(shared, 'game')}_", standing],
    ]

    streaks = _streaks(analytics.get("table", []), player_order)
    longest, current = streaks["longest"], streaks["current"]
    if longest:
        block = ["_Streaks_"]
        if current:
            block.append(
                f"🔥 Current • {_names([current['player']])} {current['length']}"
            )
        # one Longest line per player, when they're level on the longest run
        for run in longest["runs"]:
            block.append(f"📈 Longest • {_names([run['player']])} {run['length']}")
            block.append(f"_{_streak_span(run)}_")
        blocks.append(block)

    blocks.append([
        "_Average Score_",
        f"{avg1} • {name1}",
        f"{avg2} • {name2}",
    ])

    blocks.append([
        "_https://wordle-scoreboard.up.railway.app/_"
    ])

    return "\n\n".join("\n".join(block) for block in blocks)


def _show_quick_copy(analytics, player_order):
    """Collapsible (open by default) block of copy-paste-ready summary text."""
    with st.expander("Quick copy", expanded=True):
        st.code(
            _whatsapp_summary(analytics, player_order),
            language=None,
            wrap_lines=True,
        )


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

    streaks = _streaks(analytics.get("table", []), player_order)
    longest, current = streaks["longest"], streaks["current"]

    longest_value = longest["length"] if longest else "—"
    longest_delta = (
        _names([run["player"] for run in longest["runs"]]) if longest else None
    )

    current_value = current["length"] if current else "—"
    if current:
        current_delta = _names([current["player"]])
    elif streaks["last_winner"] == "tie":
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

    # --- copy-paste-ready recap ---
    _show_quick_copy(analytics, player_order)

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
