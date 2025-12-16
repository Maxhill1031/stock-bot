import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta, datetime
import yfinance as yf
import pytz

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

# --- 從 Yahoo Finance 抓取完整的歷史日線數據 ---
@st.cache_data(ttl=3600) # 緩存 1 小時，避免重複抓取
def fetch_full_history():
    try:
        # 抓取 TX=F 所有可得的歷史數據
        ticker = yf.Ticker("TX=F")
        df = ticker.history(period="max", interval="1d")
        
        if df.empty:
            return None
        
        # 重新命名欄位
        df = df.rename(columns={'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'})
        
        # 確保索引是 datetime 且去除時區
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except Exception as e:
        st.error(f"Yahoo Finance 歷史數據連線錯誤: {e}")
        return None

# --- 資料重新取樣 (Resampling) 函式 ---
def resample_data(df, period):
    if period == "日 K":
        # 日 K 不需要重新取樣
        return df
    
    # 重新取樣為週 K (W) 或月 K (M)
    resample_period = 'W' if period == "週 K" else 'M'
    
    # OHLC 重取樣邏輯: 開(first), 高(max), 低(min), 收(last), 量(sum)
    ohlc_dict = {
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum'
    }
    
    df_resampled = df.resample(resample_period).apply(ohlc_dict)
    
    # 移除因為重取樣產生但無數據的行 (例如當月還沒結束)
    df_resampled = df_resampled.dropna(subset=['Open', 'High', 'Low', 'Close'])
    
    return df_resampled

