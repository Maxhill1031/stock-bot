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
        # 使用 Streamlit Secrets
        creds_dict = dict(st.secrets["gcp_service_account"])
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        
        # 讀取全部資料
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"資料庫連線失敗: {e}")
        return pd.DataFrame()

# --- 主程式 ---
def main():
    st.title("📊 台股期貨自動分析系統")
    st.markdown("數據來源：期交所/證交所 | 更新頻率：每日 15:30 自動更新")

    # 1. 讀取資料
    df = get_data()
    
    if not df.empty:
        # 資料處理
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")
        
        # 顯示最新數據
        last_row = df.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("最新日期", last_row['Date'].strftime("%Y-%m-%d"))
        c2.metric("收盤價", f"{last_row['Close']:.0f}")
        c3.metric("外資空方成本", f"{last_row['Short_Cost']:.0f}")
        c4.metric("開盤賣壓", f"{last_row['Sell_Pressure']:.2f} 萬")

        # 2. 繪圖 (只取最後 60 筆)
        df_chart = df.tail(60).set_index("Date")
        
        # 設定 K 線圖樣式
        mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
        
        # 附加圖表：中關價(線) + 賣壓(柱狀)
        apds = [
            mpf.make_addplot(df_chart['Mid_Pass'], color='orange', width=1.5, linestyle='-'), # 中關價
            mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='賣壓(萬)', alpha=0.5),
        ]
        
        fig, ax = mpf.plot(df_chart, type='candle', style=s, 
                           title="\n台股期貨日 K 線圖 (橘線=中關價)",
                           addplot=apds, volume=False, panel_ratios=(3, 1), 
                           returnfig=True, figsize=(10, 8))
        
        st.pyplot(fig)
        
        # 3. 顯示原始數據表格
        with st.expander("查看詳細歷史數據"):
            st.dataframe(df.sort_index(ascending=False))
            
    else:
        st.warning("目前資料庫為空，請等待下午 15:30 自動排程執行，或檢查 GitHub Actions。")

if __name__ == "__main__":
    main()