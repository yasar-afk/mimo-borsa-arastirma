# -*- coding: utf-8 -*-
# ============================================================
# dashboard/chart_engine.py — Plotly Grafik Motoru
#
# AMAÇ:
#   Tüm Plotly grafiklerini üreten merkezi modül.
#   Dashboard'un her sekmesi bu modülden grafik alır.
# ============================================================

from __future__ import annotations

from typing import Optional
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

# ─── Tema Renkleri ─────────────────────────────────────────

THEME = {
    "bg": "#0d1117",
    "card_bg": "#161b22",
    "border": "#30363d",
    "text": "#e6edf3",
    "muted": "#8b949e",
    "green": "#3fb950",
    "red": "#f85149",
    "blue": "#58a6ff",
    "purple": "#bc8cff",
    "orange": "#d29922",
    "candle_up": "#26a69a",
    "candle_down": "#ef5350",
}

LAYOUT_BASE = dict(
    paper_bgcolor=THEME["bg"],
    plot_bgcolor=THEME["card_bg"],
    font=dict(color=THEME["text"], family="Inter, sans-serif", size=12),
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(
        bgcolor=THEME["card_bg"],
        bordercolor=THEME["border"],
        borderwidth=1,
        font=dict(size=11),
    ),
    xaxis=dict(
        gridcolor=THEME["border"],
        showgrid=True,
        zeroline=False,
    ),
    yaxis=dict(
        gridcolor=THEME["border"],
        showgrid=True,
        zeroline=False,
    ),
)


def _apply_theme(fig: go.Figure, title: str = "") -> go.Figure:
    """Standart karanlık tema uygular."""
    layout = dict(**LAYOUT_BASE)
    if title:
        layout["title"] = dict(text=title, font=dict(size=14, color=THEME["text"]))
    fig.update_layout(**layout)
    return fig


# ─── 1. Equity Curve ───────────────────────────────────────

def equity_curve_chart(df: pd.DataFrame, start_balance: float = 10000.0) -> go.Figure:
    """Portföy değer eğrisini çizer."""
    fig = go.Figure()

    if df.empty:
        fig.add_annotation(
            text="Henüz işlem yok — Equity curve oluşacak",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color=THEME["muted"])
        )
        return _apply_theme(fig, "Equity Curve")

    color = THEME["green"] if df["Bakiye"].iloc[-1] >= start_balance else THEME["red"]

    fig.add_trace(go.Scatter(
        x=df["Tarih"],
        y=df["Bakiye"],
        mode="lines",
        name="Bakiye (USDT)",
        line=dict(color=color, width=2.5),
        fill="tozeroy",
        fillcolor=f"rgba({_hex_to_rgb(color)}, 0.08)",
    ))

    # Başlangıç çizgisi
    fig.add_hline(
        y=start_balance,
        line_dash="dash",
        line_color=THEME["muted"],
        annotation_text="Başlangıç",
        annotation_font_color=THEME["muted"],
    )

    fig.update_layout(
        yaxis_tickprefix="$",
        hovermode="x unified",
    )
    return _apply_theme(fig, "📈 Equity Curve (Portföy Büyüme)")


# ─── 2. Candlestick + Bollinger + RSI ─────────────────────