# --- 自定義數據卡片 (維持不動) ---
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
    st.markdown("""
        <style>
            .block-container { padding-top: 1rem; padding-bottom: 1rem; padding-left: 1rem; padding-right: 1rem; }
            .header-container { display: flex; align-items: baseline; padding-bottom: 8px; border-bottom: 1px solid #eee; margin-bottom: 15px; }
            .main-title { font-size: 1.5rem; font-weight: bold; color: #333; margin-right: 12px; }
            .sub-title { font-size: 0.8rem; color: #888; font-weight: normal; }
        </style>
        <div class="header-container">
            <span class="main-title">📊 台股期貨自動分析系統</span>
            <span class="sub-title">數據來源：期交所/證交所/Yahoo歷史數據 | 每日更新</span>
        </div>
    """, unsafe_allow_html=True)

    # 1. 讀取 Google Sheet 分析數據
    df_analysis = get_data()
    
    if df_analysis.empty:
        st.warning("⚠️ 資料庫為空，無法顯示分析數據。")
        return

    # 資料清洗 (確保能轉為數字)
    df_analysis.columns = df_analysis.columns.str.strip() 
    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 'Long_Cost', 'Short_Cost', 'Sell_Pressure']
    for col in numeric_cols:
        if col in df_analysis.columns:
            df_analysis[col] = df_analysis[col].astype(str).str.replace(',', '').replace('nan', '')
            df_analysis[col] = pd.to_numeric(df_analysis[col], errors='coerce')
    df_analysis['Date'] = pd.to_datetime(df_analysis['Date'])
    df_analysis = df_analysis.sort_values(by="Date")
    if 'Sell_Pressure' in df_analysis.columns:
        df_analysis['Sell_Pressure'] = df_analysis['Sell_Pressure'].fillna(0)

    last_row = df_analysis.iloc[-1]
    
    # 關鍵數值 (固定顯示最新日資料)
    ref_divider = float(last_row.get('Divider', 0))
    ref_long = float(last_row.get('Long_Cost', 0))
    ref_short = float(last_row.get('Short_Cost', 0))

    def fmt(val):
        try: return str(int(val))
        except: return "0"

    # --- 頂部資訊看板 (完全保留原本的呈現) ---
    st.header("📌 交易分析數據 (最新日資料)")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: display_card("📅 最新日期", last_row['Date'].strftime("%Y-%m-%d"))
    with c2: display_card("⚖️ 明日多空分界", fmt(ref_divider), color="#333", help_text="(開+低+收)/3")
    with c3: display_card("🔮 明日三關價", f"{fmt(last_row.get('Upper_Pass',0))}/{fmt(last_row.get('Mid_Pass',0))}/{fmt(last_row.get('Lower_Pass',0))}", color="#555")
    with c4: display_card("🔴 外資多方成本", fmt(ref_long), color="#d63031")
    with c5: display_card("🟢 外資空方成本", fmt(ref_short), color="#00b894")
    st.markdown("---")


    # 2. 歷史走勢圖表
    st.header("📈 歷史走勢分析")
    
    # 週期切換選單
    period_options = ["日 K", "週 K", "月 K"]
    col_select, col_empty = st.columns([1, 4])
    with col_select:
        selected_period = st.selectbox("選擇走勢週期", period_options, index=0)

    # 抓取 Yahoo 歷史數據
    df_history = fetch_full_history()

    if df_history is None:
        st.error("無法從 Yahoo Finance 取得歷史 K 線數據。")
        return

    # 重新取樣數據
    df_chart = resample_data(df_history, selected_period)
    
    # 只顯示近 60 筆數據 (日K=60天，週K=60週，月K=60月)
    df_chart = df_chart.tail(60)

    # 繪圖設定
    mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
    s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True, figcolor='w')
    
    # 確保 Sell_Pressure 的資料類型正確，並只取繪圖區間的資料
    df_pressure_plot = df_analysis.set_index("Date")
    # 將日資料的賣壓重新取樣到週/月 (取總和)
    if selected_period != "日 K" and 'Sell_Pressure' in df_pressure_plot.columns:
        df_pressure_plot = df_pressure_plot.resample(resample_period).sum()
    
    # 合併賣壓數據到 K 線圖 (僅適用於日 K)
    # 注意：將賣壓疊加到週/月 K 線上，邏輯上可能會有爭議，這裡為求呈現先簡化處理
    df_chart = df_chart.merge(df_pressure_plot[['Sell_Pressure']], left_index=True, right_index=True, how='left')
    df_chart['Sell_Pressure'] = df_chart['Sell_Pressure'].fillna(0)


    add_plots = []
    if 'Sell_Pressure' in df_chart.columns and selected_period == "日 K": # 只有日 K 才畫 Sell_Pressure
        add_plots.append(mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='賣壓 (日K限定)', alpha=0.3))

    try:
        # 繪製 K 線圖
        fig, axlist = mpf.plot(
            df_chart, type='candle', style=s, title=f"台指期 {selected_period} 走勢圖", 
            ylabel='指數', addplot=add_plots, 
            volume=False, 
            panel_ratios=(3, 1) if selected_period == "日 K" else (1, 0), # 只有日 K 有副圖
            returnfig=True, figsize=(12, 6), tight_layout=True
        )

        # 調整 X 軸刻度顯示 (只在日K時才每5天標記，週/月K讓mplfinance自動處理)
        if selected_period == "日 K":
            xtick_locs = []
            xtick_labels = []
            for i, date_val in enumerate(df_chart.index):
                if i % 5 == 0:
                    xtick_locs.append(i)
                    xtick_labels.append(date_val.strftime('%Y-%m-%d'))
            axlist[0].set_xticks(xtick_locs)
            axlist[0].set_xticklabels(xtick_labels)

        # 處理賣壓線的顯示 (僅限日 K)
        if selected_period == "日 K" and len(axlist) > 2:
            ax_pressure = axlist[2]
            
            # 確保 date_max/date_min 在當前 df_chart 的索引中
            date_max_index = df_chart.index.min()
            date_min_index = df_chart.index.min()
            
            if not prev_month_df.empty:
                # 重新計算 p_max/p_min 的 x 軸位置
                try: 
                    idx_max = df_chart.index.get_loc(date_max)
                    date_max_index = df_chart.index[idx_max]
                except: pass
                
                try: 
                    idx_min = df_chart.index.get_loc(date_min)
                    date_min_index = df_chart.index[idx_min]
                except: pass
            
            x_end = len(df_chart)

            # 找到日期在當前 df_chart 內的索引位置
            try: idx_max = df_chart.index.get_loc(date_max_index)
            except: idx_max = 0 
            try: idx_min = df_chart.index.get_loc(date_min_index)
            except: idx_min = 0

            # 畫線與標註 (zorder=10 確保浮在上層)
            if p_max > 0:
                ax_pressure.plot([idx_max, x_end], [p_max, p_max], color='red', linestyle='--', linewidth=1.5, zorder=10)
                ax_pressure.text(x_end + 0.5, p_max, f'{p_max:.1f}', color='red', va='center', fontsize=10, fontweight='bold')
            if p_min > 0:
                ax_pressure.plot([idx_min, x_end], [p_min, p_min], color='green', linestyle='--', linewidth=1.5, zorder=10)
                ax_pressure.text(x_end + 0.5, p_min, f'{p_min:.1f}', color='green', va='center', fontsize=10, fontweight='bold')
            
            ax_pressure.set_yticks([]) 
            ax_pressure.set_xticks([]) # 副圖不再顯示 X 軸標籤

        st.pyplot(fig, use_container_width=True)

    except Exception as e:
        st.error(f"圖表繪製錯誤: {e}")

    # 3. 詳細數據表格 (固定顯示日資料)
    st.markdown("---")
    with st.expander("查看詳細日歷史數據"):
        st.dataframe(df_analysis.sort_index(ascending=False), use_container_width=True)

if __name__ == "__main__":
    main()
