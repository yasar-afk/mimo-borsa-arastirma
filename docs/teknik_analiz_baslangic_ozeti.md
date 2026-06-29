# Teknik Analiz Başlangıç Özeti
*Kaynak: "Teknik Analiz Zor (Bu Videoyu İzleyene Kadar)" — Emir Şahin*
*Tarih: 2026-06-16*

---

## Temel Terimler

| Terim | Açıklama |
|-------|----------|
| **ATH** | All Time High — varlığın tüm zamanların en yüksek fiyatı |
| **Destek** | Fiyat düştüğünde alıcıların devreye girdiği seviye |
| **Direnç** | Fiyat yükseldiğinde satışların arttığı seviye |
| **Long** | Fiyatın yükseleceği yönünde pozisyon |
| **Short** | Fiyatın düşeceği yönünde pozisyon |

## Emir Türleri

- **Piyasa Emri**: Anlık fiyattan alım/satım
- **Limit Emri**: Belirlenen fiyattan otomatik alım/satım → daha kontrollü

## Grafik Okuma

- **Yeşil mum**: Fiyat yükseldi (açılış alt, kapanış üst)
- **Kırmızı mum**: Fiyat düştü (açılış üst, kapanış alt)
- **Fitiller**: O mumdaki en düşük ve en yüksek seviye

## Temel Göstergeler

### RSI (Göreceli Güç Endeksi)
- 30 altı → aşırı satış, fiyat yükselebilir
- 70 üstü → aşırı alım, fiyat düşebilir

### Hareketli Ortalama
- Son X günün fiyat ortalaması
- Fiyat hareketli ortalamayı aşağı kırarsa → düşüş sinyali

### İşlem Hacmi
- Fiyat yükselirken hacim de artarsa → güçlü trend
- Tüm borsalardan veri çektiği için CoinMarketCap/CoinGecko tercih edilmeli

## Kaldıraçlı İşlemler

- Kazancı ve kaybı büyütür (örn: 12x kaldıraç → %1 fiyat hareketi = %12 kâr/zarar)
- **Stop Loss** mutlaka kullanılmalı

## Anahtar Mesajlar

> "Teknik analiz tek başına %100 sonuç vermez."

> "Para ve haber teknik analizi bozar."

> "Teknik analiz insanların psikolojisini gösterir — uzmanlaştıkça başarı şansı artar."

## Proje İçin Uygulama

Bu proje (`live_v6mr.py`, `watch.py`) zaten RSI, hareketli ortalama, MACD gibi göstergeleri kullanıyor. Videodaki kavramlar mevcut `config.yaml` ve `TECHNICAL_INDICATORS_REPORT.md` ile uyumlu.

### Dikkat Edilecekler
1. Teknik analiz tek başına karar verici olmamalı
2. Makro faktörler (enflasyon, faiz, jeopolitik) hesaba katılmalı
3. Stop Loss stratejisi destek seviyelerine veya RSI'a göre belirlenebilir
4. İşlem hacmi trend gücünü doğrular
