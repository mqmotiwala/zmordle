"""
Small CSS/markdown helpers for styling the Streamlit UI.

Mirrors the helper used in the Pickwise app so the look-and-feel is consistent
across projects (highlighted titles, custom dividers, underlines, etc.).
"""

import config as c
import streamlit as st


def markdown(text):
    """Wrapper on st.markdown() that allows inline HTML."""
    return st.markdown(text, unsafe_allow_html=True)


def highlight(text, background=c.PRIMARY_COLOR, color="black",
              font_weight="normal", font_size="inherit", tilt=0):
    """Return an HTML <span> that highlights text inside Streamlit markdown."""
    return (
        "<span style='"
        f"background-color:{background}; "
        f"color:{color}; "
        f"font-weight:{font_weight}; "
        f"font-size:{font_size}; "
        f"transform: rotate({tilt}deg); "
        "border-radius: 6px; "
        "display: inline-block; "
        "padding: 2px 8px;'>"
        f"{text}</span>"
    )


def center(text, margin="1em 0"):
    """Return an HTML <div> that center-aligns the text."""
    return f"<div style='text-align: center; margin: {margin};'>{text}</div>"


def divider(color=c.PRIMARY_COLOR, thickness="1px", margin="1.25em 0"):
    """Render a horizontal divider styled with a custom color/thickness."""
    return markdown(
        f"<hr style='border: none; border-top: {thickness} solid {color}; "
        f"margin: {margin};' />"
    )


def underline(text, color=c.PRIMARY_COLOR, thickness="2px", offset="2px", style="solid"):
    """Return an HTML <span> with a styled underline."""
    if style not in ("solid", "double", "dotted", "dashed", "wavy"):
        raise ValueError("Invalid underline style")
    return (
        "<span style='"
        "text-decoration: underline; "
        f"text-decoration-color: {color}; "
        f"text-decoration-style: {style}; "
        f"text-underline-offset: {offset}; "
        f"text-decoration-thickness: {thickness};'>"
        f"{text}</span>"
    )


def header(text, lvl=1, underline_text=True):
    """Shorthand for rendering a markdown header, optionally underlined."""
    if lvl not in range(1, 7):
        raise ValueError("Markdown levels must be between 1 and 6")
    prefix = "#" * lvl
    body = underline(text) if underline_text else text
    return markdown(f"{prefix} {body}")


def empty_space():
    """Insert a little vertical breathing room."""
    st.markdown("")
    st.markdown("")
