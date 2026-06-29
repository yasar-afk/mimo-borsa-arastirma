# -*- coding: utf-8 -*-
# ============================================================
# dashboard/app.py — Ana Dash Uygulaması
#
# ÇALIŞTIRMA:
#   python dashboard/app.py
#   veya: dashboard_baslat.bat
#
# AÇILIR: http://localhost:8050
# ============================================================

from __future__ import annotations

import sys
import os
from pathlib import Path

# Proje kök dizinini Python path'ine ekle
ROOT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT_DIR))

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import dash
import dash_bootstrap_components as dbc
from dash import html

from dashboard.layout import build_layout
from dashboard.callbacks import register_callbacks


# ─── Uygulama Başlat ───────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[
        dbc.themes.DARKLY,
        "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap",
    ],
    suppress_callback_exceptions=True,
    title="Trading Bot Dashboard",
    update_title=None,
    meta_tags=[
        {"name": "viewport", "content": "width=device-width, initial-scale=1"},
        {"name": "description", "content": "Trading Bot Trading Bot — Canlı Dashboard"},
    ],
)

# Layout'u bağla
app.layout = build_layout()

# Callback'leri kaydet
register_callbacks(app)


# ─── Başlatma ──────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", 8050))
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")

    print("=" * 60)
    print("  ⚡ Trading Bot Trading Dashboard")
    print(f"  🌐 Adres: http://{host}:{port}")
    print("  📊 Otomatik yenileme: 30 saniye")
    print("  🛑 Durdurmak için: Ctrl+C")
    print("=" * 60)

    app.run(
        debug=False,
        host=host,
        port=port,
        dev_tools_hot_reload=False,
    )
