import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from FinMind.data import DataLoader

st.set_page_config(page_title="台股實際收盤價河流圖", layout="wide")

# 初始化 FinMind
dl = DataLoader()

st.title("📈 台股本益比河流圖 (實際收盤價版)")
st.write("此版本顯示當日原始收盤價，未經過除權息還原修正。")
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
    
    fetch_button = st.button("更新數據並繪圖")

# --- 數據轉換函式 ---
def resample_stock_data(df, period):
    # 強制只針對 'Close' 進行取樣
    agg_dict = {'Close': 'last', 'Volume': 'sum'}
    if period == "週 (Weekly)":
        df = df.resample('W-FRI').agg(agg_dict)
    elif period == "月 (Monthly)":
        df = df.resample('ME').agg(agg_dict)
    elif period == "年 (Yearly)":
        df = df.resample('YE').agg(agg_dict)
    return df

# --- 核心抓取函式 ---
def get_clean_data(symbol, start, end):
    # 同時考慮上市與上櫃
    suffix_list = [".TW", ".TWO"]
    df = pd.DataFrame()
    m_type = ""
    s_name = symbol

    for suffix in suffix_list:
        t_str = f"{symbol}{suffix}"
        t_obj = yf.Ticker(t_str)
        # auto_adjust=False 確保拿到原始收盤價
        df = t_obj.history(start=start, end=end, auto_adjust=False)
        
        if not df.empty:
            m_type = "上市 (.TW)" if suffix == ".TW" else "上櫃 (.TWO)"
            try:
                info = t_obj.info
                s_name = info.get('longName') or info.get('shortName') or symbol
            except:
                pass
            break
    return df, m_type, s_name

if fetch_button:
    try:
        with st.spinner('抓取真實報價中...'):
            df_yf, market_type, stock_name = get_clean_data(raw_id, start_date, end_date)
            
            if df_yf.empty:
                st.error("找不到數據。")
            else:
                # 移除 MultiIndex 並強制選擇原始 Close
                if isinstance(df_yf.columns, pd.MultiIndex):
                    df_yf.columns = df_yf.columns.get_level_values(0)
                
                # 重新取樣週期
                df_resampled = resample_stock_data(df_yf, period_choice).reset_index()

                # 抓取財報
                eps_df = dl.taiwan_stock_financial_statement(
                    stock_id=raw_id,
                    start_date=start_date.strftime('%Y-%m-%d'),
                    end_date=end_date.strftime('%Y-%m-%d')
                )
                
                if not eps_df.empty:
                    eps_data = eps_df[eps_df['type'] == 'EPS'][['date', 'value']]
                    eps_data['date'] = pd.to_datetime(eps_data['date'])
                    eps_data['Year'] = eps_data['date'].dt.year
                    annual_eps = eps_data.groupby('Year')['value'].sum().reset_index()
                    annual_eps.columns = ['Year', 'Annual_EPS']
                    
                    # 合併
                    df_resampled['Year'] = df_resampled['Date'].dt.year
                    df_final = pd.merge(df_resampled, annual_eps, on='Year', how='left')
                    df_final['Annual_EPS'] = df_final['Annual_EPS'].ffill()
                else:
                    st.warning("無財報數據。")
                    df_final = df_resampled
                    annual_eps = pd.DataFrame()

                # 繪圖
                fig = go.Figure()
                if not annual_eps.empty:
                    for ratio in pe_ratios:
                        fig.add_trace(go.Scatter(
                            x=df_final['Date'], y=df_final['Annual_EPS'] * ratio,
                            mode='lines', name=f'{ratio}x PE', line=dict(dash='dot', width=1)
                        ))

                fig.add_trace(go.Scatter(
                    x=df_final['Date'], y=df_final['Close'], # 這裡絕對是原始 Close
                    mode='lines', name='實際收盤價', line=dict(color='firebrick', width=2.5)
                ))

                fig.update_layout(
                    title=f"{raw_id} {stock_name} ({market_type})",
                    hovermode="x unified",
                    template="plotly_white",
                    height=600
                )
                st.plotly_chart(fig, use_container_width=True)

                # 下方數據
                st.markdown("---")
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader("💰 年度總 EPS")
                    st.dataframe(annual_eps.sort_values('Year', ascending=False) if not annual_eps.empty else annual_eps)
                with c2:
                    st.subheader("📉 成交量")
                    st.bar_chart(df_final.set_index('Date')['Volume'])

    except Exception as e:
        st.error(f"錯誤: {e}")
