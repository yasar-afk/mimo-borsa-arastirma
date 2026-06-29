# -*- coding: utf-8 -*-
# ============================================================
# dashboard/layout.py — Dashboard HTML Yapısı
#
# AMAÇ:
#   Dash uygulamasının tüm sekme yapısını ve
#   bileşen yerleşimini tanımlar.
# ============================================================

from __future__ import annotations

import dash_bootstrap_components as dbc
from dash import dcc, html

# ─── Stil Sabitleri ────────────────────────────────────────

CARD_STYLE = {
    "background": "#161b22",
    "border": "1px solid #30363d",
    "borderRadius": "8px",
    "padding": "16px",
    "marginBottom": "12px",
}

METRIC_CARD_STYLE = {
    **CARD_STYLE,
    "textAlign": "center",
    "padding": "20px 12px",
}

HEADER_STYLE = {
    "background": "linear-gradient(135deg, #161b22 0%, #0d1117 100%)",
    "borderBottom": "1px solid #30363d",
    "padding": "16px 24px",
    "marginBottom": "0",
}


def _metric_card(title: str, value_id: str, icon: str = "", color: str = "#58a6ff") -> dbc.Col:
    """Tek metrik kartı bileşeni."""
    return dbc.Col(
        html.Div([
            html.Div(icon, style={"fontSize": "22px", "marginBottom": "4px"}),
            html.Div(title, style={"color": "#8b949e", "fontSize": "11px",
                                   "textTransform": "uppercase", "letterSpacing": "0.5px"}),
            html.Div(id=value_id, children="—",
                     style={"color": color, "fontSize": "22px",
                            "fontWeight": "700", "marginTop": "4px"}),
        ], style=METRIC_CARD_STYLE),
        xs=6, sm=4, md=2,
    )


# ─── Header ────────────────────────────────────────────────

def build_header() -> html.Div:
    return html.Div([
        dbc.Row([
            dbc.Col([
                html.Div([
                    html.Span("⚡", style={"fontSize": "24px", "marginRight": "10px"}),
                    html.Span("Trading Bot", style={
                        "fontSize": "22px", "fontWeight": "800",
                        "background": "linear-gradient(90deg, #58a6ff, #bc8cff)",
                        "WebkitBackgroundClip": "text",
                        "WebkitTextFillColor": "transparent",
                        "letterSpacing": "2px",
                    }),
                    html.Span(" Trading Dashboard", style={
                        "fontSize": "14px", "color": "#8b949e",
                        "marginLeft": "8px", "fontWeight": "400",
                    }),
                ], style={"display": "flex", "alignItems": "center"}),
            ], width=8),
            dbc.Col([
                html.Div([
                    html.Span("🟢 Canlı  ", style={"color": "#3fb950", "fontSize": "12px"}),
                    html.Span(id="last-update-time", children="",
                              style={"color": "#8b949e", "fontSize": "11px"}),
                ], style={"textAlign": "right", "paddingTop": "6px"}),
            ], width=4),
        ]),
    ], style=HEADER_STYLE)


# ─── Metrik Satırı ─────────────────────────────────────────

def build_metrics_row() -> html.Div:
    return html.Div([
        dbc.Row([
            _metric_card("Bakiye", "metric-balance", "💰", "#58a6ff"),
            _metric_card("Toplam PnL", "metric-pnl", "📈", "#3fb950"),
            _metric_card("Win Rate", "metric-winrate", "🎯", "#bc8cff"),
            _metric_card("İşlem Sayısı", "metric-trades", "🔁", "#d29922"),
            _metric_card("Max Drawdown", "metric-drawdown", "📉", "#f85149"),
            _metric_card("Açık Poz.", "metric-open", "🔓", "#58a6ff"),
        ], className="g-2"),
    ], style={"padding": "16px 24px 4px"})


# ─── Sekme 1: Portföy ──────────────────────────────────────

def build_portfolio_tab() -> dbc.Tab:
    return dbc.Tab(
        label="📊 Portföy",
        tab_id="tab-portfolio",
        children=[
            dbc.Row([
                # Sol: Equity Curve
                dbc.Col([
                    html.Div([
                        dcc.Graph(id="equity-curve", style={"height": "300px"},
                                  config={"displayModeBar": False}),
                    ], style=CARD_STYLE),
                ], md=8),
                # Sağ: Win Rate Gauge + Günlük PnL
                dbc.Col([
                    html.Div([
                        dcc.Graph(id="win-rate-gauge", style={"height": "200px"},
                                  config={"displayModeBar": False}),
                    ], style={**CARD_STYLE, "padding": "8px"}),
                    html.Div([
                        dcc.Graph(id="daily-pnl-bar", style={"height": "280px"},
                                  config={"displayModeBar": False}),
                    ], style=CARD_STYLE),
                ], md=4),
            ], className="g-2"),
            # Açık Pozisyonlar Tablosu
            html.Div([
                html.Div("🔓 Açık Pozisyonlar", style={
                    "color": "#58a6ff", "fontWeight": "600",
                    "fontSize": "13px", "marginBottom": "10px",
                }),
                html.Div(id="open-positions-table"),
            ], style=CARD_STYLE),
        ],
    )


# ─── Sekme 2: İşlem Geçmişi ────────────────────────────────

