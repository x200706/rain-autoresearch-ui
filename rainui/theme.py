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


# 使用者可選的主題色（頂列八個小方塊）。藍色就是上面 LIGHT／DARK 原本的配色，不另外覆寫。
# 每種顏色：淺色模式（文字與連結、按鈕、按鈕滑過、淡底）與深色模式（同上）
ACCENTS = {
    "pink":   ("粉", dict(accent="#C2185B", btn="#EC4899", hover="#F472B6", sel="#FBE0EC"),
               dict(accent="#F48FB1", btn="#EC4899", hover="#F472B6", sel="#3D1426")),
    "orange": ("橙", dict(accent="#C2410C", btn="#EA580C", hover="#F97316", sel="#FDE6D8"),
               dict(accent="#FDBA74", btn="#EA580C", hover="#F97316", sel="#3B1D0C")),
    # 黃色按鈕要夠亮才不像棕色，白字看不清楚，按鈕文字改深色（on）
    "yellow": ("黃", dict(accent="#946200", btn="#EAB308", hover="#FACC15", sel="#FBF0C9", on="#1F1A05"),
               dict(accent="#FDE047", btn="#EAB308", hover="#FACC15", sel="#3A2F07", on="#1F1A05")),
    # 淺色模式用偏黃的翠綠；按鈕夠亮，白字不清楚，按鈕文字改深色
    "green":  ("綠", dict(accent="#4E7F1F", btn="#7CB342", hover="#8BC34A", sel="#E6F2D6", on="#14240A"),
               dict(accent="#86EFAC", btn="#238636", hover="#2EA043", sel="#0E2A17")),
    "blue":   ("藍", dict(accent=LIGHT["accent"], btn=LIGHT["btn"], hover="#0B6BD0", sel=LIGHT["sel"]),
               dict(accent=DARK["accent"], btn=DARK["btn"], hover="#388BFD", sel=DARK["sel"])),
    # 初音色 #39C5BB；按鈕夠亮，白字不清楚，按鈕文字改深色
    "teal":   ("湖藍", dict(accent="#138A82", btn="#39C5BB", hover="#5DD3CA", sel="#D7F4F1", on="#062F2C"),
               dict(accent="#7FE0D8", btn="#39C5BB", hover="#5DD3CA", sel="#0B2B29", on="#062F2C")),
    "purple": ("紫", dict(accent="#6D28D9", btn="#6D28D9", hover="#7C3AED", sel="#EDE5FD"),
               dict(accent="#C4B5FD", btn="#7C3AED", hover="#8B5CF6", sel="#24163F")),
    "gray":   ("灰", dict(accent="#475569", btn="#475569", hover="#64748B", sel="#E5E9F0"),
               dict(accent="#CBD5E1", btn="#475569", hover="#64748B", sel="#1E2632")),
}
DEFAULT_ACCENT = "blue"
# 小方塊本身的顏色：深淺色都用同一個中間色，淺色模式也不會太深
SWATCH = {"pink": "#EC4899", "orange": "#F97316", "yellow": "#EAB308", "green": "#7CB342", "blue": "#3B82F6",
          "teal": "#39C5BB", "purple": "#A855F7", "gray": "#94A3B8"}
# 底色、框線、次要文字：原本偏藍灰的中性色，換主題時把色相轉到主題色（灰色則去掉彩度）
NEUTRALS = {"bg": ["--body-background-fill", "--bg", "--bg-dark"],   # Gradio 的頁面底色另外用 --bg／--bg-dark
            "bar": ["--background-fill-secondary"],
            "panel": ["--background-fill-primary", "--block-background-fill", "--panel-background-fill",
                      "--table-even-background-fill", "--block-label-background-fill"],
            "editor": ["--code-background-fill", "--table-odd-background-fill"],
            "input": ["--input-background-fill", "--button-secondary-background-fill",
                      "--checkbox-label-background-fill"],
            "border": ["--block-border-color", "--border-color-primary", "--panel-border-color",
                       "--input-border-color", "--button-secondary-border-color", "--table-border-color"],
            "muted": ["--body-text-color-subdued", "--block-label-text-color", "--block-info-text-color"]}


def _hex_to_hls(color: str):
    import colorsys
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def _rehue(color: str, hue: float, sat_scale: float = 1.0) -> str:
    import colorsys
    _, l, s = _hex_to_hls(color)
    r, g, b = colorsys.hls_to_rgb(hue, l, min(1.0, s * sat_scale))
    return "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))


def _neutral_vars(base: dict, key: str) -> str:
    hue = _hex_to_hls(SWATCH[key])[0]
    sat = 0.0 if key == "gray" else 1.0
    return "".join(f"{var}:{_rehue(base[token], hue, sat)};" for token, names in NEUTRALS.items() for var in names)


def _accent_vars(c: dict) -> str:
    return (f"--ra-accent:{c['accent']};--ra-token:{c['accent']};"
            f"--ra-token-bg:color-mix(in srgb,{c['accent']} 12%,transparent);"
            f"--color-accent:{c['accent']};--border-color-accent:{c['accent']};--link-text-color:{c['accent']};"
            f"--link-text-color-hover:{c['accent']};--link-text-color-visited:{c['accent']};"
            f"--input-border-color-focus:{c['accent']};--color-accent-soft:{c['sel']};"
            f"--checkbox-label-background-fill-selected:{c['sel']};"
            f"--button-primary-background-fill:{c['btn']};--button-primary-border-color:{c['btn']};"
            f"--button-primary-background-fill-hover:{c['hover']};--button-primary-border-color-hover:{c['hover']};"
            f"--checkbox-background-color-selected:{c['btn']};--checkbox-border-color-selected:{c['btn']};"
            f"--button-primary-text-color:{c.get('on', '#FFFFFF')};--button-primary-text-color-hover:{c.get('on', '#FFFFFF')};"
            f"--ra-on-accent:{c.get('on', '#FFFFFF')};")


def accent_css() -> str:
    """html[data-accent=…] 時覆寫主題色。Gradio 把變數定義在 :root 與 body.dark，所以覆寫寫在 body 上才蓋得過。"""
    rules = []
    for key, (_, light, dark) in ACCENTS.items():
        if key == DEFAULT_ACCENT:
            continue
        # Gradio 會把 style.css 的 .dark 變數改寫到 .gradio-container .contain 上，所以這裡也要蓋到那一層
        rules.append(f'html[data-accent="{key}"] body, '
                     f'html[data-accent="{key}"] body .gradio-container .contain'
                     f'{{{_accent_vars(light)}{_neutral_vars(LIGHT, key)}}}')
        rules.append(f'html[data-accent="{key}"] body.dark, '
                     f'html[data-accent="{key}"] body.dark .gradio-container .contain'
                     f'{{{_accent_vars(dark)}{_neutral_vars(DARK, key)}}}')
    return "\n".join(rules)


def swatches_html() -> str:
    """頂列的主題色小方塊；點了由頁面的 JS 切換並記在瀏覽器（localStorage ra-accent）。"""
    return '<div class="swatches" role="group" aria-label="主題色">' + "".join(
        f'<button type="button" class="swatch" data-accent="{key}" title="{name}" aria-label="主題色：{name}" '
        f'style="--sw:{SWATCH[key]}"></button>'
        for key, (name, light, dark) in ACCENTS.items()) + "</div>"
