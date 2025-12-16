import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta, datetime

# --- 設定 ---
SHEET_NAME = "Daily_Stock_Data"
st.set_page_config(page_title="台股期貨AI儀表板", layout="wide")

# --- 連接 Google Sheet (讀取日資料) ---
def get_data():
    try:
        # 檢查是否設定了 Secrets
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            sheet = client.open(SHEET_NAME).sheet1
            data = sheet.get_all_records()
            return pd.DataFrame(data)
        else:
            st.error("找不到 Secrets 設定 (gcp_service_account)")
            return pd.DataFrame()
    except Exception as e:
        st.error(f"資料庫連線失敗: {e}")
        return pd.DataFrame()

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
            margin-bottom: 10px;
            " {tooltip_html}>
            <div style="font-size: 0.85rem; color: #666; margin-bottom: 2px;">{label}</div>
            # 這裡稍微縮小一點字體，確保更長的數字也能塞入
            <div style="font-size: 1.6rem; font-weight: bold; color: {color}; line-height: 1.1;">{value}</div>
        </div>
    """, unsafe_allow_html=True)

# --- 主程式 ---
def main():
    # CSS 全局樣式
    st.markdown("""
        <style>
            .block-container { padding-top: 1rem; padding-bottom: 1rem; }
            .header-container { display: flex; align-items: baseline; padding-bottom: 8px; border-bottom: 1px solid #eee; margin-bottom: 15px; }
            .main-title { font-size: 1.5rem; font-weight: bold; color: #333; margin-right: 12px; }
            .sub-title { font-size: 0.8rem; color: #888; font-weight: normal; }
        </style>
        <div class="header-container">
            <span class="main-title">📊 台股期貨盤後分析</span>
            <span class="sub-title">數據來源：Google Sheet | 每日更新</span>
        </div>
    """, unsafe_allow_html=True)

    # 1. 讀取 Google Sheet 資料
    df = get_data()
    
    if not df.empty:
        # --- 資料清洗 ---
        # 確保 Date 是時間格式並排序
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")

        # 處理數值欄位 (移除逗號, 轉為 float)
        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 'Long_Cost', 'Short_Cost', 'Sell_Pressure', 'Volume']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '').replace('nan', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 填補空值
        if 'Sell_Pressure' in df.columns:
            df['Sell_Pressure'] = df['Sell_Pressure'].fillna(0)

        # 取得最新一筆資料
        last_row = df.iloc[-1]
        
        # 格式化數值 (轉整數顯示)
        def fmt(val):
            try: return str(int(val))
            except: return "0"

        ref_divider = float(last_row.get('Divider', 0))
        ref_long = float(last_row.get('Long_Cost', 0))
        ref_short = float(last_row.get('Short_Cost', 0))

        # --- 2. 顯示頂部資訊卡片 (修改這裡) ---
        # 使用比例 [1, 1, 2, 1, 1] 讓中間的 c3 (三關價) 變寬
        c1, c2, c3, c4, c5 = st.columns([1, 1, 2, 1, 1])
        with c1: display_card("📅 最新日期", last_row['Date'].strftime("%Y-%m-%d"))
        with c2: display_card("⚖️ 明日多空分界", fmt(ref_divider), color="#333", help_text="(開+低+收)/3")
        with c3: display_card("🔮 明日三關價", f"{fmt(last_row.get('Upper_Pass',0))}/{fmt(last_row.get('Mid_Pass',0))}/{fmt(last_row.get('Lower_Pass',0))}", color="#555")
        with c4: display_card("🔴 外資多方成本", fmt(ref_long), color="#d63031")
        with c5: display_card("🟢 外資空方成本", fmt(ref_short), color="#00b894")

        # --- 3. 計算上個月的賣壓 (用於畫線) ---
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
            # 取得發生日期的 datetime
            date_max = prev_month_df.loc[prev_month_df['Sell_Pressure'].idxmax(), 'Date']
            date_min = prev_month_df.loc[prev_month_df['Sell_Pressure'].idxmin(), 'Date']
        else:
            p_max, p_min = 0.0, 0.0
            date_max, date_min = current_date, current_date

        # --- 4. 繪製圖表 (只取最後 60 筆) ---
        df_chart = df.tail(60).set_index("Date")
        
        # 設定 K 線圖樣式
        mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
        
        # 設定副圖 (賣壓柱狀圖)
        add_plots = []
        if 'Sell_Pressure' in df_chart.columns:
            add_plots.append(mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='賣壓', alpha=0.3))

        try:
            fig, axlist = mpf.plot(
                df_chart, type='candle', style=s, title="", ylabel='指數', 
                addplot=add_plots, volume=False, panel_ratios=(3, 1), 
                returnfig=True, figsize=(12, 6), tight_layout=True
            )

            # 自定義 X 軸標籤 (避免擁擠，每 5 天顯示一個)
            xtick_locs = []
            xtick_labels = []
            for i, date_val in enumerate(df_chart.index):
                if i % 5 == 0:
                    xtick_locs.append(i)
                    xtick_labels.append(date_val.strftime('%Y-%m-%d'))
            axlist[0].set_xticks(xtick_locs)
            axlist[0].set_xticklabels(xtick_labels)

            # 在副圖畫出「上月最大/最小賣壓」虛線
            if len(axlist) > 2:
                ax_pressure = axlist[2]
                
                # 找出日期在目前圖表中的索引位置
                try: idx_max = df_chart.index.get_loc(date_max)
                except: idx_max = 0 
                try: idx_min = df_chart.index.get_loc(date_min)
                except: idx_min = 0
                x_end = len(df_chart)

                # 畫紅線 (最大賣壓)
                if p_max > 0:
                    ax_pressure.plot([idx_max, x_end], [p_max, p_max], color='red', linestyle='--', linewidth=1.5)
                    ax_pressure.text(x_end + 0.5, p_max, f'{p_max:.1f}', color='red', va='center', fontsize=10, fontweight='bold')
                
                # 畫綠線 (最小賣壓)
                if p_min > 0:
                    ax_pressure.plot([idx_min, x_end], [p_min, p_min], color='green', linestyle='--', linewidth=1.5)
                    ax_pressure.text(x_end + 0.5, p_min, f'{p_min:.1f}', color='green', va='center', fontsize=10, fontweight='bold')

                # 隱藏副圖的 Y 軸刻度，保持乾淨
                ax_pressure.set_yticks([]) 

            st.pyplot(fig, use_container_width=True)

        except Exception as e:
            st.error(f"圖表繪製發生錯誤: {e}")

        # --- 5. 顯示詳細數據 ---
        with st.expander("查看詳細歷史數據"):
            st.dataframe(df.sort_index(ascending=False), use_container_width=True)

    else:
        st.warning("⚠️ 資料庫為空或無法讀取，請檢查 Google Sheet 連線。")

if __name__ == "__main__":
    main()
