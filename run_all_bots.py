# -*- coding: utf-8 -*-
"""run_all_bots.py — V5 PA + V7 PA tek pencerede"""
import sys
import os
import threading
import time
import signal
import json

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ".")

running = True

def signal_handler(sig, frame):
    global running
    running = False

signal.signal(signal.SIGINT, signal_handler)


def run_v5():
    global running
    try:
        from live_v5 import LiveV5Bot
        bot = LiveV5Bot(initial_capital=10000.0, max_positions=5, position_pct=0.02,
                        is_live=True, top_n=100)
        while running:
            try:
                bot.run_cycle()
            except Exception as e:
                print(f"[V5] Hata: {e}")
            time.sleep(900)
    except Exception as e:
        print(f"[V5] Kritik: {e}")


def run_v7():
    global running
    try:
        from live_v7 import LiveV7Bot
        bot = LiveV7Bot(initial_capital=10000.0, max_positions=10, position_pct=0.02,
                        is_live=True, top_n=100)
        while running:
            try:
                bot.run_cycle()
            except Exception as e:
                print(f"[V7] Hata: {e}")
            time.sleep(900)
    except Exception as e:
        print(f"[V7] Kritik: {e}")


def main():
    global running

    print("=" * 60)
    print("  Trading Bot — V5 + V7 (TEK PENCERE)")
    print("=" * 60)
    print("  V5: Price Action, filtresiz, %2 risk, 50 coin")
    print("  V7: Price Action, filtreli, %2 risk, 100 coin")
    print("  Durdurmak icin: Ctrl+C")
    print("=" * 60)

    try:
        from src.utils.telegram_notifier import send_telegram_notification
        send_telegram_notification(
            "🤖 V5 + V7 BAŞLATILDI\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "V5: PA Filtresiz, %2 risk, 50 coin\n"
            "V7: PA Filtreli, %2 risk, 100 coin"
        )
    except Exception:
        pass

    threads = [
        threading.Thread(target=run_v5, name="V5", daemon=True),
        threading.Thread(target=run_v7, name="V7", daemon=True),
    ]
    for t in threads:
        t.start()
        time.sleep(5)

    try:
        while running:
            time.sleep(1)
    except KeyboardInterrupt:
        running = False
    print("\nDurduruldu.")


if __name__ == "__main__":
    main()
