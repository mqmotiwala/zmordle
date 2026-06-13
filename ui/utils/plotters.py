"""
Plotters for the Wordle Scoreboard app.
"""

import config as c
import plotly.graph_objects as go


def running_score_chart(running, player_order):
    """
    Build a cumulative-wins line chart.

    Args:
        running: list of {"puzzle": int, "<player>": cumulative_wins, ...}
        player_order: list of player ids, e.g. ["mufi", "zahra"]
    """
    fig = go.Figure()

    puzzles = [row["puzzle"] for row in running]

    for player in player_order:
        fig.add_trace(
            go.Scatter(
                x=puzzles,
                y=[row.get(player, 0) for row in running],
                mode="lines+markers",
                name=c.PLAYER_DISPLAY.get(player, player),
                line=dict(color=c.PLAYER_COLORS.get(player), width=2.5),
                marker=dict(size=5),
                hovertemplate=(
                    f"{c.PLAYER_DISPLAY.get(player, player)}<br>"
                    "Wordle %{x}<br>Wins: %{y}<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        template="plotly_white",
        height=520,
        margin=dict(l=80, r=40, t=70, b=80),
        font=dict(size=14),
        xaxis=dict(
            title=dict(text="Wordle puzzle #", font=dict(size=17)),
            tickfont=dict(size=13),
            showgrid=True,
        ),
        yaxis=dict(
            title=dict(text="Cumulative wins", font=dict(size=17), standoff=12),
            tickfont=dict(size=13),
            rangemode="tozero",
            showgrid=True,
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.04,
            xanchor="left", x=0, font=dict(size=14),
        ),
        hovermode="x unified",
    )

    return fig
