import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 設定 ---
SHEET_NAME = "Daily_Stock_Data"
st.set_page_config(page_title="台股期貨AI儀表板", layout="wide")

# --- 連接 Google Sheet (讀取專用) ---
def get_data():
    try:
        # 使用 Streamlit Secrets 讀取金鑰
        # 請確保你的 .streamlit/secrets.toml 或 Streamlit Cloud 後台有設定
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            sheet = client.open(SHEET_NAME).sheet1
            
            # 讀取全部資料
            data = sheet.get_all_records()
            return pd.DataFrame(data)
        else:
            st.error("找不到 Secrets 設定，請檢查 Streamlit 設定檔。")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"資料庫連線失敗: {e}")
        return pd.DataFrame()

# --- 主程式 ---
def main():
    st.title("📊 台股期貨自動分析系統")
    st.markdown("數據來源：期交所/證交所 | 資料源：Google Sheets (Bot 自動更新)")

    # 1. 讀取資料
    df = get_data()
    
    if not df.empty:
        # --- 資料清洗與轉換 ---
        # 確保日期格式正確
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")

        # 確保數值欄位真的是數字 (防止 Google Sheet 傳回字串)
        cols_to_numeric = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Long_Cost', 'Short_Cost', 'Sell_Pressure']
        for col in cols_to_numeric:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # --- 2. 顯示頂部關鍵數據 (Metrics) ---
        last_row = df.iloc[-1]
        
        # 輔助函式：轉整數與字串
        def fmt(val):
            try:
                return str(int(val))
            except:
                return "0"

        c1, c2, c3, c4 = st.columns(4)
        
        with c1:
            st.metric("📅 最新日期", last_row['Date'].strftime("%Y-%m-%d"))
        
        with c2:
            # 將三關價合併顯示
            u = fmt(last_row.get('Upper_Pass', 0))
            m = fmt(last_row.get('Mid_Pass', 0))
            l = fmt(last_row.get('Lower_Pass', 0))
            st.metric("📊 三關價 (上 / 中 / 下)", f"{u} / {m} / {l}")
            
        with c3:
            # 顯示顏色：紅色代表多方
            st.metric("🔴 外資多方成本", fmt(last_row.get('Long_Cost', 0)))
            
        with c4:
            # 顯示顏色：綠色代表空方
            st.metric("🟢 外資空方成本", fmt(last_row.get('Short_Cost', 0)))

        # --- 3. 繪圖 (只取最後 60 筆) ---
        st.subheader("趨勢圖表")
        
        # 準備繪圖資料 (index 必須是 datetime)
        df_chart = df.tail(60).set_index("Date")
        
        # 設定 K 線圖樣式 (使用 Yahoo 風格或自己定義)
        mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
        
        # 附加圖表設定
        add_plots = []
        
        # 加入三關價線 (上/中/下)
        if 'Upper_Pass' in df_chart.columns:
            add_plots.append(mpf.make_addplot(df_chart['Upper_Pass'], color='red', width=1, linestyle='--'))
        if 'Mid_Pass' in df_chart.columns:
            add_plots.append(mpf.make_addplot(df_chart['Mid_Pass'], color='orange', width=1.5))
        if 'Lower_Pass' in df_chart.columns:
            add_plots.append(mpf.make_addplot(df_chart['Lower_Pass'], color='green', width=1, linestyle='--'))
            
        # 加入賣壓 (副圖 Panel 1)
        if 'Sell_Pressure' in df_chart.columns:
            add_plots.append(mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='Pressure', alpha=0.3))
        
        # 繪製圖表
        # 注意：title 使用英文是為了避免在 Linux/Cloud 環境下出現中文字型亂碼 (豆腐塊)
        fig, ax = mpf.plot(
            df_chart, 
            type='candle', 
            style=s, 
            title=f"Taifex Futures Daily K-Line (Latest: {last_row['Date'].strftime('%Y-%m-%d')})",
            ylabel='Price',
            addplot=add_plots, 
            volume=False, 
            panel_ratios=(3, 1), 
            returnfig=True, 
            figsize=(12, 8)
        )
        
        st.pyplot(fig)
        
        # --- 4. 顯示原始數據表格 (可展開) ---
        with st.expander("查看詳細歷史數據"):
            # 整理顯示格式，把不需要的小數點去掉
            display_df = df.sort_index(ascending=False).copy()
            st.dataframe(display_df, use_container_width=True)
            
    else:
        st.warning("⚠️ 目前資料庫為空，請確認 bot.py 是否已成功執行並寫入 Google Sheet。")

if __name__ == "__main__":
    main()