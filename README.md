# 📈 MIMO Borsa Araştırma

Xiaomi MiMo v2.5 AI ile desteklenen otonom kripto trading botu. Binance Futures üzerinde çalışan, grafik tabanlı sinyal doğrulama yapan gelişmiş trading sistemi.

[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
![AI](https://img.shields.io/badge/AI-MiMo%20v2.5-FF6700?style=for-the-badge)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

## ✨ Özellikler

| Modül | Açıklama | Durum |
|-------|----------|-------|
| 📊 **V5 Strategy** | RSI + Bollinger Bands | ✅ |
| 📈 **V6.5 Mean Reversion** | Ortalama dönüş stratejisi | ✅ |
| 📉 **V7 Strategy** | Price Action + SMC | ✅ |
| 🤖 **AI Verification** | MiMo v2.5 grafik doğrulama | ✅ |
| 🧠 **Adaptive Learning** | Otomatik optimizasyon | ✅ |
| 🎯 **Risk Management** | Kapsamlı risk kontrolü | ✅ |
| 📱 **Telegram Bot** | Gerçek zamanlı bildirimler | ✅ |
| 📊 **Dashboard** | Web tabanlı izleme | ✅ |

## 🚀 Hızlı Başlangıç

### Kurulum

```bash
# 1. Depoyu klonla
git clone https://github.com/yasar-afk/mimo-borsa-arastirma.git
cd mimo-borsa-arastirma

# 2. Sanal ortam oluştur
python -m venv venv
venv\Scripts\activate

# 3. Bağımlılıkları yükle
pip install -r requirements.txt

# 4. Konfigürasyon
cp .env.example .env
```

### .env Dosyası

```env
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
MIMO_API_KEY=your_mimo_api_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### Çalıştırma

```bash
# Tüm botları paralel çalıştır
python run_all.py

# V7 botu
python live_v7.py --paper    # Paper trading
python live_v7.py --live     # Canlı borsa

# V6.5 Mean Reversion
python live_v65.py

# Dashboard
python dashboard/app.py
```

## 📊 Stratejiler

### V5 - RSI + Bollinger Bands
- RSI aşırı alım/satım tespiti
- Bollinger Bands kırılma sinyalleri
- EMA trend filtresi

### V6.5 - Mean Reversion
- Fiyatın ortalamaya dönüşü
- Bollinger Bands geri dönüş sinyalleri
- Hacim doğrulaması

### V7 - Price Action + SMC
- 100 mum swing high/low tarama
- Smart Money Concepts (SMC)
- Liquidity Sweep Reversal
- Dinamik Risk/Reward (ADX bazlı)
- Multi-timeframe konfirmasyon (15m + 1h + 4h)

## 🤖 AI Entegrasyonu (MiMo v2.5)

```
┌─────────────────────────────────────────────────┐
│              MIMO AI Pipeline                   │
└─────────────────────────────────────────────────┘
                     │
    ┌────────────────┼────────────────┐
    ▼                ▼                ▼
┌────────┐     ┌──────────┐     ┌──────────┐
│ Mum    │     │ İndikatör│     │ Sentiment│
│ Grafik │     │ Hesaplama│     │ Analizi  │
└────┬───┘     └────┬─────┘     └────┬─────┘
     │              │                │
     └──────────────┼────────────────┘
                    ▼
            ┌──────────────┐
            │   MiMo v2.5  │
            │  Grafik Analiz│
            └──────┬───────┘
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
    ┌──────┐  ┌────────┐  ┌──────┐
    │ TRADE│  │  SKIP  │  │CLOSE │
    └──────┘  └────────┘  └──────┘
```

## 🛡️ Risk Yönetimi

| Parametre | Değer | Açıklama |
|-----------|-------|----------|
| Max pozisyon | 10 | Eşzamanlı maksimum pozisyon |
| Pozisyon riski | %2 | Her pozisyon için risk |
| Günlük drawdown | %5 | Günlük maksimum kayıp |
| Kaldıraç | 5x | İzole marjin |
| Komisyon | %0.063 | İşlem komisyonu |
| Cooldown | 24 saat | Stop-loss sonrası bekleme |
| Arka arkaya kayıp | 3 | 2. kayıp %50, 3. kayıp %25 |

## 📱 Telegram Komutları

```
/durum    - Bot durumu ve istatistikler
/status   - Açık pozisyonlar
/portfoy  - Portföy özeti
/pozisyon - Detaylı pozisyon bilgisi
/acik     - Açık pozisyon listesi
```

## 📁 Proje Yapısı

```
mimo-borsa-arastirma/
├── live_v7.py              # V7 ana bot
├── live_v65.py             # V6.5 Mean Reversion
├── live_v5.py              # V5 bot
├── run_all.py              # Tümünü paralel çalıştır
├── config.yaml             # Ana konfigürasyon
├── config_v7.yaml          # V7 ayarları
├── requirements.txt        # Bağımlılıklar
├── setup.py                # pip kurulum
│
├── src/                    # Kaynak kodları
│   ├── strategy/           # Strateji modülleri
│   ├── risk/               # Risk yönetimi
│   ├── data/               # Veri çekme
│   └── utils/              # Yardımcı fonksiyonlar
│
├── dashboard/              # Web dashboard
├── models/                 # ML modelleri
├── data/                   # Fiyat verileri
├── logs/                   # İşlem logları
└── tests/                  # Test dosyaları
```

## 🔧 Konfigürasyon

```yaml
# config_v7.yaml
strategy:
  sweep_window: 100
  trend_ema: 180
  atr_multiplier: 0.6
  min_sl_pct: 0.02
  max_sl_pct: 0.08

risk:
  max_position_pct: 0.02
  max_daily_drawdown_pct: 0.05
  min_risk_reward_ratio: 3.0

execution:
  leverage: 5
  margin_mode: ISOLATED
```

## 🧪 Backtest

```bash
# V7 backtest
python backtest_v7.py

# Kapsamlı analiz
python analyze_v7_comprehensive.py

# Sinyal analizi
python diagnose_signals.py
```

## 📊 Performans

| Metrik | Değer |
|--------|-------|
| Strateji | V7 Price Action + SMC |
| AI | MiMo v2.5 |
| Kaldıraç | 5x İzole |
| Durum | Aktif (Paper Trading) |

## 🛠️ Teknoloji Stack

| Kategori | Teknoloji |
|----------|-----------|
| **Dil** | Python 3.9+ |
| **Borsa** | Binance Futures (ccxt) |
| **AI** | MiMo v2.5 (Xiaomi) |
| **ML** | Scikit-learn, XGBoost |
| **Bildirim** | Telegram Bot |
| **Veri** | Pandas, NumPy |
| **Grafik** | Matplotlib, Plotly |

## ⚠️ Uyarı

Bu bot yatırım tavsiyesi değildir. Kripto para birimleri yüksek risk taşır. Paper trading ile test edin.

## 📝 Lisans

MIT License

---

**MIMO Borsa Araştırma** — MiMoCode tarafından geliştirildi 📈
