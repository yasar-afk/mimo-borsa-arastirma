# V6 Mean Reversion LIVE Trading Bot

Bu proje, Binance üzerinde çalışan ve en yüksek hacimli 100 USDT çiftini sürekli tarayarak Bollinger Bands, RSI ve ATR indikatörlerine dayalı V6 Mean Reversion stratejisiyle canlı/paper trading yapan bir bottur.

> [!IMPORTANT]
> **YAPAY ZEKA (AI) AGENTLARINA TALİMAT:**
> Bu projede herhangi bir kod güncellemesi veya analiz yapmadan önce mutlaka bu dosyayı ve `.cursorrules` dosyasını baştan sona okuyun.

---

## 📂 Proje Yapısı ve Kritik Dosyalar

*   **`live_v6mr.py`**: Canlı veya paper trade modunda çalışan ana bot döngüsü.
    *   **Port Kilidi:** Çift çalışmayı (mükerrer çalıştırma) önlemek için yerel `28384` portunu kilitler. İkinci bir kopya çalıştırılamaz.
    *   **Hassas Fiyat Formatı:** Küçük fiyatlı coinler (örn. LUNC) için basamak hatası oluşmaması için `format_price()` fonksiyonunu kullanır.
*   **`watch.py`**: Portföy, anlık açık pozisyonlar ve geçmiş işlemleri terminalde izlemek için kullanılan grafiksel panel.
*   **`logs/portfolio_state.json`**: Botun **tek gerçek veri kaynağıdır (Source of Truth)**. Bakiyeler, açık pozisyonlar ve geçmiş tüm işlemler burada tutulur. Bot kapansa dahi buradan otomatik kurtarma yapar.
*   **`config_live_v6mr.yaml`**: Botun canlı çalışma parametrelerini (kâr al/zarar kes oranları, pozisyon yüzdeleri vb.) içeren ayar dosyası.
*   **`botu_baslat.bat`**: Windows ortamında botu tek tıklamayla canlı modda başlatır.
*   **`izleyiciyi_baslat.bat`**: Windows ortamında izleme panelini (`watch.py`) tek tıklamayla başlatır.
*   **`src/`**: Botun arka plan sınıfları (veri çekici, indikatör motoru, Telegram bildirimi vb.).

---

## ⚠️ AI Düzenleme Kuralları (AI Agent Constraints)

1.  **Mükerrer İşlem Yasağı:** Botu terminal üzerinden test etmek veya çalıştırmak istediğinizde, arka planda çalışan aktif bir bot süreci (`task`) olup olmadığını kontrol edin. Çift çalıştırma durumunda port kilidi nedeniyle hata alırsınız.
2.  **Hassas Fiyat Formatı:** LUNC, PEPE gibi ucuz coinlerin fiyatlarını formatlarken asla sabit yuvarlama (örn: `:.4f`) kullanmayın. Her zaman `format_price(price)` fonksiyonunu çağırın.
3.  **UTF-8 Standartı:** Windows Türkçe (CP1254) konsol çıktı hatalarını (`UnicodeEncodeError`) önlemek için, konsola yazı yazdıran yeni betiklerin başına şu kod bloğunu ekleyin:
    ```python
    import sys
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ```
4.  **Durum Koruma:** `logs/portfolio_state.json` dosyasının şemasını bozacak değişiklikler yapmayın. `_save_state` ve `_load_state` fonksiyonlarının tutarlılığını koruyun.
