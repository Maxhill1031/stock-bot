import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta, datetime
import yfinance as yf
import pytz

# --- 設定 ---
SHEET_NAME = "Daily_Stock_Data"
st.set_page_config(page_title="台股期貨AI儀表板", layout="wide")

# --- 連接 Google Sheet (讀取日資料) ---
def get_data():
    try:
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            sheet = client.open(SHEET_NAME).sheet1
            data = sheet.get_all_records()
            return pd.DataFrame(data)
        else:
            st.error("找不到 Secrets 設定")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"資料庫連線失敗: {e}")
        return pd.DataFrame()

# --- ★ 使用 yfinance 抓取即時分鐘資料 ---
def fetch_realtime_data():
    try:
        ticker = yf.Ticker("TX=F")
        df = ticker.history(period="1d", interval="1m")
        if df.empty: return None
        
        # 轉換時區
        if df.index.tzinfo is None:
             df.index = df.index.tz_localize('UTC').tz_convert('Asia/Taipei')
        else:
             df.index = df.index.tz_convert('Asia/Taipei')
        
        df = df.rename(columns={'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'})
        return df
    except Exception as e:
        st.error(f"Yahoo Finance 連線錯誤: {e}")
        return None

# --- 自定義數據卡片 ---
def display_card(label, value, color="black", help_text=""):
    tooltip_html = f'title="{help_text}"' if help_text else ''
    st.markdown(f"""
        <div style="
            background-color: white;
            padding: 10px 5px;
            border-radius: 8px;
            border: 1px solid #e0e0e0;
            text-align: center;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            " {tooltip_html}>
            <div style="font-size: 0.85rem; color: #666; margin-bottom: 2px;">{label}</div>
            <div style="font-size: 1.8rem; font-weight: bold; color: {color}; line-height: 1.1;">{value}</div>
        </div>
    """, unsafe_allow_html=True)

# --- 主程式 ---
def main():
    st.markdown("""
        <style>
            .block-container { padding-top: 1rem; padding-bottom: 1rem; padding-left: 1rem; padding-right: 1rem; }
            .header-container { display: flex; align-items: baseline; padding-bottom: 8px; border-bottom: 1px solid #eee; margin-bottom: 15px; }
            .main-title { font-size: 1.5rem; font-weight: bold; color: #333; margin-right: 12px; }
            .sub-title { font-size: 0.8rem; color: #888; font-weight: normal; }
            button[data-baseweb="tab"] > div { font-size: 1.1rem; font-weight: bold; }
        </style>
        <div class="header-container">
            <span class="main-title">📊 台股期貨自動分析系統</span>
            <span class="sub-title">數據來源：期交所/證交所/Yahoo財經 | 自動更新</span>
        </div>
    """, unsafe_allow_html=True)

    # 1. 讀取日資料
    df = get_data()
    
    if not df.empty:
        # ★ 修正重點 1：清除欄位名稱的空白 (防止 key error 或抓不到欄位)
        df.columns = df.columns.str.strip()
        
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")
        
        # ★ 修正重點 2：強力轉換數字 (去除逗號，強制轉 float)
        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 'Long_Cost', 'Short_Cost', 'Sell_Pressure']
        
        for col in numeric_cols:
            if col in df.columns:
                # 先轉字串，把逗號去掉，再轉數字
                df[col] = df[col].astype(str).str.replace(',', '').replace('nan', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 補 0 (防止繪圖崩潰)
        if 'Sell_Pressure' in df.columns:
            df['Sell_Pressure'] = df['Sell_Pressure'].fillna(0)

        last_row = df.iloc[-1]
        
        # 關鍵數值 (給 Tab 2 即時圖用) - 確保是純數字
        ref_divider = float(last_row.get('Divider', 0))
        ref_long = float(last_row.get('Long_Cost', 0))
        ref_short = float(last_row.get('Short_Cost', 0))

        def fmt(val):
            try: return str(int(val))
            except: return "0"

        # =========================================================
        # ★ 建立頁籤
        # =========================================================
        tab1, tab2 = st.tabs(["📅 每日盤後分析", "⚡ 即時行情走勢"])

        # ---------------------------------------------------------
        # Tab 1: 每日盤後分析
        # ---------------------------------------------------------
        with tab1:
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1: display_card("📅 最新日期", last_row['Date'].strftime("%Y-%m-%d"))
            with c2: display_card("⚖️ 明日多空分界", fmt(ref_divider), color="#333", help_text="(開+低+收)/3")
            with c3: display_card("🔮 明日三關價", f"{fmt(last_row.get('Upper_Pass',0))}/{fmt(last_row.get('Mid_Pass',0))}/{fmt(last_row.get('Lower_Pass',0))}", color="#555")
            with c4: display_card("🔴 外資多方成本", fmt(ref_long), color="#d63031")
            with c5: display_card("🟢 外資空方成本", fmt(ref_short), color="#00b894")

            # 計算上月賣壓
            current_date = last_row['Date']
            first_day_this_month = current_date.replace(day=1)
            last_day_prev_month = first_day_this_month - timedelta(days=1)
            target_year = last_day_prev_month.year
            target_month = last_day_prev_month.month
            
            mask = (df['Date'].dt.year == target_year) & (df['Date'].dt.month == target_month)
            prev_month_df = df[mask]
            
            if not prev_month_df.empty:
                p_max = float(prev_month_df['Sell_Pressure'].max())
                p_min = float(prev_month_df['Sell_Pressure'].min())
                date_max = prev_month_df.loc[prev_month_df['Sell_Pressure'].idxmax(), 'Date']
                date_min = prev_month_df.loc[prev_month_df['Sell_Pressure'].idxmin(), 'Date']
            else:
                p_max, p_min = 0.0, 0.0
                date_max, date_min = current_date, current_date

            # 繪製歷史日 K 線圖
            df_chart = df.tail(60).set_index("Date")
            mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
            s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
            
            add_plots = []
            if 'Sell_Pressure' in df_chart.columns:
                # 這裡確保 data 是 float，防止 TypeError
                add_plots.append(mpf.make_addplot(df_chart['Sell_Pressure'].astype(float), panel=1, color='blue', type='bar', ylabel='', alpha=0.3))

            try:
                fig, axlist = mpf.plot(
                    df_chart, type='candle', style=s, title="", ylabel='', addplot=add_plots, 
                    volume=False, panel_ratios=(3, 1), returnfig=True, figsize=(10, 5), tight_layout=True
                )

                # X 軸每 5 天標記
                xtick_locs = []
                xtick_labels = []
                for i, date_val in enumerate(df_chart.index):
                    if i % 5 == 0:
                        xtick_locs.append(i)
                        xtick_labels.append(date_val.strftime('%Y-%m-%d'))
                axlist[0].set_xticks(xtick_locs)
                axlist[0].set_xticklabels(xtick_labels)

                # 副圖賣壓
