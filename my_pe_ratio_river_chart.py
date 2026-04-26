import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from FinMind.data import DataLoader

st.set_page_config(page_title="台股全市場河流圖分析", layout="wide")

# 初始化 FinMind
dl = DataLoader()

st.title("📈 台股上市/上櫃本益比河流圖系統")
st.write("自動辨識上市 (.TW) 與上櫃 (.TWO) 並顯示股票名稱")
st.markdown("---")

with st.sidebar:
    st.header("🔍 查詢參數")
    raw_id = st.text_input("輸入股票代碼", value="2330")
    
    period_choice = st.selectbox(
        "選擇顯示週期",
        options=["日 (Daily)", "週 (Weekly)", "月 (Monthly)", "年 (Yearly)"],
        index=0
    )
    
    start_date = st.date_input("開始日期", value=pd.to_datetime("2020-01-01"))
    end_date = st.date_input("結束日期", value=pd.to_datetime("today"))
    
    st.subheader("📏 河流倍數設定")
    pe_ratios = [
        st.number_input("倍數 A", value=15.0),
        st.number_input("倍數 B", value=20.0),
        st.number_input("倍數 C", value=25.0),
        st.number_input("倍數 D", value=30.0)
    ]
    
    fetch_button = st.button("開始抓取數據")

# --- 數據轉換函式 ---
def resample_stock_data(df, period):
    agg_dict = {'Close': 'last', 'Volume': 'sum'}
    if period == "週 (Weekly)":
        df = df.resample('W-FRI').agg(agg_dict)
    elif period == "月 (Monthly)":
        df = df.resample('ME').agg(agg_dict)
    elif period == "年 (Yearly)":
        df = df.resample('YE').agg(agg_dict)
    return df

# --- 核心：抓取股價與股票名稱 ---
def get_stock_info_and_data(symbol, start, end):
    # 嘗試上市
    suffix_list = [".TW", ".TWO"]
    df = pd.DataFrame()
    market_type = ""
    stock_name = "未知名稱"
    
    for suffix in suffix_list:
        ticker_str = f"{symbol}{suffix}"
        ticker_obj = yf.Ticker(ticker_str)
        df = ticker_obj.history(start=start, end=end)
        
        if not df.empty:
            market_type = "上市 (.TW)" if suffix == ".TW" else "上櫃 (.TWO)"
            # 嘗試抓取名稱 (longName 或 shortName)
            try:
                info = ticker_obj.info
                stock_name = info.get('longName') or info.get('shortName') or symbol
            except:
                stock_name = symbol # 抓不到名稱時回退顯示代碼
            break
            
    return df, market_type, stock_name

if fetch_button:
    try:
        with st.spinner(f'正在查詢 {raw_id} 的資訊與財報...'):
            # 1. 抓取股價與名稱
            df_yf, market_type, stock_full_name = get_stock_info_and_data(raw_id, start_date, end_date)
            
            if df_yf.empty:
                st.error(f"❌ 找不到代碼 {raw_id} 的數據。")
            else:
                # 顯示成功的確認資訊
                st.success(f"✅ 已找到：{raw_id} {stock_full_name} ({market_type})")
                
                # 處理 yfinance 欄位 (history 抓回來的通常是單層，保險起見再做處理)
                if isinstance(df_yf.columns, pd.MultiIndex):
                    df_yf.columns = df_yf.columns.get_level_values(0)
                
                # 執行週期轉換
                df_resampled = resample_stock_data(df_yf, period_choice).reset_index()

                # 2. 抓取財報 (FinMind)
                eps_df = dl.taiwan_stock_financial_statement(
                    stock_id=raw_id,
                    start_date=start_date.strftime('%Y-%m-%d'),
                    end_date=end_date.strftime('%Y-%m-%d')
                )
                
                if eps_df.empty:
                    st.warning("⚠️ 財報資料庫中無 EPS 數據。")
                    annual_eps = pd.DataFrame(columns=['Year', 'Annual_EPS'])
                else:
                    eps_data = eps_df[eps_df['type'] == 'EPS'][['date', 'value']]
                    eps_data['date'] = pd.to_datetime(eps_data['date'])
                    eps_data['Year'] = eps_data['date'].dt.year
                    annual_eps = eps_data.groupby('Year')['value'].sum().reset_index()
                    annual_eps.columns = ['Year', 'Annual_EPS']

                # 3. 合併與河流圖
                df_resampled['Year'] = df_resampled['Date'].dt.year
                df_final = pd.merge(df_resampled, annual_eps, on='Year', how='left')
                df_final['Annual_EPS'] = df_final['Annual_EPS'].ffill()

                # 繪圖
                fig = go.Figure()
                if not annual_eps.empty:
                    for ratio in pe_ratios:
                        fig.add_trace(go.Scatter(
                            x=df_final['Date'], y=df_final['Annual_EPS'] * ratio,
                            mode='lines', name=f'{ratio}x PE', line=dict(dash='dot', width=1), opacity=0.5
                        ))

                fig.add_trace(go.Scatter(
                    x=df_final['Date'], y=df_final['Close'],
                    mode='lines', name='實際收盤價', line=dict(color='firebrick', width=2.5)
                ))

                fig.update_layout(
                    # 標題加入股票名稱
                    title=f"{raw_id} {stock_full_name} - {period_choice} 走勢與河流圖",
                    hovermode="x unified",
                    template="plotly_white",
                    height=600
                )
                
                st.plotly_chart(fig, use_container_width=True)

                # 展示數據
                st.markdown("---")
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader(f"💰 {stock_full_name} 歷年 EPS")
                    st.dataframe(annual_eps.sort_values('Year', ascending=False), use_container_width=True, hide_index=True)
                with c2:
                    st.subheader("📉 成交量")
                    st.bar_chart(df_final.set_index('Date')['Volume'])

    except Exception as e:
        st.error(f"系統錯誤: {e}")