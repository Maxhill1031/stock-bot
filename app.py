import streamlit as st
import pandas as pd
import requests
import datetime
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 設定常數 ---
SHEET_NAME = "Daily_Stock_Data" # 您的 Google Sheet 名稱
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

# --- 1. 連接 Google Sheet ---
def get_google_sheet_data():
    # 從 Streamlit 的 Secrets 讀取憑證 (部署時會設定)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    # 這裡使用 Streamlit 的 secrets 管理功能，避免金鑰外洩
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    try:
        sheet = client.open(SHEET_NAME).sheet1
        return sheet
    except Exception as e:
        st.error(f"找不到 Google Sheet，請確認名稱是否為 '{SHEET_NAME}' 且已分享給服務帳戶。錯誤: {e}")
        return None

# --- 2. 爬蟲功能 (同之前邏輯) ---
def fetch_daily_data():
    st.info("正在執行每日爬蟲...")
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    # --- A. 期交所籌碼 ---
    long_cost, short_cost = 0, 0
    try:
        url_chip = "https://www.taifex.com.tw/cht/3/futContractsDate"
        dfs = pd.read_html(url_chip)
        df = dfs[0]
        target = df[df.iloc[:, 1].astype(str).str.contains("臺股期貨", na=False) & 
                    df.iloc[:, 2].astype(str).str.contains("外資", na=False)]
        
        if not target.empty:
            long_vol = float(target.iloc[0, 3])
            long_amt = float(target.iloc[0, 4])
            short_vol = float(target.iloc[0, 5])
            short_amt = float(target.iloc[0, 6])
            
            long_cost = (long_amt * 1000) / long_vol * 1000 / 200 if long_vol > 0 else 0
            short_cost = (short_amt * 1000) / short_vol * 1000 / 200 if short_vol > 0 else 0
    except Exception as e:
        st.warning(f"籌碼抓取失敗 (可能是假日): {e}")
        return None

    # --- B. 期交所行情 ---
    ohlc = None
    try:
        url_ohlc = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
        dfs = pd.read_html(url_ohlc)
        df_ohlc = dfs[0]
        target_ohlc = df_ohlc[df_ohlc.iloc[:, 0].astype(str).str.contains("臺股期貨", na=False) & 
                              ~df_ohlc.iloc[:, 0].astype(str).str.contains("盤後", na=False)]
        
        if not target_ohlc.empty:
            data = target_ohlc.iloc[0]
            open_p = float(data[2])
            high_p = float(data[3])
            low_p = float(data[4])
            close_p = float(data[5])
            
            mid_pass = (high_p + low_p) / 2
            up_pass = low_p + (high_p - low_p) * 1.382
            low_pass = high_p - (high_p - low_p) * 1.382
            
            ohlc = (open_p, high_p, low_p, close_p, up_pass, mid_pass, low_pass)
    except:
        st.warning("行情抓取失敗")
        return None

    # --- C. 證交所賣壓 ---
    pressure = 0
    try:
        url_twse = "https://www.twse.com.tw/exchangeReport/MI_5MINS?response=json"
        r = requests.get(url_twse, headers=HEADERS)
        data = r.json()
        if data['stat'] == 'OK':
            first = data['data'][0]
            if "09:00" in first[0]:
                pressure = float(first[4].replace(',', '')) / 10000
    except:
        st.warning("賣壓抓取失敗")
        return None

    if ohlc is None:
        return None

    return {
        "Date": today_str,
        "Open": ohlc[0], "High": ohlc[1], "Low": ohlc[2], "Close": ohlc[3],
        "Long_Cost": long_cost, "Short_Cost": short_cost,
        "Upper_Pass": ohlc[4], "Mid_Pass": ohlc[5], "Lower_Pass": ohlc[6],
        "Sell_Pressure": pressure
    }

# --- 3. 主程式介面 ---
def main():
    st.title("📈 台股期貨每日自動分析")
    
    sheet = get_google_sheet_data()
    if not sheet:
        return

    # 讀取現有資料
    try:
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty:
            df['Date'] = pd.to_datetime(df['Date'])
    except:
        df = pd.DataFrame()

    # 按鈕：手動觸發更新 (Streamlit 打開時也可以自動檢查)
    if st.button("🔄 執行今日資料抓取"):
        new_data = fetch_daily_data()
        if new_data:
            today_str = new_data['Date']
            
            # 檢查是否已存在
            exists = False
            if not df.empty:
                # 轉換為字串比對
                if today_str in df['Date'].dt.strftime("%Y-%m-%d").values:
                    exists = True
            
            if not exists:
                # 寫入 Google Sheet
                # 轉換數值為列表
                row_values = list(new_data.values())
                # 如果是第一筆，先寫標題
                if df.empty:
                    sheet.append_row(list(new_data.keys()))
                
                sheet.append_row(row_values)
                st.success(f"成功寫入 {today_str} 資料！")
                st.experimental_rerun() # 重新整理頁面
            else:
                st.info("今日資料已存在，無需更新。")
        else:
            st.error("今日無完整資料或尚未開盤。")

    # --- 顯示圖表 ---
    if not df.empty:
        # 只取最後 60 筆
        df_chart = df.sort_values(by="Date").tail(60).set_index("Date")
        
        st.subheader("近 60 日 K 線圖與賣壓")
        
        # 繪圖設定
        mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc)
        
        apds = [
            mpf.make_addplot(df_chart['Mid_Pass'], color='orange', width=0.7),
            mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='Pressure'),
        ]
        
        fig, ax = mpf.plot(df_chart, type='candle', style=s, 
                           addplot=apds, volume=False, panel_ratios=(2, 1), 
                           returnfig=True)
        
        st.pyplot(fig)
        
        # 顯示詳細數據表格
        st.subheader("詳細數據")
        st.dataframe(df_chart.sort_index(ascending=False))

if __name__ == "__main__":
    main()