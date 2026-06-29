# -*- coding: utf-8 -*-
# ============================================================
# dashboard/callbacks.py — Dash Callback'leri
#
# AMAÇ:
#   Kullanıcı etkileşimleri ve otomatik yenileme için
#   tüm Dash callback fonksiyonlarını tanımlar.
# ============================================================

from __future__ import annotations

from datetime import datetime
from typing import Any

import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback_context, html
from dash.exceptions import PreventUpdate

from dashboard.data_provider import (
    add_indicators,
    fetch_ohlcv,
    get_available_symbols,
    get_closed_trades_df,
    get_daily_pnl,
    get_equity_curve,
    get_open_positions_df,
    get_portfolio_metrics,
    load_signals,
)
from dashboard.chart_engine import (
    candlestick_chart,
    close_reason_pie,
    confidence_histogram,
    daily_pnl_chart,
    empty_figure,
    equity_curve_chart,
    pnl_scatter,
    signal_type_bar,
    symbol_pnl_bar,
    win_rate_gauge,
)


def _table_row_style(pnl: float) -> dict:
    """PnL değerine göre satır rengi."""
    if pnl > 0:
        return {"color": "#3fb950", "fontSize": "12px"}
    elif pnl < 0:
        return {"color": "#f85149", "fontSize": "12px"}
    return {"color": "#e6edf3", "fontSize": "12px"}


def _format_cell(val) -> str:
    import pandas as pd
    if val is None or pd.isna(val) or str(val).lower() in ("nan", "nat", "<na>", "none"):
        return "—"
    return str(val)


def _make_table(df, columns=None, max_rows=50) -> html.Table:
    """DataFrame'den styled HTML tablosu üretir."""
    if df is None or df.empty:
        return html.Div("Veri bulunamadı", style={"color": "#8b949e", "padding": "16px"})

    if columns is None:
        columns = df.columns.tolist()

    header_style = {
        "background": "#21262d",
        "padding": "8px 12px",
        "textAlign": "left",
        "fontSize": "11px",
        "color": "#8b949e",
        "textTransform": "uppercase",
        "letterSpacing": "0.5px",
        "borderBottom": "1px solid #30363d",
        "whiteSpace": "nowrap",
    }
    cell_style = {
        "padding": "7px 12px",
        "fontSize": "12px",
        "borderBottom": "1px solid #21262d",
        "whiteSpace": "nowrap",
    }

    return html.Table(
        [
            html.Thead(html.Tr([html.Th(c, style=header_style) for c in columns])),
            html.Tbody([
                html.Tr([
                    html.Td(
                        _format_cell(row[c]) if c in row.index else "—",
                        style={
                            **cell_style,
                            **({"color": "#3fb950"} if c == "PnL ($)" and row.get(c, 0) > 0
                               else {"color": "#f85149"} if c == "PnL ($)" and row.get(c, 0) < 0
                               else {}),
                        }
                    )
                    for c in columns
                ])
                for _, row in df.head(max_rows).iterrows()
            ]),
        ],
        style={
            "width": "100%",
            "borderCollapse": "collapse",
            "color": "#e6edf3",
        }
    )


