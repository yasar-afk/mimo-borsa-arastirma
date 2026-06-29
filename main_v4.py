# ============================================================
# main_v4.py — Trading Bot Trading Bot v4
#
# AMAÇ:
#   v4 stratejisi için ana giriş noktası.
#   v4 = Price Action / Smart Money Concepts (SMC) with Optimized confluences
#   config_v4.yaml kullanır, logs_v4/ dizinine yazar.
#
# ÇALIŞTIRMA:
#   python main_v4.py                    # Döngü modu
#   python main_v4.py --single-run       # Tek seferlik
#   python main_v4.py --top-50           # Top 50 coin tara
# ============================================================

from __future__ import annotations

import os
os.environ["LOG_DIR"] = "logs_v4"
os.environ["CONFIG_FILE"] = "config_v4.yaml"

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import yaml
from src.config.settings import (
    _build_settings_from_yaml,
    Settings,
)
from src.bot.engine import BotEngine
from src.utils.logger import get_logger

logger = get_logger("trading-bot.main_v4")

CONFIG_FILE = "config_v4.yaml"
VERSION_LABEL = "v4"


def load_v4_settings() -> Settings:
    """config_v4.yaml'dan v4 settings yükler."""
    path = Path(CONFIG_FILE)
    if not path.exists():
        logger.error(f"❌ {CONFIG_FILE} bulunamadı!")
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        yaml_data = yaml.safe_load(f) or {}
    cfg = _build_settings_from_yaml(yaml_data)
    # v4 versiyonunu açıkça zorla
    cfg.strategy.version = "v4"
    return cfg


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trading Bot v4 — Price Action & SMC Algo Trading (Optimized)"
    )
    parser.add_argument("--single-run", action="store_true")
    parser.add_argument("--top-50", action="store_true")
    parser.add_argument("--top-100", action="store_true")
    parser.add_argument("--top", type=int, default=None)
    parser.add_argument("--symbols", type=str, default=None)
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--tf", type=str, default=None)
    parser.add_argument(
        "--mode",
        type=str,
        choices=["paper", "live"],
        default=None,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_v4_settings()

    logger.info("=" * 60)
    logger.info(f"🚀 Trading Bot {VERSION_LABEL} — Price Action & SMC Bot Başlatılıyor")
    logger.info("=" * 60)
    logger.info(f"📌 Strateji: {cfg.strategy.version}")
    logger.info(f"📁 Log dizini: {cfg.logging.log_dir}")

    # CLI override'lar
    if args.symbol:
        cfg.exchange.symbol = args.symbol
    if args.tf:
        cfg.data.timeframes = [t.strip() for t in args.tf.split(",")]
    if args.mode:
        cfg.trading_mode = args.mode
        if args.mode == "live" and not cfg.has_api_credentials:
            logger.error("❌ Canlı modda API anahtarları gereklidir.")
            sys.exit(1)

    symbols_list = (
        [s.strip() for s in args.symbols.split(",")]
        if args.symbols
        else None
    )

    bot = BotEngine(settings=cfg)
    bot.run(
        single_run=args.single_run,
        symbols=symbols_list,
        top_50=args.top_50,
        top_100=args.top_100,
        top_n=args.top,
    )


if __name__ == "__main__":
    main()
