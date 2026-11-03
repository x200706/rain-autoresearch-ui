"""沿用 HTML 原型的配色（深色為主）與 125% 字級。"""
import inspect

import gradio as gr

# 淺色：面板用白色，不再灰灰的；深色：本文更亮、強調藍更淡，深底上比較清楚
LIGHT = dict(bg="#F4F7FB", bar="#EAF0F7", panel="#FFFFFF", editor="#FFFFFF", input="#FFFFFF", border="#D3DCE8",
             strong="#9AAAC0", sel="#DCEAFB", text="#1A2233", muted="#56637A", accent="#005FB8", btn="#005FB8",
             err="#B3261E")
DARK = dict(bg="#0B0E13", bar="#0F131A", panel="#0D1117", editor="#0B0E13", input="#141A23", border="#1E2632",
            strong="#334155", sel="#0F2547", text="#E2E8F0", muted="#A3AFC0", accent="#7FB2FF", btn="#1F6FEB",
            err="#F85149")


def build() -> gr.themes.Base:
    theme = gr.themes.Base(
        primary_hue=gr.themes.colors.blue, neutral_hue=gr.themes.colors.slate,
        text_size=gr.themes.Size(xxs="11px", xs="13px", sm="15px", md="17px", lg="19px", xl="23px", xxl="28px"),
        spacing_size=gr.themes.sizes.spacing_md, radius_size=gr.themes.sizes.radius_sm,
        font=["Segoe UI", "system-ui", "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("JetBrains Mono"), "ui-monospace", "Consolas", "monospace"],
    )
    pairs = {
        "body_background_fill": "bg", "background_fill_primary": "panel", "background_fill_secondary": "bar",
        "block_background_fill": "panel", "block_border_color": "border", "border_color_primary": "border",
        "panel_background_fill": "panel", "panel_border_color": "border", "input_background_fill": "input",
        "input_border_color": "border", "input_border_color_focus": "accent", "body_text_color": "text",
        "body_text_color_subdued": "muted", "block_label_text_color": "muted", "block_title_text_color": "text",
        "block_info_text_color": "muted", "color_accent": "accent", "color_accent_soft": "sel",
        "border_color_accent": "accent", "link_text_color": "accent", "code_background_fill": "editor",
        "button_primary_background_fill": "btn", "button_primary_border_color": "btn",
        "button_secondary_background_fill": "input", "button_secondary_border_color": "border",
        "checkbox_label_background_fill": "input", "checkbox_label_background_fill_selected": "sel",
        "checkbox_background_color_selected": "btn", "checkbox_border_color_selected": "btn",
        "table_border_color": "border", "table_even_background_fill": "panel", "table_odd_background_fill": "editor",
        "error_border_color": "err", "block_label_background_fill": "panel",
    }
    allowed = set(inspect.signature(theme.set).parameters)
    values = {}
    for name, key in pairs.items():
        values[name] = LIGHT[key]
        if f"{name}_dark" in allowed:
            values[f"{name}_dark"] = DARK[key]
    return theme.set(
        **values,
        button_primary_text_color="#FFFFFF", button_primary_text_color_dark="#FFFFFF",
        button_primary_background_fill_hover="#0B6BD0", button_primary_background_fill_hover_dark="#388BFD",
        block_shadow="none", block_shadow_dark="none", input_shadow="none", input_shadow_dark="none",
        block_radius="6px", input_radius="4px", button_large_radius="4px", button_small_radius="4px",
    )
