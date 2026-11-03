"""Gradio theme: cool grey canvas, white panels, one deep teal accent, IBM Plex Sans.

Colours are defined once here (for Gradio's own components) and once in `style.css`
(for StaffPilot's HTML pieces), each with a light and a dark value.
"""

from __future__ import annotations

from pathlib import Path

import gradio as gr


CSS = (Path(__file__).parent / "style.css").read_text(encoding="utf-8")

INK = "#17202b"
ACCENT = "#0f6e75"
ACCENT_DARK = "#5fb8be"


def theme() -> gr.themes.Base:
    base = gr.themes.Base(
        primary_hue=gr.themes.colors.teal,
        neutral_hue=gr.themes.colors.slate,
        radius_size=gr.themes.sizes.radius_sm,
        spacing_size=gr.themes.sizes.spacing_md,
        text_size=gr.themes.sizes.text_md,
        font=[gr.themes.GoogleFont("IBM Plex Sans"), "Helvetica Neue", "Arial", "sans-serif"],
        font_mono=["ui-monospace", "Menlo", "monospace"],
    )
    return base.set(
        body_background_fill="#eef1f4",
        body_background_fill_dark="#101418",
        body_text_color=INK,
        body_text_color_dark="#e8edf1",
        body_text_color_subdued="#6b7682",
        body_text_color_subdued_dark="#8a949e",
        background_fill_primary="#ffffff",
        background_fill_primary_dark="#171c21",
        background_fill_secondary="#f7f9fa",
        background_fill_secondary_dark="#1c2228",
        border_color_primary="#e2e6eb",
        border_color_primary_dark="#29313a",
        block_background_fill="#ffffff",
        block_background_fill_dark="#171c21",
        block_border_width="1px",
        block_border_color="#e2e6eb",
        block_border_color_dark="#29313a",
        block_shadow="none",
        block_shadow_dark="none",
        block_radius="8px",
        block_label_text_color="#71717a",
        block_label_text_weight="500",
        block_label_text_size="12px",
        block_title_text_weight="500",
        input_background_fill="#ffffff",
        input_background_fill_dark="#1c2228",
        input_border_color="#cfd6dd",
        input_border_color_dark="#36404a",
        input_border_color_focus=ACCENT,
        input_border_color_focus_dark=ACCENT_DARK,
        input_shadow="none",
        input_shadow_focus="0 0 0 3px rgba(15, 110, 117, 0.14)",
        input_radius="8px",
        button_large_radius="8px",
        button_small_radius="6px",
        button_primary_background_fill=ACCENT,
        button_primary_background_fill_hover="#0b5a60",
        button_primary_background_fill_dark=ACCENT_DARK,
        button_primary_background_fill_hover_dark="#7fcbd0",
        button_primary_text_color="#ffffff",
        button_primary_text_color_dark="#101418",
        button_primary_border_color="transparent",
        button_primary_shadow="none",
        button_secondary_background_fill="#ffffff",
        button_secondary_background_fill_hover="#e4e9ed",
        button_secondary_background_fill_dark="#1c2228",
        button_secondary_background_fill_hover_dark="#222a31",
        button_secondary_border_color="#cfd6dd",
        button_secondary_border_color_dark="#36404a",
        button_secondary_text_color=INK,
        button_secondary_text_color_dark="#ededef",
        button_secondary_shadow="none",
        button_border_width="1px",
        button_transition="background 120ms ease",
        color_accent_soft="#e2f0f1",
        color_accent_soft_dark="#17343a",
        table_border_color="#e2e6eb",
        table_border_color_dark="#29313a",
        table_even_background_fill="#f7f9fa",
        table_even_background_fill_dark="#1a2026",
        table_odd_background_fill="#ffffff",
        table_odd_background_fill_dark="#171c21",
    )
