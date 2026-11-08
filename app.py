import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone

st.set_page_config(page_title="KankaBot | Paper Trading", page_icon="🤖", layout="wide")
st.title("🤖 KankaBot — Paper Trading")
st.caption("İlk sürüm: canlı piyasa verisi + sanal işlemler. Gerçek cüzdana bağlanmaz, emir göndermez.")

if "balance" not in st.session_state:
    st.session_state.balance = 20.0
if "positions" not in st.session_state:
    st.session_state.positions = {}
if "history" not in st.session_state:
    st.session_state.history = []

with st.sidebar:
    st.header("Risk ayarları")
    start_balance = st.number_input("Sanal başlangıç bakiyesi ($)", min_value=1.0, value=20.0, step=1.0)
    trade_size = st.number_input("Her işlem tutarı ($)", min_value=1.0, value=2.0, step=0.5)
    stop_loss = st.slider("Stop-loss (%)", min_value=3, max_value=50, value=15)
    take_profit = st.slider("Take-profit (%)", min_value=5, max_value=200, value=30)
    st.warning("Bu ayarlar eğitim amaçlıdır; kâr garantisi yoktur.")

if st.button("Sanal hesabı sıfırla"):
    st.session_state.balance = float(start_balance)
    st.session_state.positions = {}
    st.session_state.history = []
    st.rerun()

token = st.text_input("Solana token adresi (mint address)", placeholder="Token adresini buraya yapıştır")
col1, col2 = st.columns(2)
with col1:
    if st.button("Piyasa verisini getir", disabled=not token.strip()):
        try:
            resp = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token.strip()}", timeout=12)
            resp.raise_for_status()
            pairs = resp.json().get("pairs") or []
            sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
            if not sol_pairs:
                st.error("Solana üzerinde eşleşen market bulunamadı.")
            else:
                pair = max(sol_pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
                st.session_state.current_pair = pair
                st.success("Market bulundu. İşlem paneli aşağıda.")
        except Exception as e:
            st.error(f"Veri alınamadı: {e}")

pair = st.session_state.get("current_pair")
if pair:
    price = float(pair.get("priceUsd") or 0)
    liquidity = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24 = float((pair.get("volume") or {}).get("h24") or 0)
    change24 = float((pair.get("priceChange") or {}).get("h24") or 0)
    name = (pair.get("baseToken") or {}).get("name", "Token")
    symbol = (pair.get("baseToken") or {}).get("symbol", "?")
    st.subheader(f"{name} ({symbol})")
    m1,m2,m3,m4=st.columns(4)
    m1.metric("Fiyat", f"${price:.8f}")
    m2.metric("Likidite", f"${liquidity:,.0f}")
    m3.metric("24s hacim", f"${vol24:,.0f}")
    m4.metric("24s değişim", f"{change24:+.2f}%")

    st.markdown("### Sanal işlem")
    c_buy,c_sell=st.columns(2)
    with c_buy:
        if st.button(f"Sanal AL — ${trade_size:.2f}", disabled=price <= 0 or st.session_state.balance < trade_size):
            qty=trade_size/price
            st.session_state.balance -= trade_size
            st.session_state.positions[token.strip()]={"name":name,"symbol":symbol,"entry":price,"qty":qty,"cost":trade_size}
            st.session_state.history.append({"Saat":datetime.now().strftime("%H:%M:%S"),"İşlem":"AL","Token":symbol,"Fiyat":price,"Tutar":trade_size})
            st.rerun()
    with c_sell:
        pos=st.session_state.positions.get(token.strip())
        if st.button("Sanal SAT", disabled=not pos or price <= 0):
            proceeds=pos["qty"]*price
            pnl=proceeds-pos["cost"]
            st.session_state.balance += proceeds
            st.session_state.history.append({"Saat":datetime.now().strftime("%H:%M:%S"),"İşlem":"SAT","Token":symbol,"Fiyat":price,"Tutar":proceeds,"K/Z":pnl})
            del st.session_state.positions[token.strip()]
            st.rerun()

    pos=st.session_state.positions.get(token.strip())
    if pos:
        pnl=pos["qty"]*price-pos["cost"]
        pct=(price/pos["entry"]-1)*100 if pos["entry"] else 0
        st.metric("Açık pozisyon K/Z", f"${pnl:+.2f}", f"{pct:+.2f}%")
        if pct <= -stop_loss:
            st.error(f"Stop-loss seviyesi aşıldı ({-stop_loss}%). Bot henüz otomatik satmaz; sanal SAT düğmesini kullan.")
        elif pct >= take_profit:
            st.success(f"Take-profit seviyesi görüldü (+{take_profit}%). Bot henüz otomatik satmaz; sanal SAT düğmesini kullan.")

st.divider()
st.subheader("Hesap özeti")
a,b=st.columns(2)
a.metric("Kullanılabilir sanal bakiye", f"${st.session_state.balance:.2f}")
b.metric("Açık pozisyon sayısı", len(st.session_state.positions))
if st.session_state.positions:
    st.dataframe(pd.DataFrame([{"Token":v["symbol"],"Giriş":v["entry"],"Miktar":v["qty"],"Maliyet":v["cost"]} for v in st.session_state.positions.values()]), use_container_width=True)
if st.session_state.history:
    st.subheader("İşlem geçmişi")
    st.dataframe(pd.DataFrame(st.session_state.history), use_container_width=True)

st.caption("Veri kaynağı: DexScreener public API. Bu başlangıç sürümü strateji otomasyonu veya gerçek emir sistemi değildir. API verileri gecikmeli/eksik olabilir.")
