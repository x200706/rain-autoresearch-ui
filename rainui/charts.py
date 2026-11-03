"""Plotly 圖表。背景透明、文字與格線顏色交給 CSS（跟著深淺色模式變），圖本身可拖曳放大。"""
import pandas as pd
import plotly.graph_objects as go

ACCENT = "#4D8EF7"
ACTUAL = "#3B82F6"
PRED = "#EF4444"
MUTED = "#8592A6"
GRID = "rgba(133,146,166,0.22)"


def _layout(fig: go.Figure, height: int, ytitle: str, xtitle: str) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=56, r=16, t=16, b=44), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font=dict(family="JetBrains Mono, Segoe UI, Microsoft JhengHei", size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0, bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified", dragmode="zoom",
    )
    fig.update_xaxes(title_text=xtitle, gridcolor=GRID, zeroline=False, linecolor=GRID)
    fig.update_yaxes(title_text=ytitle, gridcolor=GRID, zeroline=False, linecolor=GRID, rangemode="tozero")
    return fig


def convergence(conv: list[dict]) -> go.Figure:
    fig = go.Figure()
    pts = [c for c in conv if c.get("best") is not None]
    if pts:
        fig.add_trace(go.Scatter(x=[int(c["g"]) for c in pts], y=[float(c["best"]) for c in pts], name="目前最佳",
                                 mode="lines+markers", line=dict(color=ACCENT, width=3, shape="hv")))
        passed = [c for c in pts if c.get("pass") is not None]
        fig.add_trace(go.Scatter(x=[int(c["g"]) for c in passed], y=[float(c["pass"]) for c in passed], name="該代最低",
                                 mode="lines+markers", line=dict(color=MUTED, width=1.5, dash="dash")))
    fig = _layout(fig, 300, "≥ 40 mm MAE（mm）", "代數")
    fig.update_layout(dragmode=False)                       # 收斂圖只有十幾個點，不需要縮放
    fig.update_xaxes(dtick=1, fixedrange=True)
    fig.update_yaxes(rangemode="normal", fixedrange=True)
    return fig


def predictions(frame: pd.DataFrame | None, title: str) -> go.Figure:
    fig = go.Figure()
    if frame is None or frame.empty:
        fig.add_annotation(text="沒有預測檔（展示資料或尚未完成）", showarrow=False, font=dict(size=15))
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
        return _layout(fig, 360, "", "")
    # Gradio 5 附的 plotly.js 讀不懂 plotly 6 的二進位陣列格式（會畫成亂掉的遞增線），一律轉成一般清單
    x = frame["datetime"].dt.strftime("%Y-%m-%d %H:%M").tolist()
    # 觀測先畫在下層，預測畫在上層
    fig.add_trace(go.Scattergl(x=x, y=frame["actual"].round(2).tolist(), name="觀測雨量", mode="lines",
                               line=dict(color=ACTUAL, width=1)))
    fig.add_trace(go.Scattergl(x=x, y=frame["pred"].round(2).tolist(), name="預測雨量（雙分類器＋有雨 LSTM）",
                               mode="lines", line=dict(color=PRED, width=1)))
    fig = _layout(fig, 420, "逐時雨量（mm）", title)
    fig.update_xaxes(rangeslider=dict(visible=True, thickness=0.08, bgcolor="rgba(133,146,166,0.08)"))
    return fig
