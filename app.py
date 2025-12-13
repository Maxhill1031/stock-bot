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

# --- 自定義的小型數據卡片 (HTML) ---
def display_card(label, value, color="black", help_text=""):
    """
    用 HTML 渲染一個比 st.metric 更小的數據卡片
    """
    tooltip_html = f'title="{help_text}"' if help_text else ''
    st.markdown(f"""
        <div style="
            background-color: white;
            padding: 10px;
            border-radius: 5px;
            border: 1px solid #e0e0e0;
            text-align: center;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            " {tooltip_html}>
            <div style="font-size: 0.85rem; color: #666; margin-bottom: 4px;">{label}</div>
            <div style="font-size: 1.8rem; font-weight: bold; color: {color};">{value}</div>
        </div>
    """, unsafe_allow_html=True)

# --- 主程式 ---
def main():
    # 1. 客製化標題區 (標題變小 + 副標題移到後面)
    st.markdown("""
        <style>
            .header-container {
                display: flex;
                align-items: baseline; /* 讓文字底部對齊 */
                padding-bottom: 10px;
                border-bottom: 1px solid #eee;
                margin-bottom: 20px;
            }
            .main-title {
                font-size: 1.8rem; /* 比原本 st.title 小 */
                font-weight: bold;
                color: #333;
                margin-right: 15px;
            }
            .sub-title {
                font-size: 0.9rem;
                color: #888;
                font-weight: normal;
            }
        </style>
        <div class="header-container">
            <span class="main-title">📊 台股期貨自動分析系統</span>
            <span class="sub-title">數據來源：期交所/證交所 | 自動更新</span>
        </div>
    """, unsafe_allow_html=True)

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

        # --- 2. 頂部資訊看板 (使用自定義卡片) ---
        
        c1, c2, c3, c4, c5 = st.columns(5)
        
        with c1:
            display_card("📅 最新日期", last_row['Date'].strftime("%Y-%m-%d"))
        
        with c2:
            div_val = fmt(last_row.get('Divider', 0))
            display_card("⚖️ 明日多空分界", div_val, color="#333", help_text="(開+低+收)/3")

        with c3:
            u = fmt(last_row.get('Upper_Pass', 0))
            m = fmt(last_row.get('Mid_Pass', 0))
            l = fmt(last_row.get('Lower_Pass', 0))
            # 字體太長時，HTML 會自動換行或縮小，比 st.metric 更有彈性
            display_card("🔮 明日三關價", f"{u}/{m}/{l}", color="#555")
            
        with c4:
            display_card("🔴 外資多方成本", fmt(last_row.get('Long_Cost', 0)), color="#d63031")
            
        with c5:
            display_card("🟢 外資空方成本", fmt(last_row.get('Short_Cost', 0)), color="#00b894")

        # --- 3. 繪圖 (極簡乾淨版) ---
        
        df_chart = df.tail(60).set_index("Date")
        
        # K線圖樣式
        mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
        
        add_plots = []
        if 'Sell_Pressure' in df_chart.columns:
            add_plots.append(mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='', alpha=0.3))
        
        # 這裡加入一個間距，讓圖表跟上面的卡片分開一點點
        st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)

        fig, ax = mpf.plot(
            df_chart, 
            type='candle', 
            style=s, 
            title="", 
            ylabel='', 
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