def candlestick_chart(df: pd.DataFrame, symbol: str = "BTC/USDT",
                      positions: Optional[pd.DataFrame] = None,
                      trades: Optional[pd.DataFrame] = None) -> go.Figure:
    """OHLCV mum grafiği + Bollinger + RSI + Hacim + Alış/Satış işaretleri."""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="Fiyat verisi yüklenemedi",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color=THEME["muted"])
        )
        return _apply_theme(fig)

    # 3 satırlı subplot: [Fiyat+BB], [Hacim], [RSI]
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.60, 0.20, 0.20],
        vertical_spacing=0.03,
        subplot_titles=("", "Hacim", "RSI (14)"),
    )

    # — Candlestick —
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["open"], high=df["high"],
        low=df["low"], close=df["close"],
        name="OHLCV",
        increasing_line_color=THEME["candle_up"],
        decreasing_line_color=THEME["candle_down"],
        increasing_fillcolor=THEME["candle_up"],
        decreasing_fillcolor=THEME["candle_down"],
        whiskerwidth=0.3,
    ), row=1, col=1)

    # — Bollinger Bantları —
    if "bb_upper" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_upper"],
            name="BB Üst", line=dict(color=THEME["blue"], width=1, dash="dot"),
            showlegend=True,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_mid"],
            name="BB Orta (SMA20)", line=dict(color=THEME["muted"], width=1),
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["bb_lower"],
            name="BB Alt", line=dict(color=THEME["blue"], width=1, dash="dot"),
            fill="tonexty",
            fillcolor=f"rgba({_hex_to_rgb(THEME['blue'])}, 0.05)",
        ), row=1, col=1)

    # — EMA —
    if "ema20" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema20"],
            name="EMA 20", line=dict(color=THEME["orange"], width=1.2),
        ), row=1, col=1)
    if "ema50" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema50"],
            name="EMA 50", line=dict(color=THEME["purple"], width=1.2),
        ), row=1, col=1)

    # — Kapalı İşlem Alış/Satış/Çıkış Noktaları ▲▼■ —
    if trades is not None and not trades.empty:
        sym_short = symbol.replace("/USDT", "")
        trade_df = trades[trades["Sembol"].str.replace("/USDT", "") == sym_short].copy()

        if not trade_df.empty:
            entries_long  = trade_df[trade_df["Yön"] == "LONG"]
            entries_short = trade_df[trade_df["Yön"] == "SHORT"]

            # LONG girişler
            if not entries_long.empty and "Giriş Tarihi" in entries_long.columns:
                et  = pd.to_datetime(entries_long["Giriş Tarihi"], errors="coerce")
                ep  = entries_long["Giriş ($)"].values
                pnl = entries_long["PnL ($)"].values
                sym = entries_long["Sembol"].values
                rsn = entries_long["Kapanış Sebebi"].values if "Kapanış Sebebi" in entries_long else [""] * len(entries_long)

                fig.add_trace(go.Scatter(
                    x=et, y=[p * 0.996 for p in ep], mode="markers", name="▲ LONG Giriş",
                    marker=dict(symbol="triangle-up", size=16, color=THEME["green"], opacity=1.0, line=dict(color="#0d1117", width=1.5)),
                    customdata=list(zip(sym, [f"${p:.4f}" for p in ep], [f"${v:+.2f}" for v in pnl], rsn)),
                    hovertemplate="<b>▲ LONG GİRİŞ — %{customdata[0]}</b><br>Giriş: %{customdata[1]}<br>PnL: %{customdata[2]}<br>Sebep: %{customdata[3]}<extra></extra>",
                ), row=1, col=1)

            # SHORT girişler
            if not entries_short.empty and "Giriş Tarihi" in entries_short.columns:
                et  = pd.to_datetime(entries_short["Giriş Tarihi"], errors="coerce")
                ep  = entries_short["Giriş ($)"].values
                pnl = entries_short["PnL ($)"].values
                sym = entries_short["Sembol"].values
                rsn = entries_short["Kapanış Sebebi"].values if "Kapanış Sebebi" in entries_short else [""] * len(entries_short)

                fig.add_trace(go.Scatter(
                    x=et, y=[p * 1.004 for p in ep], mode="markers", name="▼ SHORT Giriş",
                    marker=dict(symbol="triangle-down", size=16, color=THEME["red"], opacity=1.0, line=dict(color="#0d1117", width=1.5)),
                    customdata=list(zip(sym, [f"${p:.4f}" for p in ep], [f"${v:+.2f}" for v in pnl], rsn)),
                    hovertemplate="<b>▼ SHORT GİRİŞ — %{customdata[0]}</b><br>Giriş: %{customdata[1]}<br>PnL: %{customdata[2]}<br>Sebep: %{customdata[3]}<extra></extra>",
                ), row=1, col=1)

            # Çıkışlar
            if "Çıkış Tarihi" in trade_df.columns and "Çıkış ($)" in trade_df.columns:
                xt  = pd.to_datetime(trade_df["Çıkış Tarihi"], errors="coerce")
                xp  = trade_df["Çıkış ($)"].values
                pnl = trade_df["PnL ($)"].values
                sym = trade_df["Sembol"].values
                rsn = trade_df["Kapanış Sebebi"].values if "Kapanış Sebebi" in trade_df else [""] * len(trade_df)
                exit_colors = [THEME["blue"] if v >= 0 else THEME["orange"] for v in pnl]
                fig.add_trace(go.Scatter(
                    x=xt, y=xp, mode="markers", name="■ Çıkış",
                    marker=dict(symbol="square", size=12, color=exit_colors, opacity=0.95, line=dict(color="#0d1117", width=1.5)),
                    customdata=list(zip(sym, [f"${p:.4f}" for p in xp], [f"${v:+.2f}" for v in pnl], rsn)),
                    hovertemplate="<b>■ ÇIKIŞ — %{customdata[0]}</b><br>Çıkış: %{customdata[1]}<br>PnL: %{customdata[2]}<br>Sebep: %{customdata[3]}<extra></extra>",
                ), row=1, col=1)

            # Bağlantı çizgileri
            for _, row_t in trade_df.iterrows():
                try:
                    t0, t1 = pd.to_datetime(row_t["Giriş Tarihi"]), pd.to_datetime(row_t["Çıkış Tarihi"])
                    p0, p1 = float(row_t["Giriş ($)"]), float(row_t["Çıkış ($)"])
                    pnl_v = float(row_t.get("PnL ($)", 0))
                    line_color = f"rgba({_hex_to_rgb(THEME['green'] if pnl_v >= 0 else THEME['red'])}, 0.35)"
                    fig.add_trace(go.Scatter(x=[t0, t1], y=[p0, p1], mode="lines", showlegend=False, line=dict(color=line_color, width=1.5, dash="dot"), hoverinfo="skip"), row=1, col=1)
                except Exception: pass

    # — Açık Pozisyon Çizgileri —
    if positions is not None and not positions.empty:
        for _, pos in positions.iterrows():
            if pos.get("Sembol", "").replace("/USDT", "") in symbol:
                fig.add_hline(y=pos.get("Giriş", 0), line_color=THEME["blue"], line_dash="dash", annotation_text=f"GİRİŞ ${pos.get('Giriş', 0):,.4f}", row=1, col=1)
                if pos.get("SL", 0) > 0: fig.add_hline(y=pos.get("SL", 0), line_color=THEME["red"], line_dash="dot", row=1, col=1)
                if pos.get("TP", 0) > 0: fig.add_hline(y=pos.get("TP", 0), line_color=THEME["green"], line_dash="dot", row=1, col=1)

    # — Hacim —
    colors = [THEME["candle_up"] if c >= o else THEME["candle_down"] for c, o in zip(df["close"], df["open"])]
    fig.add_trace(go.Bar(x=df.index, y=df["volume"], name="Hacim", marker_color=colors, marker_opacity=0.7, showlegend=False), row=2, col=1)

    # — RSI —
    if "rsi" in df.columns:
        fig.add_trace(go.Scatter(x=df.index, y=df["rsi"], name="RSI", line=dict(color=THEME["blue"], width=1.5), showlegend=False), row=3, col=1)
        fig.add_hline(y=70, line_color=THEME["red"], line_dash="dash", row=3, col=1)
        fig.add_hline(y=30, line_color=THEME["green"], line_dash="dash", row=3, col=1)

    fig.update_layout(xaxis_rangeslider_visible=False, paper_bgcolor=THEME["bg"], plot_bgcolor=THEME["card_bg"], font=dict(color=THEME["text"]), legend=dict(orientation="h", x=0, y=1.02), hovermode="x unified", title=dict(text=f"🕯️ {symbol} — Candlestick", font=dict(size=14)))
    for i in [1, 2, 3]: fig.update_xaxes(gridcolor=THEME["border"], row=i, col=1); fig.update_yaxes(gridcolor=THEME["border"], row=i, col=1)
    fig.update_yaxes(range=[0, 100], row=3, col=1)
    return fig


