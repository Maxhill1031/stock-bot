import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta, datetime
import requests
import yfinance as yf # ★ 新增：必須引入 yfinance
import pytz # ★ 新增：處理時區

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

# --- ★ 修改：改用 Yahoo Finance 抓取即時分K數據 (給 Tab 2 用) ---
def fetch_realtime_data():
    try:
        # TX=F 是 Yahoo Finance 的台指期代號
        ticker = yf.Ticker("TX=F")
        # period="1d" (抓一天), interval="1m" (1分鐘K棒)
        df = ticker.history(period="1d", interval="1m")
        
        if df.empty:
            return None
        
        # 處理時區問題 (Yahoo 預設是 UTC，轉為台灣時間)
        if df.index.tzinfo is None:
             df.index = df.index.tz_localize('UTC').tz_convert('Asia/Taipei')
        else:
             df.index = df.index.tz_convert('Asia/Taipei')
        
        # 重新命名欄位以符合 mplfinance 格式
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

    # 1. 先讀取日資料 (兩個 Tab 都會用到)
    df = get_data()
    
    if not df.empty:
        # --- ★ 必須加入：資料清洗 (防止 TypeError) ---
        # 如果不加這段，Google Sheet 裡的 "28,250" 會導致程式崩潰
        df.columns = df.columns.str.strip() 
        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 'Long_Cost', 'Short_Cost', 'Sell_Pressure']
        for col in numeric_cols:
            if col in df.columns:
                # 先轉字串去掉逗號，再轉數字
                df[col] = df[col].astype(str).str.replace(',', '').replace('nan', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        # -------------------------------------------

        # 資料預處理
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")
        
        if 'Sell_Pressure' in df.columns:
            df['Sell_Pressure'] = df['Sell_Pressure'].fillna(0)

        # 取得最新一筆日資料 (用於 Tab 1 顯示卡片，也用於 Tab 2 畫參考線)
        last_row = df.iloc[-1]
        
        # 關鍵數值 (給 Tab 2 即時圖用)
        ref_divider = float(last_row.get('Divider', 0))
        ref_long = float(last_row.
