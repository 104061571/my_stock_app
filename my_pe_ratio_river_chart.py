import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from FinMind.data import DataLoader

# --- 1. 頁面基本設定 ---
st.set_page_config(page_title="台股河流圖 - 雲端穩定版", layout="wide")

# 初始化 FinMind
dl = DataLoader()

st.title("📈 台股本益比河流圖 (雲端穩定版)")
st.write("已加入快取機制以減少 Rate Limit 錯誤。")
st.markdown("---")

# --- 2. 側邊欄參數 ---
with st.sidebar:
    st.header("🔍 查詢設定")
    raw_id = st.text_input("輸入股票代碼", value="2330")
    period_choice = st.selectbox("選擇週期", ["日 (Daily)", "週 (Weekly)", "月 (Monthly)", "年 (Yearly)"])
    start_date = st.date_input("開始日期", value=pd.to_datetime("2020-01-01"))
    end_date = st.date_input("結束日期", value=pd.to_datetime("today"))
    
    st.subheader("📏 河流倍數")
    pe_ratios = [st.number_input(f"倍數 {i}", value=v) for i, v in zip("ABCD", [15.0, 20.0, 25.0, 30.0])]
    fetch_button = st.button("更新數據")

# --- 3. 核心功能：加入快取機制 (重要！) ---

@st.cache_data(ttl=3600) # 快取 1 小時，避免頻繁請求
def get_cached_data(symbol, start, end):
    """自動辨識上市櫃並抓取原始收盤價"""
    for suffix in [".TW", ".TWO"]:
        t_str = f"{symbol}{suffix}"
        t_obj = yf.Ticker(t_str)
        # auto_adjust=False 確保獲取原始 Close
        df = t_obj.history(start=start, end=end, auto_adjust=False)
        if not df.empty:
            m_type = "上市 (.TW)" if suffix == ".TW" else "上櫃 (.TWO)"
            try:
                name = t_obj.info.get('shortName') or symbol
            except:
                name = symbol
            return df, m_type, name
    return pd.DataFrame(), "", symbol

@st.cache_data(ttl=3600)
def get_cached_eps(symbol, start, end):
    """抓取 FinMind EPS 數據"""
    try:
        eps_df = dl.taiwan_stock_financial_statement(
            stock_id=symbol,
            start_date=start.strftime('%Y-%m-%d'),
            end_date=end.strftime('%Y-%m-%d')
        )
        if not eps_df.empty:
            eps_data = eps_df[eps_df['type'] == 'EPS'][['date', 'value']]
            eps_data['date'] = pd.to_datetime(eps_data['date'])
            eps_data['Year'] = eps_data['date'].dt.year
            annual_eps = eps_data.groupby('Year')['value'].sum().reset_index()
            return annual_eps
    except:
        return pd.DataFrame()

# --- 4. 數據處理與繪圖 ---
if fetch_button:
    try:
        with st.spinner('同步數據中...'):
            df_yf, m_type, s_name = get_cached_data(raw_id, start_date, end_date)
            
            if df_yf.empty:
                st.error("找不到股價數據，可能是請求太頻繁，請稍候再試。")
            else:
                st.success(f"已找到：{raw_id} {s_name}")
                
                # 重新取樣
                df_yf = df_yf.resample(
                    'W-FRI' if "週" in period_choice else 'ME' if "月" in period_choice else 'YE' if "年" in period_choice else 'D'
                ).agg({'Close': 'last', 'Volume': 'sum'}).reset_index()

                # EPS 處理
                annual_eps = get_cached_eps(raw_id, start_date, end_date)
                df_yf['Year'] = df_yf['Date'].dt.year
                
                if not annual_eps.empty:
                    annual_eps.columns = ['Year', 'Annual_EPS']
                    df_final = pd.merge(df_yf, annual_eps, on='Year', how='left').ffill()
                else:
                    df_final = df_yf
                    df_final['Annual_EPS'] = None

                # 繪圖
                fig = go.Figure()
                if 'Annual_EPS' in df_final.columns and df_final['Annual_EPS'].notnull().any():
                    for ratio in pe_ratios:
                        fig.add_trace(go.Scatter(x=df_final['Date'], y=df_final['Annual_EPS']*ratio, 
                                                 mode='lines', name=f'{ratio}x', line=dict(dash='dot', width=1)))
                
                fig.add_trace(go.Scatter(x=df_final['Date'], y=df_final['Close'], 
                                         mode='lines', name='實際收盤價', line=dict(color='red', width=2)))
                
                fig.update_layout(title=f"{s_name} 河流圖", template="plotly_white", height=600)
                st.plotly_chart(fig, use_container_width=True)
                
                st.subheader("💰 年度 EPS 統計")
                st.dataframe(annual_eps.sort_values('Year', ascending=False) if not annual_eps.empty else "無資料")

    except Exception as e:
        st.error(f"錯誤：{e}")