# ─── 3. Günlük PnL Bar Chart ──────────────────────────────

def daily_pnl_chart(df: pd.DataFrame) -> go.Figure:
    """Günlük kar/zarar bar grafiği."""
    fig = go.Figure()

    if df.empty:
        fig.add_annotation(
            text="Henüz kapalı işlem yok",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color=THEME["muted"])
        )
        return _apply_theme(fig, "Günlük PnL")

    colors = [THEME["green"] if v >= 0 else THEME["red"] for v in df["PnL ($)"]]

    fig.add_trace(go.Bar(
        x=df["Gün"].astype(str),
        y=df["PnL ($)"],
        marker_color=colors,
        name="Günlük PnL",
        text=[f"${v:+.2f}" for v in df["PnL ($)"]],
        textposition="outside",
        textfont=dict(size=10),
    ))

    fig.add_hline(y=0, line_color=THEME["muted"], line_width=1)
    fig.update_layout(yaxis_tickprefix="$", showlegend=False)
    return _apply_theme(fig, "📅 Günlük PnL (USDT)")


# ─── 4. Win Rate Gauge ────────────────────────────────────

def win_rate_gauge(win_rate: float) -> go.Figure:
    """Win rate kadran göstergesi."""
    color = THEME["green"] if win_rate >= 50 else THEME["orange"] if win_rate >= 40 else THEME["red"]

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=win_rate,
        number={"suffix": "%", "font": {"size": 28, "color": color}},
        delta={"reference": 50, "relative": False,
               "increasing": {"color": THEME["green"]},
               "decreasing": {"color": THEME["red"]}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": THEME["text"]},
            "bar": {"color": color},
            "bgcolor": THEME["card_bg"],
            "borderwidth": 1,
            "bordercolor": THEME["border"],
            "steps": [
                {"range": [0, 40], "color": f"rgba({_hex_to_rgb(THEME['red'])}, 0.2)"},
                {"range": [40, 60], "color": f"rgba({_hex_to_rgb(THEME['orange'])}, 0.2)"},
                {"range": [60, 100], "color": f"rgba({_hex_to_rgb(THEME['green'])}, 0.2)"},
            ],
            "threshold": {"line": {"color": THEME["blue"], "width": 3},
                          "thickness": 0.75, "value": 50},
        },
        title={"text": "Win Rate", "font": {"size": 13, "color": THEME["muted"]}},
    ))

    fig.update_layout(
        paper_bgcolor=THEME["bg"],
        font=dict(color=THEME["text"]),
        margin=dict(l=20, r=20, t=30, b=20),
        height=200,
    )
    return fig


