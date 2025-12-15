import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta, datetime
import requests
import yfinance as yf  # ★ 新增：Yahoo Finance 套件
import pytz            # ★ 新增：時區處理

# --- 設定 ---
SHEET_NAME = "Daily_Stock_Data"
st.set_page_config(page_title="台股期貨AI儀表板", layout="wide")

# --- 連接 Google Sheet (讀取日資料 - 完全不動) ---
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

# --- ★ 修改：改用 Yahoo Finance 抓取即時分K數據 (取代原本的 Wantgoo) ---
def fetch_realtime_data():
    try:
        # TX=F 是 Yahoo Finance 的台指期代號
        # interval="1m" 代表抓取 1 分鐘線
        ticker = yf.Ticker("TX=F")
        df = ticker.history(period="1d", interval="1m")
        
        if df.empty:
            return None
        
        # 處理時區問題 (轉為台灣時間)
        if df.index.tzinfo is None:
             df.index = df.index.tz_localize('UTC').tz_convert('Asia/Taipei')
        else:
             df.index = df.index.tz_convert('Asia/Taipei')
        
        # 重新命名欄位以符合 mplfinance 要求
        df = df.rename(columns={'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'})
        return df
    except Exception as e:
        st.error(f"Yahoo Finance 連線錯誤: {e}")
        return None

# --- 自定義數據卡片 (完全不動) ---
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
    # CSS 全局樣式
    st.markdown("""
        <style>
            .block-container { padding-top: 1rem; padding-bottom: 1rem; padding-left: 1rem; padding-right: 1rem; }
            .header-container { display: flex; align-items: baseline; padding-bottom: 8px; border-bottom: 1px solid #eee; margin-bottom: 15px; }
            .main-title { font-size: 1.5rem; font-weight: bold; color: #333; margin-right: 12px; }
            .sub-title { font-size: 0.8rem; color: #888; font-weight: normal; }
            /* 調整 Tab 字體 */
            button[data-baseweb="tab"] > div { font-size: 1.1rem; font-weight: bold; }
        </style>
        <div class="header-container">
            <span class="main-title">📊 台股期貨自動分析系統</span>
            <span class="sub-title">數據來源：期交所/證交所/Yahoo財經 | 自動更新</span>
        </div>
    """, unsafe_allow_html=True)

    # 1. 先讀取日資料
    df = get_data()
    
    if not df.empty:
        # 資料預處理 (保留你原本的邏輯)
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")
        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 'Long_Cost', 'Short_Cost', 'Sell_Pressure']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        if 'Sell_Pressure' in df.columns:
            df['Sell_Pressure'] = df['Sell_Pressure'].fillna(0)

        last_row = df.iloc[-1]
        
        # 關鍵數值
        ref_divider = last_row.get('Divider', 0)
        ref_long = last_row.get('Long_Cost', 0)
        ref_short = last_row.get('Short_Cost', 0)

        def fmt(val):
            try: return str(int(val))
            except: return "0"

        # =========================================================
        # ★ 建立頁籤 (Tabs)
        # =========================================================
        tab1, tab2 = st.tabs(["📅 每日盤後分析", "⚡ 即時行情走勢"])

        # ---------------------------------------------------------
        # Tab 1: 每日盤後分析 (完全不動)
        # ---------------------------------------------------------
        with tab1:
            c1, c2, c3, c4, c5 = st.columns(5)
            with c1: display_card("📅 最新日期", last_row['Date'].strftime("%Y-%m-%d"))
            with c2: display_card("⚖️ 明日多空分界", fmt(ref_divider), color="#333", help_text="(開+低+收)/3")
            with c3: display_card("🔮 明日三關價", f"{fmt(last_row.get('Upper_Pass',0))}/{fmt(last_row.get('Mid_Pass',0))}/{fmt(last_row.get('Lower_Pass',0))}", color="#555")
            with c4: display_card("🔴 外資多方成本", fmt(ref_long), color="#d63031")
            with c5: display_card("🟢 外資空方成本", fmt(ref_short), color="#00b894")

            current_date = last_row['Date']
            first_day_this_month = current_date.replace(day=1)
            last_day_prev_month = first_day_this_month - timedelta(days=1)
            target_year