def register_callbacks(app) -> None:
    """Tüm callback'leri Dash app'e kayıt eder."""

    # ─── Sembol Dropdown'ını Doldur ────────────────────────
    # signals.jsonl'daki TÜM sembolleri yükler (bot'un taradığı ~100 çift)

    @app.callback(
        Output("chart-symbol", "options"),
        Input("auto-refresh", "n_intervals"),
    )
    def populate_symbol_dropdown(n):
        symbols = get_available_symbols()
        # BTC/USDT'yi listenin başına al
        prioritized = []
        top = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
        for s in top:
            if s in symbols:
                prioritized.append(s)
        rest = [s for s in symbols if s not in top]
        final = prioritized + rest
        return [{"label": s, "value": s} for s in final]

    # ─── Metrik Kartları ───────────────────────────────────

    @app.callback(
        [
            Output("metric-balance", "children"),
            Output("metric-pnl", "children"),
            Output("metric-winrate", "children"),
            Output("metric-trades", "children"),
            Output("metric-drawdown", "children"),
            Output("metric-open", "children"),
            Output("last-update-time", "children"),
        ],
        Input("auto-refresh", "n_intervals"),
    )
    def update_metrics(n):
        m = get_portfolio_metrics()
        pnl_color = "#3fb950" if m["total_pnl"] >= 0 else "#f85149"
        pnl_str = f"${m['total_pnl']:+.2f}"
        return (
            f"${m['balance']:,.2f}",
            html.Span(pnl_str, style={"color": pnl_color}),
            f"%{m['win_rate']:.1f}",
            str(m["total_trades"]),
            f"${m['max_drawdown']:.2f}",
            str(m["open_count"]),
            f"Son güncelleme: {datetime.now().strftime('%H:%M:%S')}",
        )

    # ─── Equity Curve ──────────────────────────────────────

    @app.callback(
        Output("equity-curve", "figure"),
        Input("auto-refresh", "n_intervals"),
    )
    def update_equity_curve(n):
        df = get_equity_curve()
        return equity_curve_chart(df)

    # ─── Win Rate Gauge ────────────────────────────────────

    @app.callback(
        Output("win-rate-gauge", "figure"),
        Input("auto-refresh", "n_intervals"),
    )
    def update_gauge(n):
        m = get_portfolio_metrics()
        return win_rate_gauge(m["win_rate"])

    # ─── Günlük PnL ────────────────────────────────────────

    @app.callback(
        Output("daily-pnl-bar", "figure"),
        Input("auto-refresh", "n_intervals"),
    )
    def update_daily_pnl(n):
        df = get_daily_pnl()
        return daily_pnl_chart(df)

    # ─── Açık Pozisyonlar ──────────────────────────────────

    @app.callback(
        Output("open-positions-table", "children"),
        Input("auto-refresh", "n_intervals"),
    )
    def update_open_positions(n):
        df = get_open_positions_df()
        cols = ["Sembol", "Kategori", "Yön", "Giriş", "Anlık", "PnL ($)", "PnL (%)", "SL", "TP", "Açılış"]
        return _make_table(df, columns=[c for c in cols if c in df.columns] if not df.empty else cols)

    # ─── İşlem Geçmişi Grafikleri ─────────────────────────

    @app.callback(
        [
            Output("pnl-scatter", "figure"),
            Output("close-reason-pie", "figure"),
            Output("symbol-pnl-bar", "figure"),
            Output("closed-trades-table", "children"),
        ],
        Input("auto-refresh", "n_intervals"),
    )
    def update_trade_charts(n):
        df = get_closed_trades_df()
        cols = ["Sembol", "Yön", "Giriş Tarihi", "Çıkış ($)", "PnL ($)", "PnL (%)", "Süre (saat)", "Kapanış Sebebi"]
        table_cols = [c for c in cols if not df.empty and c in df.columns]
        return (
            pnl_scatter(df),
            close_reason_pie(df),
            symbol_pnl_bar(df),
            _make_table(df, columns=table_cols if table_cols else None),
        )

    # ─── Sinyal Grafikleri ─────────────────────────────────

    @app.callback(
        [
            Output("signal-type-bar", "figure"),
            Output("confidence-histogram", "figure"),
            Output("signals-live-table", "children"),
        ],
        [
            Input("auto-refresh", "n_intervals"),
            Input("signal-filter", "value"),
        ],
    )
    def update_signal_charts(n, filter_value):
        df = load_signals(limit=1000)

        # İstatistik grafikleri için tüm veri
        sig_bar = signal_type_bar(df)
        conf_hist = confidence_histogram(df)

        # Tablo için filtre uygula
        table_df = df.copy() if not df.empty else df
        if not table_df.empty and filter_value and filter_value != "ALL":
            if filter_value == "TRADE":
                table_df = table_df[table_df["signal_type"].isin(["BUY", "SELL"])]
            else:
                table_df = table_df[table_df["signal_type"] == filter_value]

        # Gösterilecek kolonlar
        show_cols = []
        if not table_df.empty:
            for c in ["generated_at", "symbol", "timeframe", "signal_type", "category",
                      "confidence", "weighted_score", "entry_price", "price"]:
                if c in table_df.columns:
                    show_cols.append(c)

        # Tarih formatla
        if not table_df.empty and "generated_at" in table_df.columns:
            table_df = table_df.copy()
            table_df["generated_at"] = table_df["generated_at"].astype(str).str[:16]

        table = _make_table(
            table_df.sort_values("generated_at", ascending=False).head(50) if not table_df.empty else table_df,
            columns=show_cols,
        )
        return sig_bar, conf_hist, table

    # ─── Candlestick Grafik ────────────────────────────────

    @app.callback(
        Output("candlestick-chart", "figure"),
        [
            Input("chart-refresh-btn", "n_clicks"),
            Input("chart-symbol", "value"),
            Input("chart-timeframe", "value"),
        ],
        prevent_initial_call=False,
    )
    def update_candlestick(n_clicks, symbol, timeframe):
        sym = symbol or "BTC/USDT"
        tf = timeframe or "1h"

        ohlcv = fetch_ohlcv(sym, tf, limit=200)
        ohlcv = add_indicators(ohlcv)
        positions = get_open_positions_df()
        trades = get_closed_trades_df()   # ← alış/satış noktaları için
        return candlestick_chart(ohlcv, symbol=sym, positions=positions, trades=trades)