# ─── 5. PnL Scatter (Süre vs Kar) ─────────────────────────

def pnl_scatter(df: pd.DataFrame) -> go.Figure:
    """İşlem süresi × PnL scatter grafiği."""
    fig = go.Figure()

    if df.empty:
        fig.add_annotation(
            text="Henüz kapalı işlem yok",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color=THEME["muted"])
        )
        return _apply_theme(fig, "İşlem Süresi vs PnL")

    colors = [THEME["green"] if v >= 0 else THEME["red"] for v in df["PnL ($)"]]
    fig.add_trace(go.Scatter(
        x=df["Süre (saat)"],
        y=df["PnL ($)"],
        mode="markers+text",
        text=df["Sembol"].str.replace("/USDT", ""),
        textposition="top center",
        textfont=dict(size=9),
        marker=dict(color=colors, size=10, opacity=0.8,
                    line=dict(color=THEME["border"], width=1)),
        customdata=df[["Sembol", "Kapanış Sebebi"]].values,
        hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "Süre: %{x:.1f} saat<br>"
            "PnL: $%{y:.2f}<br>"
            "Sebep: %{customdata[1]}<extra></extra>"
        ),
    ))

    fig.add_hline(y=0, line_color=THEME["muted"], line_dash="dash")
    fig.update_layout(
        xaxis_title="Süre (Saat)",
        yaxis_title="PnL ($)",
        yaxis_tickprefix="$",
    )
    return _apply_theme(fig, "⏱️ İşlem Süresi vs Kâr/Zarar")


# ─── 6. Kapanış Sebebi Pie ────────────────────────────────

def close_reason_pie(df: pd.DataFrame) -> go.Figure:
    """Kapanış sebeplerinin dağılımı."""
    fig = go.Figure()

    if df.empty or "Kapanış Sebebi" not in df.columns:
        fig.add_annotation(
            text="Veri yok",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color=THEME["muted"])
        )
        return _apply_theme(fig, "Kapanış Sebepleri")

    counts = df["Kapanış Sebebi"].value_counts()
    color_map = {
        "TP_1": THEME["green"], "TP_2": THEME["green"], "TP_3": THEME["green"],
        "SL": THEME["red"], "TRAILING_SL": THEME["orange"],
        "MANUAL": THEME["blue"], "ROTATE": THEME["purple"],
    }
    colors = [color_map.get(r, THEME["muted"]) for r in counts.index]

    fig.add_trace(go.Pie(
        labels=counts.index,
        values=counts.values,
        hole=0.45,
        marker=dict(colors=colors, line=dict(color=THEME["bg"], width=2)),
        textfont=dict(size=11),
    ))

    return _apply_theme(fig, "🥧 Kapanış Sebepleri")


