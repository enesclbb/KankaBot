# KankaBot — başlangıç sürümü

Bu proje Solana tokenleri için DexScreener üzerinden market verisi okuyan, sanal AL/SAT ve işlem geçmişi sunan bir paper-trading dashboardudur. **Gerçek cüzdan veya gerçek emir bağlantısı yoktur.**

## Bilgisayarda çalıştırma
1. Python 3.10+ kur.
2. Terminali proje klasöründe aç.
3. `pip install -r requirements.txt`
4. `streamlit run app.py`
5. Tarayıcıda açılan panelde Solana token mint adresini gir.

## Not
Sanal işlemler basit test içindir. Stop-loss/take-profit seviyeleri yalnızca uyarı verir; otomatik satış gerçekleştirmez. Canlı işlem öncesi strateji, güvenlik, slippage, likidite ve anahtar yönetimi ayrıca tasarlanmalıdır. Seed phrase/private key hiçbir yere girilmemelidir.
