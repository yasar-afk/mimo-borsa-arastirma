# ============================================================
# src/utils/telegram_listener.py — Telegram Command Listener
# Komutlar:
#   /durum veya "durum" → Açık pozisyonlar + K/Z
# ============================================================

import json
import urllib.request
import urllib.parse
import threading
import time
import sys
from typing import Any
from src.utils.logger import get_logger
from src.utils.telegram_notifier import send_telegram_notification

logger = get_logger(__name__)


def format_price(price: float) -> str:
    if price is None or price == 0:
        return "-"
    if price >= 100:
        return f"${price:,.2f}"
    elif price >= 1.0:
        return f"${price:,.4f}"
    elif price >= 0.0001:
        return f"${price:,.6f}"
    else:
        return f"${price:,.8f}"


class TelegramListener(threading.Thread):
    def __init__(self, token: str, chat_id: str, execution_engine: Any) -> None:
        super().__init__(daemon=True)
        self.token = token
        self.chat_id = str(chat_id)
        self.engine = execution_engine
        self.last_update_id = 0
        self.running = True

    def run(self) -> None:
        if "pytest" in sys.modules:
            return

        logger.info("Telegram listener baslatildi.")
        
        try:
            url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset=-1&limit=1"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                res = json.loads(resp.read().decode('utf-8'))
                if res.get("ok") and res.get("result"):
                    self.last_update_id = res["result"][0]["update_id"]
        except Exception:
            pass

        while self.running:
            try:
                url = f"https://api.telegram.org/bot{self.token}/getUpdates?offset={self.last_update_id + 1}&timeout=10"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res = json.loads(resp.read().decode('utf-8'))
                    if res.get("ok") and res.get("result"):
                        for update in res["result"]:
                            self.last_update_id = update["update_id"]
                            
                            msg = update.get("message") or update.get("edited_message")
                            if not msg:
                                continue
                            
                            text = msg.get("text", "").strip().lower()
                            chat_id_from_msg = str(msg.get("chat", {}).get("id"))
                            
                            if chat_id_from_msg != self.chat_id:
                                continue

                            # /durum komutu
                            if any(cmd in text for cmd in ["durum", "status", "portfoy", "pozisyon", "acik"]):
                                self._send_durum()
                                
            except Exception as e:
                if "409" in str(e):
                    # Birden fazla listener — bekle
                    time.sleep(30)
                else:
                    logger.error(f"Telegram listener hatasi: {e}")
                    time.sleep(10)
            
            time.sleep(2)

    def _send_durum(self) -> None:
        """Acik pozisyonlari ve K/Z'yi goster."""
        try:
            balance = getattr(self.engine, 'balance', 0)
            positions = getattr(self.engine, 'positions', {})
            initial = getattr(self.engine, 'initial_capital', 10000)
            
            # Toplam K/Z
            total_pnl = 0
            symbol_stats = getattr(self.engine, '_symbol_stats', {})
            for sym, stats in symbol_stats.items():
                total_pnl += stats.get('total_pnl', 0)
            
            # Acik pozisyonlar + anlık K/Z
            pos_text = ""
            if positions:
                for sym, pos in positions.items():
                    direction = pos.get('direction', '?')
                    entry = pos.get('entry_price', 0)
                    notional = pos.get('notional', 0)
                    sl = pos.get('stop_loss', 0)
                    tp = pos.get('take_profit', 0)
                    
                    # Anlık fiyat al
                    try:
                        ticker = self.engine.fetcher.exchange.fetch_ticker(sym)
                        current = ticker['last']
                    except:
                        current = entry
                    
                    # Anlık K/Z hesapla
                    if direction == 'BUY':
                        pnl_pct = (current - entry) / entry * 100
                    else:
                        pnl_pct = (entry - current) / entry * 100
                    pnl_usd = notional * pnl_pct / 100 * 5  # 5x kaldıraç
                    
                    emoji = "🟢" if direction == "BUY" else "🔴"
                    kz_emoji = "📈" if pnl_usd >= 0 else "📉"
                    
                    # Bu coin'in toplam istatistiği
                    coin_stats = symbol_stats.get(sym, {"wins": 0, "losses": 0, "total_pnl": 0})
                    coin_total = coin_stats.get("total_pnl", 0)
                    coin_trades = coin_stats.get("wins", 0) + coin_stats.get("losses", 0)
                    coin_wr = coin_stats.get("wins", 0) / coin_trades * 100 if coin_trades else 0
                    
                    pos_text += (
                        f"  {emoji} {sym} | {direction}\n"
                        f"     Giriş: {format_price(entry)} → Şimdi: {format_price(current)}\n"
                        f"     {kz_emoji} Anlık K/Z: ${pnl_usd:+.2f} (%{pnl_pct:+.1f})\n"
                        f"     SL: {format_price(sl)} | TP: {format_price(tp)}\n"
                        f"     📊 Geçmiş: {coin_trades} işlem, %{coin_wr:.0f} WR, ${coin_total:+.2f}\n\n"
                    )
            else:
                pos_text = "  Açık pozisyon yok\n"
            
            # Versiyon
            version = "v7"
            try:
                from src.strategy.adaptive_learner import AdaptiveLearner
                learner = AdaptiveLearner()
                version = learner.get_version()
            except:
                pass

            msg = (
                f"📊 DURUM — {version}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Bakiye: ${balance:,.2f}\n"
                f"📈 Toplam K/Z: ${total_pnl:+,.2f}\n"
                f"💵 Başlangıç: ${initial:,.0f}\n"
                f"📊 Getiri: %{(balance/initial-1)*100:+.1f}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🔓 Açık Pozisyonlar ({len(positions)}):\n\n"
                f"{pos_text}"
            )
            send_telegram_notification(msg)
            
        except Exception as e:
            logger.error(f"Durum raporu hatasi: {e}")


def start_telegram_listener(execution_engine: Any) -> None:
    """Telegram command listener'ini baslatir."""
    cfg = execution_engine.settings
    token = cfg.telegram_bot_token
    chat_id = cfg.telegram_chat_id

    if not token or not chat_id:
        return

    if "your_telegram_bot" in token or "your_telegram_chat" in chat_id:
        return

    listener = TelegramListener(token, chat_id, execution_engine)
    listener.start()