# ─── 7. Sinyal Türü Bar ───────────────────────────────────

def signal_type_bar(df: pd.DataFrame) -> go.Figure:
    """Sinyal türlerinin dağılım bar grafiği."""
    fig = go.Figure()

    if df.empty or "signal_type" not in df.columns:
        fig.add_annotation(
            text="Sinyal verisi yok",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color=THEME["muted"])
        )
        return _apply_theme(fig, "Sinyal Türleri")

    counts = df["signal_type"].value_counts().reset_index()
    counts.columns = ["Tür", "Sayı"]

    color_map = {
        "BUY": THEME["green"], "SELL": THEME["red"],
        "HOLD": THEME["muted"], "NO_SIGNAL": THEME["border"],
    }
    colors = [color_map.get(t, THEME["blue"]) for t in counts["Tür"]]

    fig.add_trace(go.Bar(
        x=counts["Tür"],
        y=counts["Sayı"],
        marker_color=colors,
        text=counts["Sayı"],
        textposition="outside",
    ))

    return _apply_theme(fig, "📊 Sinyal Türleri Dağılımı")


# ─── 8. Confidence Score Histogram ───────────────────────

def confidence_histogram(df: pd.DataFrame) -> go.Figure:
    """Confidence score dağılımı."""
    fig = go.Figure()

    if df.empty or "confidence" not in df.columns:
        fig.add_annotation(
            text="Veri yok",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color=THEME["muted"])
        )
        return _apply_theme(fig, "Confidence Score")

    valid = df[df["confidence"] > 0]["confidence"] * 100

    fig.add_trace(go.Histogram(
        x=valid,
        nbinsx=20,
        marker_color=THEME["blue"],
        marker_opacity=0.75,
        marker_line=dict(color=THEME["border"], width=1),
        name="Confidence",
    ))

    fig.add_vline(x=65, line_color=THEME["green"], line_dash="dash",
                  annotation_text="Giriş Eşiği (65)", annotation_font_color=THEME["green"])

    fig.update_layout(xaxis_title="Confidence Score (0–100)", yaxis_title="Sinyal Sayısı")
    return _apply_theme(fig, "🎯 Confidence Score Dağılımı")


# ─── 9. Sembol PnL Bar ────────────────────────────────────

def symbol_pnl_bar(df: pd.DataFrame) -> go.Figure:
    """Sembol bazında toplam PnL."""
    fig = go.Figure()

    if df.empty or "Sembol" not in df.columns:
        fig.add_annotation(
            text="Veri yok",
            xref="paper", yref="paper", x=0.5, y=0.5,
            showarrow=False, font=dict(size=14, color=THEME["muted"])
        )
        return _apply_theme(fig, "Sembol PnL")

    grouped = df.groupby("Sembol")["PnL ($)"].sum().sort_values(ascending=False).reset_index()
    colors = [THEME["green"] if v >= 0 else THEME["red"] for v in grouped["PnL ($)"]]

    fig.add_trace(go.Bar(
        x=grouped["Sembol"].str.replace("/USDT", ""),
        y=grouped["PnL ($)"],
        marker_color=colors,
        text=[f"${v:+.2f}" for v in grouped["PnL ($)"]],
        textposition="outside",
    ))

    fig.add_hline(y=0, line_color=THEME["muted"], line_dash="dash")
    fig.update_layout(yaxis_tickprefix="$")
    return _apply_theme(fig, "🏆 Sembol Bazında Toplam PnL")


# ─── Yardımcılar ──────────────────────────────────────────

def _hex_to_rgb(hex_color: str) -> str:
    """#RRGGBB → 'R, G, B' string döndürür."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"{r}, {g}, {b}"


def empty_figure(message: str = "Yükleniyor...") -> go.Figure:
    """Boş/loading placeholder grafik."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=16, color=THEME["muted"])
    )
    return _apply_theme(fig)
