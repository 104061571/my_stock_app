import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from FinMind.data import DataLoader

# --- 1. 頁面設定 ---
st.set_page_config(page_title="台股河流圖 - 最終穩定版", layout="wide")

# 初始化 FinMind
dl = DataLoader()

st.title("📈 台股河流圖系統 (穩定版)")
st.write("已修正名稱讀取錯誤，並加入快取機制減少 Rate Limit。")
st.markdown("---")

# --- 2. 側邊欄 ---
with st.sidebar:
    st.header("🔍 查詢設定")
    raw_id = st.text_input("輸入代碼 (如: 2330)", value="2330")
    period_choice = st.selectbox("週期", ["日 (Daily)", "週 (Weekly)", "月 (Monthly)", "年 (Yearly)"])
    start_date = st.date_input("開始日期", value=pd.to_datetime("2020-01-01"))
    end_date = st.date_input("結束日期", value=pd.to_datetime("today"))
    
    st.subheader("📏 河流倍數")
    pe_ratios = [st.number_input(f"倍數 {i}", value=v) for i, v in zip("ABCD", [15.0, 20.0, 25.0, 30.0])]
    fetch_button = st.button("更新數據")

# --- 3. 核心抓取功能 (加入安全檢查) ---

@st.cache_data(ttl=3600)
def get_safe_stock_data(symbol, start, end):
    """安全地抓取股價與市場類型，避開不穩定的 info 介面"""
    for suffix in [".TW", ".TWO"]:
        t_str = f"{symbol}{suffix}"
        t_obj = yf.Ticker(t_str)
        # auto_adjust=False 確保獲取原始 Close
        df = t_obj.history(start=start, end=end, auto_adjust=False)
        
        if not df.empty:
            m_type = "上市 (.TW)" if suffix == ".TW" else "上櫃 (.TWO)"
            # 安全地嘗試抓取名稱
            s_name = symbol
            try:
                # 使用較新的快取機制獲取基本資訊，若失敗則僅顯示代號
                s_name = t_obj.fast_info.get('currency', symbol) # 測試連線
                # 這裡改用 try-except 包裹，避免 info 為 None 時崩潰
                info = t_obj.info
                if info and isinstance(info, dict):
                    s_name = info.get('shortName') or info.get('longName') or symbol
            except:
                s_name = symbol
            return df, m_type, s_name
            
    return pd.DataFrame(), "", symbol

@st.cache_data(ttl=3600)
def get_safe_eps(symbol, start, end):
    """抓取財報 EPS"""
    try:
        eps_df = dl.taiwan_stock_financial_statement(
            stock_id=symbol,
            start_date=start.strftime('%Y-%m-%d'), end_date=end.strftime('%Y-%m-%d')
        )
        if not eps_df.empty:
            eps_data = eps_df[eps_df['type'] == 'EPS'][['date', 'value']]
            eps_data['date'] = pd.to_datetime(eps_data['date'])
            eps_data['Year'] = eps_data['date'].dt.year
            return eps_data.groupby('Year')['value'].sum().reset_index()
    except:
        return pd.DataFrame()

# --- 4. 數據處理與呈現 ---
if fetch_button:
    try:
        with st.spinner('同步數據中...'):
            df_yf, m_type, s_name = get_safe_stock_data(raw_id, start_date, end_date)
            
            if df_yf.empty:
                st.error("❌ 找不到股價。請確認代碼或稍候再試 (可能受頻率限制)。")
            else:
                st.success(f"✅ 已讀取：{raw_id} {s_name}")
                
                # 週期取樣
                resample_key = 'W-FRI' if "週" in period_choice else 'ME' if "月" in period_choice else 'YE' if "年" in period_choice else 'D'
                df_res = df_yf.resample(resample_key).agg({'Close': 'last', 'Volume': 'sum'}).reset_index()
                
                # 合併 EPS
                ann_eps = get_safe_eps(raw_id, start_date, end_date)
                df_res['Year'] = df_res['Date'].dt.year
                
                if not ann_eps.empty:
                    ann_eps.columns = ['Year', 'Annual_EPS']
                    df_final = pd.merge(df_res, ann_eps, on='Year', how='left').ffill()
                else:
                    df_final = df_res
                    df_final['Annual_EPS'] = None

                # 繪圖
                fig = go.Figure()
                if 'Annual_EPS' in df_final.columns and df_final['Annual_EPS'].notnull().any():
                    for ratio in pe_ratios:
                        fig.add_trace(go.Scatter(x=df_final['Date'], y=df_final['Annual_EPS']*ratio, 
                                                 mode='lines', name=f'{ratio}x PE', line=dict(dash='dot', width=1)))
                
                fig.add_trace(go.Scatter(x=df_final['Date'], y=df_final['Close'], 
                                         mode='lines', name='實際收盤價', line=dict(color='firebrick', width=2.5)))
                
                fig.update_layout(title=f"{s_name} 河流圖分析", template="plotly_white", height=600)
                st.plotly_chart(fig, use_container_width=True)
                
                st.subheader("💰 年度總 EPS")
                st.dataframe(ann_eps.sort_values('Year', ascending=False) if not ann_eps.empty else "無數據")

    except Exception as e:
        st.error(f"發生非預期錯誤：{e}")
