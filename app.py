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
            <div style="font-size: 1.6rem; font-weight: bold; color: {color}; line-height: 1.1;">{value}</div>
        </div>
    """, unsafe_allow_html=True)

# --- 資料重取樣工具 (將日K轉為週K/月K) ---
def resample_df(df, rule):
    # rule: 'W' (週), 'M' (月)
    logic = {
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Sell_Pressure': 'sum' # 賣壓加總
    }
    # 如果有 Volume 也可以加總，這裡專注於您需要的欄位
    if 'Volume' in df.columns:
        logic['Volume'] = 'sum'

    resampled = df.resample(rule).agg(logic)
    # 移除因為重取樣可能產生的空值行
    resampled = resampled.dropna(subset=['Open', 'High', 'Low', 'Close'])
    return resampled

# --- 主程式 ---
def main():
    # CSS 全局樣式
    st.markdown("""
        <style>
            .block-container { padding-top: 1rem; padding-bottom: 1rem; }
            .header-container { display: flex; align-items: baseline; padding-bottom: 8px; border-bottom: 1px solid #eee; margin-bottom: 15px; }
            .main-title { font-size: 1.5rem; font-weight: bold; color: #333; margin-right: 12px; }
            .sub-title { font-size: 0.8rem; color: #888; font-weight: normal; }
            /* 調整 Tab 標籤樣式，讓 D/W/M 更明顯 */
            button[data-baseweb="tab"] > div { font-size: 1.2rem; font-weight: bold; width: 50px; text-align: center; }
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
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")

        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 'Long_Cost', 'Short_Cost', 'Sell_Pressure', 'Volume']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '').replace('nan', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        if 'Sell_Pressure' in df.columns:
            df['Sell_Pressure'] = df['Sell_Pressure'].fillna(0)
        
        # 設定 Date 為 Index (為了重取樣與畫圖方便)
        df = df.set_index('Date')

        # 取得最新一筆資料 (用於顯示卡片)
        last_row = df.iloc[-1]
        
        def fmt(val):
            try: return str(int(val))
            except: return "0"

        ref_divider = float(last_row.get('Divider', 0))
        ref_long = float(last_row.get('Long_Cost', 0))
        ref_short = float(last_row.get('Short_Cost', 0))

        # --- 2. 顯示頂部資訊卡片 (固定顯示最新日數據) ---
        c1, c2, c3, c4, c5 = st.columns([1, 1, 2, 1, 1])
        with c1: display_card("📅 最新日期", last_row.name.strftime("%Y-%m-%d"))
        with c2: display_card("⚖️ 明日多空分界", fmt(ref_divider), color="#333", help_text="(開+低+收)/3")
        with c3: display_card("🔮 明日三關價", f"{fmt(last_row.get('Upper_Pass',0))}/{fmt(last_row.get('Mid_Pass',0))}/{fmt(last_row.get('Lower_Pass',0))}", color="#555")
        with c4: display_card("🔴 外資多方成本", fmt(ref_long), color="#d63031")
        with c5: display_card("🟢 外資空方成本", fmt(ref_short), color="#00b894")

        # --- 3. 準備畫圖所需的計算 (上個月賣壓 - 僅用於日K) ---
        current_date = last_row.name
        first_day_this_month = current_date.replace(day=1)
        last_day_prev_month = first_day_this_month - timedelta(days=1)
        target_year = last_day_prev_month.year
        target_month = last_day_prev_month.month
        
        mask = (df.index.year == target_year) & (df.index.month == target_month)
        prev_month_df = df[mask]
        
        if not prev_month_df.empty:
            p_max = float(prev_month_df['Sell_Pressure'].max())
            p_min = float(prev_month_df['Sell_Pressure'].min())
            date_max = prev_month_df['Sell_Pressure'].idxmax()
            date_min = prev_month_df['Sell_Pressure'].idxmin()
        else:
            p_max, p_min = 0.0, 0.0
            date_max, date_min = current_date, current_date

        # ==========================================
        # ★ 標籤切換區 (D / W / M)
        # ==========================================
        tab_d, tab_w, tab_m = st.tabs(["D", "W", "M"])

        # 設定通用樣式
        mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)

        # --- Tab D: 日 K 線圖 ---
        with tab_d:
            df_d = df.tail(60)
            add_plots_d = []
            if 'Sell_Pressure' in df_d.columns:
                add_plots_d.append(mpf.make_addplot(df_d['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='賣壓', alpha=0.3))

            try:
                fig_d, axlist_d = mpf.plot(
                    df_d, type='candle', style=s, title="", ylabel='指數', 
                    addplot=add_plots_d, volume=False, panel_ratios=(3, 1), 
                    returnfig=True, figsize=(12, 6), tight_layout=True
                )
                
                # 日K 專屬：每 5 天標記一次 X 軸
                xtick_locs = []
                xtick_labels = []
                for i, date_val in enumerate(df_d.index):
                    if i % 5 == 0:
                        xtick_locs.append(i)
                        xtick_labels.append(date_val.strftime('%Y-%m-%d'))
                axlist_d[0].set_xticks(xtick_locs)
                axlist_d[0].set_xticklabels(xtick_labels)

                # 日K 專屬：畫出上個月賣壓支撐壓力線
                if len(axlist_d) > 2:
                    ax_pressure = axlist_d[2]
                    try: idx_max = df_d.index.get_loc(date_max)
                    except: idx_max = 0 
                    try: idx_min = df_d.index.get_loc(date_min)
                    except: idx_min = 0
                    x_end = len(df_d)

                    if p_max > 0:
                        ax_pressure.plot([idx_max, x_end], [p_max, p_max], color='red', linestyle='--', linewidth=1.5)
                        ax_pressure.text(x_end + 0.5, p_max, f'{p_max:.1f}', color='red', va='center', fontsize=10, fontweight='bold')
                    if p_min > 0:
                        ax_pressure.plot([idx_min, x_end], [p_min, p_min], color='green', linestyle='--', linewidth=1.5)
                        ax_pressure.text(x_end + 0.5, p_min, f'{p_min:.1f}', color='green', va='center', fontsize=10, fontweight='bold')
                    ax_pressure.set_yticks([])

                st.pyplot(fig_d, use_container_width=True)
            except Exception as e:
                st.error(f"日線圖繪製錯誤: {e}")

        # --- Tab W: 週 K 線圖 ---
        with tab_w:
            # 轉換為週K
            df_w = resample_df(df, 'W-FRI') # 視週五為一週結束
            df_w_plot = df_w.tail(60) # 顯示最近 60 週
            
            add_plots_w = []
            if 'Sell_Pressure' in df_w_plot.columns:
                add_plots_w.append(mpf.make_addplot(df_w_plot['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='賣壓', alpha=0.3))

            try:
                fig_w, axlist_w = mpf.plot(
                    df_w_plot, type='candle', style=s, title="", ylabel='指數',
                    addplot=add_plots_w, volume=False, panel_ratios=(3, 1),
                    returnfig=True, figsize=(12, 6), tight_layout=True
                )
                # 清除副圖 Y 軸刻度
                if len(axlist_w) > 2:
                    axlist_w[2].set_yticks([])
                
                st.pyplot(fig_w, use_container_width=True)
            except Exception as e:
                st.error(f"週線圖繪製錯誤 (可能資料量不足): {e}")

        # --- Tab M: 月 K 線圖 ---
        with tab_m:
            # 轉換為月K
            df_m = resample_df(df, 'ME') # Month End
            df_m_plot = df_m.tail(60) # 顯示最近 60 月
            
            add_plots_m = []
            if 'Sell_Pressure' in df_m_plot.columns:
                add_plots_m.append(mpf.make_addplot(df_m_plot['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='賣壓', alpha=0.3))

            try:
                fig_m, axlist_m = mpf.plot(
                    df_m_plot, type='candle', style=s, title="", ylabel='指數',
                    addplot=add_plots_m, volume=False, panel_ratios=(3, 1),
                    returnfig=True, figsize=(12, 6), tight_layout=True
                )
                # 清除副圖 Y 軸刻度
                if len(axlist_m) > 2:
                    axlist_m[2].set_yticks([])
                    
                st.pyplot(fig_m, use_container_width=True)
            except Exception as e:
                st.error(f"月線圖繪製錯誤 (可能資料量不足): {e}")

        # --- 詳細數據 (共用) ---
        with st.expander("查看詳細歷史數據"):
            st.dataframe(df.sort_index(ascending=False), use_container_width=True)

    else:
        st.warning("⚠️ 資料庫為空或無法讀取，請檢查 Google Sheet 連線。")

if __name__ == "__main__":
    main()