def build_trades_tab() -> dbc.Tab:
    return dbc.Tab(
        label="📈 İşlemler",
        tab_id="tab-trades",
        children=[
            dbc.Row([
                dbc.Col([
                    html.Div([
                        dcc.Graph(id="pnl-scatter", style={"height": "320px"},
                                  config={"displayModeBar": False}),
                    ], style=CARD_STYLE),
                ], md=8),
                dbc.Col([
                    html.Div([
                        dcc.Graph(id="close-reason-pie", style={"height": "320px"},
                                  config={"displayModeBar": False}),
                    ], style=CARD_STYLE),
                ], md=4),
            ], className="g-2"),
            dbc.Row([
                dbc.Col([
                    html.Div([
                        dcc.Graph(id="symbol-pnl-bar", style={"height": "280px"},
                                  config={"displayModeBar": False}),
                    ], style=CARD_STYLE),
                ], md=12),
            ]),
            # Kapalı İşlemler Tablosu
            html.Div([
                html.Div("📋 Kapalı İşlemler Geçmişi", style={
                    "color": "#58a6ff", "fontWeight": "600",
                    "fontSize": "13px", "marginBottom": "10px",
                }),
                html.Div(id="closed-trades-table"),
            ], style=CARD_STYLE),
        ],
    )


# ─── Sekme 3: Sinyal Monitörü ──────────────────────────────

def build_signals_tab() -> dbc.Tab:
    return dbc.Tab(
        label="🔍 Sinyaller",
        tab_id="tab-signals",
        children=[
            dbc.Row([
                dbc.Col([
                    html.Div([
                        dcc.Graph(id="signal-type-bar", style={"height": "280px"},
                                  config={"displayModeBar": False}),
                    ], style=CARD_STYLE),
                ], md=6),
                dbc.Col([
                    html.Div([
                        dcc.Graph(id="confidence-histogram", style={"height": "280px"},
                                  config={"displayModeBar": False}),
                    ], style=CARD_STYLE),
                ], md=6),
            ], className="g-2"),
            # Canlı Sinyal Tablosu
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Div("📡 Son Sinyaller (Canlı)", style={
                            "color": "#58a6ff", "fontWeight": "600", "fontSize": "13px",
                        }),
                    ], width=8),
                    dbc.Col([
                        dbc.Select(
                            id="signal-filter",
                            options=[
                                {"label": "Tümü", "value": "ALL"},
                                {"label": "Sadece BUY/SELL", "value": "TRADE"},
                                {"label": "HOLD", "value": "HOLD"},
                                {"label": "NO_SIGNAL", "value": "NO_SIGNAL"},
                            ],
                            value="ALL",
                            style={"background": "#161b22", "color": "#e6edf3",
                                   "border": "1px solid #30363d", "fontSize": "12px"},
                        ),
                    ], width=4),
                ], style={"marginBottom": "10px"}),
                html.Div(id="signals-live-table"),
            ], style=CARD_STYLE),
        ],
    )


# ─── Sekme 4: Candlestick Grafik ───────────────────────────

def build_chart_tab() -> dbc.Tab:
    return dbc.Tab(
        label="🕯️ Grafik",
        tab_id="tab-chart",
        children=[
            # Kontroller
            html.Div([
                dbc.Row([
                    dbc.Col([
                        html.Label("Sembol", style={"color": "#8b949e", "fontSize": "11px"}),
                        dbc.Select(
                            id="chart-symbol",
                            options=[],          # ← callback ile doldurulacak
                            value="BTC/USDT",
                            style={"background": "#161b22", "color": "#e6edf3",
                                   "border": "1px solid #30363d"},
                        ),
                    ], md=4),
                    dbc.Col([
                        html.Label("Zaman Dilimi", style={"color": "#8b949e", "fontSize": "11px"}),
                        dbc.RadioItems(
                            id="chart-timeframe",
                            options=[
                                {"label": "15m", "value": "15m"},
                                {"label": "1h", "value": "1h"},
                                {"label": "4h", "value": "4h"},
                                {"label": "1d", "value": "1d"},
                            ],
                            value="1h",
                            inline=True,
                            style={"color": "#e6edf3"},
                            inputStyle={"marginRight": "4px"},
                            labelStyle={"marginRight": "16px", "cursor": "pointer"},
                        ),
                    ], md=5),
                    dbc.Col([
                        html.Label(" ", style={"display": "block"}),
                        dbc.Button(
                            "🔄 Yenile",
                            id="chart-refresh-btn",
                            color="secondary",
                            size="sm",
                            style={"background": "#21262d", "border": "1px solid #30363d"},
                        ),
                    ], md=3),
                ], className="g-2 align-items-end"),
            ], style={**CARD_STYLE, "marginBottom": "8px", "padding": "12px 16px"}),

            # Candlestick Ana Grafik
            html.Div([
                dcc.Graph(
                    id="candlestick-chart",
                    style={"height": "600px"},
                    config={"displayModeBar": True, "scrollZoom": True},
                ),
            ], style=CARD_STYLE),
        ],
    )


# ─── Ana Layout ────────────────────────────────────────────

def build_layout() -> html.Div:
    """Tüm dashboard layout'unu döndürür."""
    return html.Div([
        # Header
        build_header(),

        # Metrik kartları
        build_metrics_row(),

        # Tab yapısı
        html.Div([
            dbc.Tabs(
                id="main-tabs",
                active_tab="tab-portfolio",
                children=[
                    build_portfolio_tab(),
                    build_trades_tab(),
                    build_signals_tab(),
                    build_chart_tab(),
                ],
                style={"borderBottom": "1px solid #30363d"},
            ),
        ], style={"padding": "0 24px 24px"}),

        # Otomatik yenileme (30 saniye)
        dcc.Interval(
            id="auto-refresh",
            interval=30 * 1000,
            n_intervals=0,
        ),

        # Grafik sekme için manuel yenileme trigger
        dcc.Store(id="chart-trigger", data=0),

    ], style={
        "background": "#0d1117",
        "minHeight": "100vh",
        "fontFamily": "Inter, -apple-system, sans-serif",
        "color": "#e6edf3",
    })
