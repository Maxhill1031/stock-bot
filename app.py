import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta, datetime
import requests
import yfinance as yf
import pytz

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

# --- ★ 修改：Yahoo Finance 抓取函式 (移除衝突的 Session 設定) ---
def fetch_realtime_data():
    try:
        # 直接呼叫，不手動塞 Session，解決 curl_cffi 錯誤
        ticker = yf.Ticker("TX=F")
        df = ticker.history(period="1d", interval="1m")
        
        if df.empty:
            return None
        
        # 處理時區 (轉為台灣時間)
        if df.index.tzinfo is None:
             df.index = df.index.tz_localize('UTC').tz_convert('Asia/Taipei')
        else:
             df.index = df.index.tz_convert('Asia/Taipei')
        
        # 欄位更名
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
        # 資料清洗
        df.columns = df.columns.str.strip() 
        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 'Long_Cost', 'Short_Cost', 'Sell_Pressure']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '').replace('nan', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")
        if 'Sell_Pressure' in df.columns:
            df['Sell_Pressure'] = df['Sell_Pressure'].fillna(0)

        last_row = df.iloc[-1]
        
        # 關鍵數值
        ref_divider = float(last_row.get('Divider', 0))
        ref_long = float(last_row.get('Long_Cost', 0))
        ref_short = float(last_row.get('Short_Cost', 0))

        def fmt(val):
            try: return str(int(val))
            except: return "0"

        # 建立頁籤
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

            df_chart = df.tail(60).set_index("Date")
            
            mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
            s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
            add_plots = []
            if 'Sell_Pressure' in df_chart.columns:
                add_plots.append(mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='', alpha=0.3))

            try:
                fig, axlist = mpf.plot(
                    df_chart, type='candle', style=s, title="", ylabel='', addplot=add_plots, 
                    volume=False, panel_ratios=(3, 1), returnfig=True, figsize=(10, 5), tight_layout=True
                )

                xtick_locs = []
                xtick_labels = []
                for i, date_val in enumerate(df_chart.index):
                    if i % 5 == 0:
                        xtick_locs.append(i)
                        xtick_labels.append(date_val.strftime('%Y-%m-%d'))
                axlist[0].set_xticks(xtick_locs)
                axlist[0].set_xticklabels(xtick_labels)

                if len(axlist) > 2:
                    ax_pressure = axlist[2]
                    try: idx_max = df_chart.index.get_loc(date_max)
                    except: idx_max = 0 
                    try: idx_min = df_chart.index.get_loc(date_min)
                    except: idx_min = 0
                    x_end = len(df_chart)

                    if p_max > 0:
                        ax_pressure.plot([idx_max, x_end], [p_max, p_max], color='red', linestyle='--', linewidth=1.5, zorder=10)
                    if p_min > 0:
                        ax_pressure.plot([idx_min, x_end], [p_min, p_min], color='green', linestyle='--', linewidth=1.5, zorder=10)

                    ax_pressure.set_yticks([]) 
                    ax_pressure.text(x_end + 0.5, p_max, f'{p_max:.1f}', color='red', va='center', fontsize=10, fontweight='bold')
                    ax_pressure.text(x_end + 0.5, p_min, f'{p_min:.1f}', color='green', va='center', fontsize=10, fontweight='bold')

                st.pyplot(fig, use_container_width=True)
            except Exception as e:
                st.error(f"歷史圖表繪製錯誤: {e}")

            with st.expander("查看詳細歷史數據"):
                st.dataframe(df.sort_index(ascending=False), use_container_width=True)

        # ---------------------------------------------------------
        # Tab 2: 即時行情走勢 (Yahoo Finance)
        # ---------------------------------------------------------
        with tab2:
            st.subheader("📈 台指期即時走勢 (Yahoo Finance)")
            
            col_btn, col_info = st.columns([1, 5])
            with col_btn:
                if 'realtime_df' not in st.session_state:
                    st.session_state['realtime_df'] = None

                if st.button("🔄 截取最新行情", type="primary"):
                    with st.spinner("連線 Yahoo Finance 中..."):
                        # ★ 呼叫沒有 session 的函式
                        df_rt = fetch_realtime_data()
                        if df_rt is not None and not df_rt.empty:
                            st.session_state['realtime_df'] = df_rt
                            st.success(f"已更新")
                        else:
                            st.warning("無法取得資料 (可能休市)")

            if st.session_state['realtime_df'] is not None:
                df_chart_rt = st.session_state['realtime_df']
                
                line_div = [ref_divider] * len(df_chart_rt)
                line_long = [ref_long] * len(df_chart_rt)
                line_short = [ref_short] * len(df_chart_rt)

                add_plots_rt = []
                if ref_divider > 0:
                     add_plots_rt.append(mpf.make_addplot(line_div, color='black', width=1.5))
                if ref_long > 0:
                     add_plots_rt.append(mpf.make_addplot(line_long, color='red', linestyle='--', width=1.2))
                if ref_short > 0:
                     add_plots_rt.append(mpf.make_addplot(line_short, color='green', linestyle='--', width=1.2))

                mc_rt = mpf.make_marketcolors(up='r', down='g', inherit=True)
                s_rt = mpf.make_mpf_style(marketcolors=mc_rt, gridstyle=':', y_on_right=True)

                try:
                    fig_rt, axlist_rt = mpf.plot(
                        df_chart_rt, type='candle', style=s_rt, title="", ylabel='',
                        addplot=add_plots_rt, volume=True, panel_ratios=(3, 1),
                        returnfig=True, figsize=(10, 6), tight_layout=True
                    )
                    
                    ax_rt = axlist_rt[0]
                    x_pos = len(df_chart_rt) + 1
                    
                    if ref_divider > 0:
                        ax_rt.text(x_pos, ref_divider, f'分界 {int(ref_divider)}', color='black', va='center', fontweight='bold')
                    if ref_long > 0:
                        ax_rt.text(x_pos, ref_long, f'多本 {int(ref_long)}', color='red', va='center', fontweight='bold')
                    if ref_short > 0:
                        ax_rt.text(x_pos, ref_short, f'空本 {int(ref_short)}', color='green', va='center', fontweight='bold')
                    
                    current_price = df_chart_rt['Close'].iloc[-1]
                    ax_rt.text(x_pos, current_price, f'◀ {int(current_price)}', color='blue', va='center', fontweight='bold')

                    st.pyplot(fig_rt, use_container_width=True)
                    with col_info:
                        last_time = df_chart_rt.index[-1].strftime('%H:%M')
                        st.info(f"最新資料時間: {last_time} (含盤後/夜盤)")

                except Exception as e:
                    st.error(f"即時圖繪製錯誤: {e}")
            else:
                st.info("👈 請點擊左側按鈕載入即時行情")

    else:
        st.warning("⚠️ 資料庫為空")

if __name__ == "__main__":
    main()
