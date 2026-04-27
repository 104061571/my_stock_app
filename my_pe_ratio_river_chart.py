import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from FinMind.data import DataLoader

# --- 頁面設定 ---
st.set_page_config(page_title="台股全市場河流圖 - 穩定版", layout="wide")

# 初始化 FinMind (全域定義)
dl = DataLoader()

st.title("📈 台股上市/上櫃本益比河流圖 (穩定版)")
st.write("支援上市/上櫃自動辨識，並顯示「真實收盤價」與「年度加總 EPS」。")
st.markdown("---")

# --- 側邊欄設定 ---
with st.sidebar:
    st.header("🔍 查詢參數")
    raw_id = st.text_input("輸入股票代碼 (如: 2330 或 8069)", value="2330")
    
    period_choice = st.selectbox(
        "選擇顯示週期",
        options=["日 (Daily)", "週 (Weekly)", "月 (Monthly)", "年 (Yearly)"],
        index=0
    )
    
    start_date = st.date_input("開始日期", value=pd.to_datetime("2020-01-01"))
    end_date = st.date_input("結束日期", value=pd.to_datetime("today"))
    
    st.subheader("📏 河流倍數設定")
    pe_ratios = [
        st.number_input("倍數 A", value=15.0, step=0.5),
        st.number_input("倍數 B", value=20.0, step=0.5),
        st.number_input("倍數 C", value=25.0, step=0.5),
        st.number_input("倍數 D", value=30.0, step=0.5)
    ]
    
    fetch_button = st.button("更新數據")

# --- 核心邏輯：資料處理與快取 ---

@st.cache_data(ttl=3600)  # 快取 1 小時，避免頻繁請求導致 Rate Limit
def get_stock_data(symbol, start, end):
    """依序嘗試上市與上櫃，並獲取真實收盤價。"""
    for suffix in [".TW", ".TWO"]:
        t_str = f"{symbol}{suffix}"
        ticker_obj = yf.Ticker(t_str)
        # auto_adjust=False 確保獲取原始價格
        df = ticker_obj.history(start=start, end=end, auto_adjust=False)
        
        if not df.empty and 'Close' in df.columns:
            market_type = "上市 (.TW)" if suffix == ".TW" else "上櫃 (.TWO)"
            try:
                # 獲取名稱，若抓不到則顯示代碼
                stock_name = ticker_obj.info.get('shortName') or ticker_obj.info.get('longName') or symbol
            except:
                stock_name = symbol
            return df, market_type, stock_name
    return pd.DataFrame(), "", symbol

@st.cache_data(ttl=3600)
def get_eps_data(symbol, start, end):
    """透過 FinMind 獲取年度加總 EPS。"""
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
            annual_eps.columns = ['Year', 'Annual_EPS']
            return annual_eps
    except:
        pass
    return pd.DataFrame()

def resample_data(df, period):
    """根據週期取樣。"""
    agg_dict = {'Close': 'last', 'Volume': 'sum'}
    if period == "週 (Weekly)":
        df = df.resample('W-FRI').agg(agg_dict)
    elif period == "月 (Monthly)":
        df = df.resample('ME').agg(agg_dict)
    elif period == "年 (Yearly)":
        df = df.resample('YE').agg(agg_dict)
    return df

# --- 執行與繪圖 ---
if fetch_button:
    try:
        with st.spinner('正在分析數據中...'):
            # 1. 抓取資料 (優先從快取讀取)
            df_stock, m_type, s_name = get_stock_data(raw_id, start_date, end_date)
            
            if df_stock.empty:
                st.error(f"❌ 找不到 {raw_id} 的數據。")
            else:
                st.success(f"✅ 已讀取：{raw_id} {s_name} ({m_type})")
                
                if isinstance(df_stock.columns, pd.MultiIndex):
                    df_stock.columns = df_stock.columns.get_level_values(0)
                
                df_resampled = resample_data(df_stock, period_choice).reset_index()
                annual_eps = get_eps_data(raw_id, start_date, end_date)

                # 數據合併
                df_resampled['Year'] = df_resampled['Date'].dt.year
                if not annual_eps.empty:
                    df_final = pd.merge(df_resampled, annual_eps, on='Year', how='left')
                    df_final['Annual_EPS'] = df_final['Annual_EPS'].ffill()
                else:
                    st.warning("⚠️ 查無財報數據。")
                    df_final = df_resampled
                    df_final['Annual_EPS'] = None

                # --- 繪製 Plotly 圖表 ---
                fig = go.Figure()
                
                # 繪製河流線
                if not annual_eps.empty:
                    for ratio in pe_ratios:
                        fig.add_trace(go.Scatter(
                            x=df_final['Date'], y=df_final['Annual_EPS'] * ratio,
                            mode='lines', name=f'{ratio}x PE', line=dict(dash='dot', width=1), opacity=0.5
                        ))

                # 繪製實際收盤價
                fig.add_trace(go.Scatter(
                    x=df_final['Date'], y=df_final['Close'],
                    mode='lines', name='當日收盤價', line=dict(color='firebrick', width=2.5)
                ))

                fig.update_layout(
                    title=f"{raw_id} {s_name} ({m_type}) - 實際價格河流圖",
                    hovermode="x unified",
                    template="plotly_white",
                    height=600,
                    yaxis_title="價格 (TWD)"
                )
                st.plotly_chart(fig, use_container_width=True)

                # 下方統計
                st.markdown("---")
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader("💰 歷年加總 EPS")
                    if not annual_eps.empty:
                        st.dataframe(annual_eps.sort_values('Year', ascending=False), hide_index=True)
                with c2:
                    st.subheader("📊 成交量趨勢")
                    st.bar_chart(df_final.set_index('Date')['Volume'])

    except Exception as e:
        st.error(f"發生錯誤: {e}")
