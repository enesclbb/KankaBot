import streamlit as st
import requests
import pandas as pd
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timezone

st.set_page_config(page_title="KankaBot | Solana Meme Tarayıcı", page_icon="🤖", layout="wide")
st.title("🤖 KankaBot — Solana Memecoin Tarayıcı")
st.caption("V5: otomatik sanal tarama ve AL/SAT, DexScreener verilerini puanlar ve sanal işlemler sunar. Gerçek cüzdan/emir bağlantısı yoktur.")

API = "https://api.dexscreener.com"
TIMEOUT = 15

if "balance" not in st.session_state:
    st.session_state.balance = 20.0
if "positions" not in st.session_state:
    st.session_state.positions = {}
if "history" not in st.session_state:
    st.session_state.history = []
if "current_pair" not in st.session_state:
    st.session_state.current_pair = None
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []
if "position_market_prices" not in st.session_state:
    st.session_state.position_market_prices = {}

@st.cache_data(ttl=90, show_spinner=False)
def latest_profiles():
    r = requests.get(f"{API}/token-profiles/latest/v1", timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []

@st.cache_data(ttl=60, show_spinner=False)
def token_pairs(mint):
    r = requests.get(f"{API}/latest/dex/tokens/{mint}", timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data.get("pairs") or []

def num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0

def choose_solana_pair(pairs):
    candidates = [p for p in pairs if p.get("chainId") == "solana"]
    if not candidates:
        return None
    return max(candidates, key=lambda p: num((p.get("liquidity") or {}).get("usd")))

def age_hours(pair):
    created = pair.get("pairCreatedAt")
    if not created:
        return None
    try:
        return max(0.0, (datetime.now(timezone.utc).timestamp() * 1000 - float(created)) / 3600000)
    except (TypeError, ValueError):
        return None

def score_pair(pair):
    liq = num((pair.get("liquidity") or {}).get("usd"))
    vol1 = num((pair.get("volume") or {}).get("h1"))
    vol24 = num((pair.get("volume") or {}).get("h24"))
    tx1 = (pair.get("txns") or {}).get("h1") or {}
    buys = num(tx1.get("buys"))
    sells = num(tx1.get("sells"))
    change1 = num((pair.get("priceChange") or {}).get("h1"))
    age = age_hours(pair)

    # Basit, açıklanabilir eleme puanı; yükseliş tahmini/garantisi değildir.
    score = 0
    if liq >= 10000: score += 25
    elif liq >= 5000: score += 15
    elif liq >= 2000: score += 5

    if vol1 >= 10000: score += 20
    elif vol1 >= 3000: score += 12
    elif vol1 >= 1000: score += 5

    if vol24 >= 50000: score += 15
    elif vol24 >= 15000: score += 10
    elif vol24 >= 5000: score += 5

    total_tx = buys + sells
    if total_tx >= 100: score += 15
    elif total_tx >= 30: score += 10
    elif total_tx >= 10: score += 5

    if buys > sells and total_tx > 0: score += 10
    if age is not None and 1 <= age <= 48: score += 10
    elif age is not None and age < 1: score += 3

    if change1 < -25: score -= 15
    if change1 > 100: score -= 10  # aşırı ani hareket için risk kesintisi
    score = max(0, min(100, score))

    warnings = []
    if liq < 5000: warnings.append("Likidite düşük")
    if total_tx < 10: warnings.append("İşlem sayısı az")
    if change1 > 100: warnings.append("Saatlik yükseliş aşırı")
    if change1 < -25: warnings.append("Saatlik düşüş sert")
    if age is not None and age < 1: warnings.append("Çok yeni havuz")
    if sells > buys * 1.5 and sells > 0: warnings.append("Satış baskısı")
    if not warnings: warnings.append("Yine de yüksek riskli")
    return score, ", ".join(warnings), age

with st.sidebar:
    st.header("Sanal risk ayarları")
    start_balance = st.number_input("Sanal başlangıç bakiyesi ($)", min_value=1.0, value=20.0, step=1.0)
    trade_size = st.number_input("Her sanal işlem tutarı ($)", min_value=1.0, value=2.0, step=0.5)
    stop_loss = st.slider("Zarar durdurma (%)", min_value=3, max_value=50, value=15)
    take_profit = st.slider("Kâr alma (%)", min_value=5, max_value=200, value=30)
    st.warning("Puanlar yalnızca basit filtre göstergesidir. Kâr tahmini veya garantisi değildir.")
    auto_mode = st.toggle("🤖 Otomatik sanal AL/SAT", value=False)
    auto_interval = st.selectbox("Otomatik kontrol aralığı", [15, 30, 60], index=0, format_func=lambda x: f"{x} saniye")
    max_positions = st.number_input("Maksimum açık pozisyon", min_value=1, max_value=5, value=2)
    min_auto_score = st.slider("Otomatik AL için minimum puan", 50, 95, 75)
    st.caption("Bu yalnızca sanal hesaptır. Gerçek cüzdana emir göndermez.")

if auto_mode:
    st_autorefresh(interval=auto_interval * 1000, key="kankabot_auto_refresh")

if st.button("Sanal hesabı sıfırla"):
    st.session_state.balance = float(start_balance)
    st.session_state.positions = {}
    st.session_state.history = []
    st.rerun()

st.subheader("1) Solana yeni token taraması")
st.write("Tarayıcı en yeni token profillerinden Solana adreslerini alır, her adres için market verisini sorgular ve temel ölçütlere göre sıralar.")
scan_count = st.select_slider("Kaç yeni profil incelensin?", options=[10, 15, 20, 30], value=15)
if st.button("Yeni memecoinleri tara", type="primary"):
    results = []
    try:
        with st.spinner("Yeni profiller alınıyor ve Solana marketleri kontrol ediliyor..."):
            profiles = latest_profiles()
            sol_profiles = []
            seen = set()
            for item in profiles:
                if item.get("chainId") != "solana":
                    continue
                mint = item.get("tokenAddress")
                if mint and mint not in seen:
                    seen.add(mint)
                    sol_profiles.append(item)
                if len(sol_profiles) >= scan_count:
                    break

            for profile in sol_profiles:
                mint = profile.get("tokenAddress")
                try:
                    pair = choose_solana_pair(token_pairs(mint))
                    if not pair:
                        continue
                    score, warnings, age = score_pair(pair)
                    base = pair.get("baseToken") or {}
                    results.append({
                        "Puan": score,
                        "Token": base.get("symbol") or profile.get("tokenAddress", "")[:8],
                        "Ad": base.get("name") or "Bilinmeyen",
                        "Fiyat ($)": num(pair.get("priceUsd")),
                        "Likidite ($)": num((pair.get("liquidity") or {}).get("usd")),
                        "Hacim 1s ($)": num((pair.get("volume") or {}).get("h1")),
                        "Hacim 24s ($)": num((pair.get("volume") or {}).get("h24")),
                        "Değişim 1s (%)": num((pair.get("priceChange") or {}).get("h1")),
                        "Alım 1s": num(((pair.get("txns") or {}).get("h1") or {}).get("buys")),
                        "Satım 1s": num(((pair.get("txns") or {}).get("h1") or {}).get("sells")),
                        "Havuz yaşı (saat)": round(age, 1) if age is not None else None,
                        "Risk notu": warnings,
                        "Mint adresi": mint,
                        "Pair adresi": pair.get("pairAddress", ""),
                    })
                except Exception:
                    # Tek tokenin API hatası tüm taramayı durdurmasın.
                    continue
        st.session_state.scan_results = sorted(results, key=lambda x: x["Puan"], reverse=True)
        if st.session_state.scan_results:
            st.success(f"{len(st.session_state.scan_results)} Solana marketi bulundu.")
        else:
            st.warning("Bu taramada uygun market bulunamadı. Biraz sonra tekrar dene.")
    except Exception as e:
        st.error(f"Tarama sırasında veri alınamadı: {e}")

if st.session_state.scan_results:
    df = pd.DataFrame(st.session_state.scan_results)
    st.markdown("#### Tarama sonuçları — puana göre sıralı")
    st.dataframe(
        df[["Puan", "Token", "Ad", "Fiyat ($)", "Likidite ($)", "Hacim 1s ($)", "Hacim 24s ($)", "Değişim 1s (%)", "Alım 1s", "Satım 1s", "Havuz yaşı (saat)", "Risk notu"]],
        use_container_width=True,
        hide_index=True
    )
    choices = {f'{row["Token"]} — puan {row["Puan"]} — {row["Mint adresi"][:8]}…': row["Mint adresi"] for row in st.session_state.scan_results}
    selected_label = st.selectbox("Sanal işlem için tarama sonucundan token seç", list(choices.keys()))
    if st.button("Seçili tokenı işlem paneline getir"):
        mint = choices[selected_label]
        try:
            pair = choose_solana_pair(token_pairs(mint))
            if pair:
                st.session_state.current_pair = pair
                st.session_state.current_mint = mint
                st.success("Token işlem paneline getirildi.")
                st.rerun()
            else:
                st.error("Seçilen token için market bulunamadı.")
        except Exception as e:
            st.error(f"Token verisi alınamadı: {e}")

# Otomatik SANAL strateji döngüsü: scan + fiyat yenile + TP/SL çık + puanlı AL.
if auto_mode:
    now_ts = datetime.now(timezone.utc).timestamp()
    last_ts = st.session_state.get("auto_last_cycle", 0)
    if now_ts - last_ts >= auto_interval:
        st.session_state.auto_last_cycle = now_ts
        auto_events = []
        # Güncel token profillerinden tarama evreni oluştur
        try:
            profiles = latest_profiles()
            auto_candidates = []
            seen_mints = set()
            for item in profiles:
                if item.get("chainId") != "solana":
                    continue
                candidate_mint = item.get("tokenAddress")
                if not candidate_mint or candidate_mint in seen_mints:
                    continue
                seen_mints.add(candidate_mint)
                try:
                    fresh_pairs = token_pairs.__wrapped__(candidate_mint)
                    candidate_pair = choose_solana_pair(fresh_pairs)
                    if not candidate_pair:
                        continue
                    candidate_score, candidate_warning, candidate_age = score_pair(candidate_pair)
                    candidate_liq = num((candidate_pair.get("liquidity") or {}).get("usd"))
                    candidate_vol1 = num((candidate_pair.get("volume") or {}).get("h1"))
                    candidate_change1 = num((candidate_pair.get("priceChange") or {}).get("h1"))
                    tx1 = (candidate_pair.get("txns") or {}).get("h1") or {}
                    buys1, sells1 = num(tx1.get("buys")), num(tx1.get("sells"))
                    auto_candidates.append((candidate_score, candidate_mint, candidate_pair, candidate_liq, candidate_vol1, candidate_change1, buys1, sells1))
                except Exception:
                    continue
                if len(auto_candidates) >= scan_count:
                    break
        except Exception as e:
            auto_events.append(f"Tarama API hatası: {e}")
            auto_candidates = []

        # Açık pozisyonların son fiyatlarını getir ve sanal TP/SL uygulaması yap
        for open_mint, open_pos in list(st.session_state.positions.items()):
            try:
                fresh_pairs = token_pairs.__wrapped__(open_mint)
                fresh_pair = choose_solana_pair(fresh_pairs)
                if not fresh_pair or num(fresh_pair.get("priceUsd")) <= 0:
                    continue
                st.session_state.position_market_prices[open_mint] = fresh_pair
                open_price = num(fresh_pair.get("priceUsd"))
                change_pct = (open_price / open_pos["entry"] - 1) * 100 if open_pos.get("entry") else 0
                if change_pct <= -stop_loss or change_pct >= take_profit:
                    proceeds = open_pos["qty"] * open_price
                    pnl = proceeds - open_pos["cost"]
                    st.session_state.balance += proceeds
                    st.session_state.history.append({"Saat": datetime.now().strftime("%H:%M:%S"), "İşlem": "OTOMATİK SANAL SAT", "Token": open_pos["symbol"], "Fiyat": open_price, "Tutar": proceeds, "K/Z": pnl})
                    del st.session_state.positions[open_mint]
                    st.session_state.position_market_prices.pop(open_mint, None)
                    auto_events.append(f"{open_pos['symbol']} sanal satıldı; K/Z ${pnl:+.2f} (TP/SL).")
            except Exception:
                continue

        # Sanal alım kriterleri: minimum puan, likidite, hacim, alım/satım akışı, ani pump eleme
        if len(st.session_state.positions) < max_positions and st.session_state.balance >= trade_size:
            auto_candidates.sort(key=lambda x: x[0], reverse=True)
            for candidate in auto_candidates:
                score, candidate_mint, candidate_pair, liq, vol1, change1, buys1, sells1 = candidate
                if candidate_mint in st.session_state.positions:
                    continue
                if score < min_auto_score or liq < 15000 or vol1 < 5000:
                    continue
                if buys1 <= sells1 or change1 > 50 or change1 < -20:
                    continue
                auto_price = num(candidate_pair.get("priceUsd"))
                if auto_price <= 0:
                    continue
                token_info = candidate_pair.get("baseToken") or {}
                auto_symbol = token_info.get("symbol") or candidate_mint[:8]
                auto_name = token_info.get("name") or "Token"
                auto_qty = trade_size / auto_price
                st.session_state.balance -= trade_size
                st.session_state.positions[candidate_mint] = {"name": auto_name, "symbol": auto_symbol, "entry": auto_price, "qty": auto_qty, "cost": trade_size}
                st.session_state.position_market_prices[candidate_mint] = candidate_pair
                st.session_state.history.append({"Saat": datetime.now().strftime("%H:%M:%S"), "İşlem": "OTOMATİK SANAL AL", "Token": auto_symbol, "Fiyat": auto_price, "Tutar": trade_size})
                auto_events.append(f"{auto_symbol} sanal alındı — puan {score}, ${trade_size:.2f}.")
                if len(st.session_state.positions) >= max_positions or st.session_state.balance < trade_size:
                    break
        if auto_events:
            st.info("Otomatik döngü: " + " | ".join(auto_events))
        else:
            st.caption("Otomatik döngü tamamlandı: bu turda yeni sanal işlem yok.")

st.divider()
st.subheader("2) İstersen adresi elle kontrol et")
token = st.text_input("Solana token adresi (mint)", placeholder="Token adresini buraya yapıştır")
if st.button("Adresin piyasa verisini getir", disabled=not token.strip()):
    try:
        pair = choose_solana_pair(token_pairs(token.strip()))
        if not pair:
            st.error("Solana üzerinde eşleşen market bulunamadı.")
        else:
            st.session_state.current_pair = pair
            st.session_state.current_mint = token.strip()
            st.success("Market bulundu. Sanal işlem paneli aşağıda.")
            st.rerun()
    except Exception as e:
        st.error(f"Veri alınamadı: {e}")

pair = st.session_state.get("current_pair")
mint = st.session_state.get("current_mint", token.strip() if token else "")

# Kullanıcı tıklamasıyla fiyat yenileme. Cache dışından DexScreener verisi alınır.
if st.session_state.positions:
    if st.button("🔄 Tüm açık pozisyonların fiyatını yenile"):
        updated = 0
        errors = []
        for pos_mint in list(st.session_state.positions.keys()):
            try:
                fresh_pairs = token_pairs.__wrapped__(pos_mint)
                fresh_pair = choose_solana_pair(fresh_pairs)
                if fresh_pair and num(fresh_pair.get("priceUsd")) > 0:
                    st.session_state.position_market_prices[pos_mint] = fresh_pair
                    updated += 1
                else:
                    errors.append(st.session_state.positions[pos_mint]["symbol"])
            except Exception:
                errors.append(st.session_state.positions[pos_mint]["symbol"])
        if mint and st.session_state.get("current_mint") in st.session_state.position_market_prices:
            st.session_state.current_pair = st.session_state.position_market_prices[st.session_state.current_mint]
        if updated:
            st.success(f"{updated} açık pozisyonun fiyatı güncellendi.")
        if errors:
            st.warning("Verisi alınamayanlar: " + ", ".join(errors))
        st.rerun()

if pair and mint:
    if st.button("🔄 Seçili market fiyatını yenile"):
        try:
            fresh_pairs = token_pairs.__wrapped__(mint)
            fresh_pair = choose_solana_pair(fresh_pairs)
            if fresh_pair:
                st.session_state.current_pair = fresh_pair
                if mint in st.session_state.positions:
                    st.session_state.position_market_prices[mint] = fresh_pair
                st.success("Fiyat güncellendi.")
                st.rerun()
            else:
                st.warning("Güncel market verisi bulunamadı.")
        except Exception as e:
            st.error(f"Fiyat yenilenemedi: {e}")

if pair:
    price = num(pair.get("priceUsd"))
    liquidity = num((pair.get("liquidity") or {}).get("usd"))
    vol24 = num((pair.get("volume") or {}).get("h24"))
    change24 = num((pair.get("priceChange") or {}).get("h24"))
    name = (pair.get("baseToken") or {}).get("name", "Token")
    symbol = (pair.get("baseToken") or {}).get("symbol", "?")
    st.subheader(f"{name} ({symbol})")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Fiyat", f"${price:.8f}")
    c2.metric("Likidite", f"${liquidity:,.0f}")
    c3.metric("24s hacim", f"${vol24:,.0f}")
    c4.metric("24s değişim", f"{change24:+.2f}%")

    st.markdown("### Sanal işlem")
    buy_col, sell_col = st.columns(2)
    with buy_col:
        if st.button(f"Sanal AL — ${trade_size:.2f}", disabled=price <= 0 or st.session_state.balance < trade_size):
            qty = trade_size / price
            st.session_state.balance -= trade_size
            st.session_state.positions[mint] = {"name": name, "symbol": symbol, "entry": price, "qty": qty, "cost": trade_size}
            st.session_state.position_market_prices[mint] = pair
            st.session_state.history.append({"Saat": datetime.now().strftime("%H:%M:%S"), "İşlem": "AL", "Token": symbol, "Fiyat": price, "Tutar": trade_size})
            st.rerun()
    with sell_col:
        pos = st.session_state.positions.get(mint)
        if st.button("Sanal SAT", disabled=not pos or price <= 0):
            proceeds = pos["qty"] * price
            pnl = proceeds - pos["cost"]
            st.session_state.balance += proceeds
            st.session_state.history.append({"Saat": datetime.now().strftime("%H:%M:%S"), "İşlem": "SAT", "Token": symbol, "Fiyat": price, "Tutar": proceeds, "K/Z": pnl})
            del st.session_state.positions[mint]
            st.session_state.position_market_prices.pop(mint, None)
            st.rerun()

    pos = st.session_state.positions.get(mint)
    if pos:
        pnl = pos["qty"] * price - pos["cost"]
        pct = (price / pos["entry"] - 1) * 100 if pos["entry"] else 0
        st.metric("Açık pozisyon K/Z", f"${pnl:+.2f}", f"{pct:+.2f}%")
        if pct <= -stop_loss:
            st.error(f"Zarar durdurma seviyesi aşıldı ({-stop_loss}%). Bot otomatik satmaz; sanal SAT düğmesini kullan.")
        elif pct >= take_profit:
            st.success(f"Kâr alma seviyesi görüldü (+{take_profit}%). Bot otomatik satmaz; sanal SAT düğmesini kullan.")

st.divider()
st.subheader("3) Sanal hesap özeti")
a, b = st.columns(2)
a.metric("Kullanılabilir sanal bakiye", f"${st.session_state.balance:.2f}")
b.metric("Açık pozisyon sayısı", len(st.session_state.positions))

# Mevcut pozisyonların kayıtlı giriş fiyatına göre K/Z; fiyatlar son yüklenen veridir.
total_unrealized = 0.0
portfolio_rows = []
for pos_mint, pos_data in st.session_state.positions.items():
    market_pair = st.session_state.position_market_prices.get(pos_mint)
    if pos_mint == st.session_state.get("current_mint") and st.session_state.current_pair:
        market_pair = st.session_state.current_pair
    current_price = num(market_pair.get("priceUsd")) if market_pair else pos_data.get("entry", 0.0)
    unrealized = pos_data["qty"] * current_price - pos_data["cost"]
    pct_unrealized = (current_price / pos_data["entry"] - 1) * 100 if pos_data.get("entry") else 0.0
    total_unrealized += unrealized
    portfolio_rows.append({"Token": pos_data["symbol"], "Maliyet ($)": pos_data["cost"], "Son fiyat ($)": current_price, "Açık K/Z ($)": unrealized, "K/Z (%)": pct_unrealized})
c, d = st.columns(2)
c.metric("Açık pozisyonların toplam K/Z", f"${total_unrealized:+.2f}")
d.metric("Sanal toplam varlık (yaklaşık)", f"${st.session_state.balance + sum(r['Maliyet ($)'] + r['Açık K/Z ($)'] for r in portfolio_rows):.2f}")
if portfolio_rows:
    st.dataframe(pd.DataFrame(portfolio_rows), use_container_width=True, hide_index=True)

if st.session_state.positions:
    st.dataframe(pd.DataFrame([{"Token": v["symbol"], "Giriş": v["entry"], "Miktar": v["qty"], "Maliyet": v["cost"]} for v in st.session_state.positions.values()]), use_container_width=True, hide_index=True)
if st.session_state.history:
    st.subheader("İşlem geçmişi")
    st.dataframe(pd.DataFrame(st.session_state.history), use_container_width=True, hide_index=True)

st.caption("Veri kaynağı: DexScreener public API. Puan sistemi basit filtreleme içindir; gerçek emir sistemi veya kâr garantisi değildir. Otomatik mod yalnızca sanal AL/SAT yapar. API verileri gecikmeli/eksik olabilir. Sanal K/Z ücretleri hesaba katmaz. Seed phrase/private key girme.")
