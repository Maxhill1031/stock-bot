import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 設定 ---
SHEET_NAME = "Daily_Stock_Data"
st.set_page_config(page_title="台股期貨AI儀表板", layout="wide")

# --- 連接 Google Sheet ---
def get_data():
    try:
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
            st.error("找不到 Secrets 設定，請檢查 Streamlit 後台。")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"資料庫連線失敗: {e}")
        return pd.DataFrame()

# --- 主程式 ---
def main():
    st.title("📊 台股期貨自動分析系統")
    st.markdown("數據來源：期交所/證交所 | 自動更新")

    df = get_data()
    
    if not df.empty:
        # --- 資料處理 ---
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")

        # 強制轉數值
        numeric_cols = ['Open', 'High', 'Low', 'Close', 
                        'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 
                        'Long_Cost', 'Short_Cost', 'Sell_Pressure']
        
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        last_row = df.iloc[-1]
        
        def fmt(val):
            try:
                return str(int(val))
            except:
                return "0"

        # --- 2. 頂部資訊看板 (Metrics) ---
        
        c1, c2, c3, c4, c5 = st.columns(5)
        
        with c1:
            st.metric("📅 最新日期", last_row['Date'].strftime("%Y-%m-%d"))
        
        with c2:
            div_val = fmt(last_row.get('Divider', 0))
            st.metric("⚖️ 明日多空分界", div_val, help="(開+低+收)/3")

        with c3:
            u = fmt(last_row.get('Upper_Pass', 0))
            m = fmt(last_row.get('Mid_Pass', 0))
            l = fmt(last_row.get('Lower_Pass', 0))
            st.metric("🔮 明日三關價 (上/中/下)", f"{u} / {m} / {l}")
            
        with c4:
            st.metric("🔴 外資多方成本", fmt(last_row.get('Long_Cost', 0)))
            
        with c5:
            st.metric("🟢 外資空方成本", fmt(last_row.get('Short_Cost', 0)))

        # --- 3. 繪圖 (無標籤極簡版) ---
        
        df_chart = df.tail(60).set_index("Date")
        
        # K線圖樣式
        mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
        
        add_plots = []
        if 'Sell_Pressure' in df_chart.columns:
            # ★ 修改處 1: ylabel='' (移除 Pressure 文字)
            add_plots.append(mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='', alpha=0.3))
        
        fig, ax = mpf.plot(
            df_chart, 
            type='candle', 
            style=s, 
            title="", 
            ylabel='',   # ★ 修改處 2: 這裡設為空字串 (移除 Price 文字)
            addplot=add_plots, 
            volume=False, 
            panel_ratios=(3, 1), 
            returnfig=True, 
            figsize=(10, 5),
            tight_layout=True
        )
        
        st.pyplot(fig, use_container_width=True)
        
        # --- 4. 數據表格 ---
        with st.expander("查看詳細歷史數據"):
            st.dataframe(df.sort_index(ascending=False), use_container_width=True)
            
    else:
        st.warning("⚠️ 資料庫為空，請確認 Bot 是否已執行寫入。")

if __name__ == "__main__":
    main()