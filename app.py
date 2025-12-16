import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta, datetime
# import yfinance as yf  <-- 確保沒有使用 Yahoo
import pytz

# --- 設定 ---
SHEET_NAME = "Daily_Stock_Data"
st.set_page_config(page_title="台股期貨AI儀表板", layout="wide")

# --- 連接 Google Sheet (讀取日資料) ---
@st.cache_data(ttl=3600) # 緩存 1 小時
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

# --- 資料重新取樣 (Resampling) 函式 ---
def resample_data(df, period):
    if period == "日 K":
        return df
    
    # 週 K: 'W', 月 K: 'M'
    resample_period = 'W' if period == "週 K" else 'M'
    
    # OHLCV 重取樣邏輯: 開(first), 高(max), 低(min), 收(last), 量(sum)
    ohlcv_dict = {
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Volume': 'sum',
        # Sell_Pressure: 確保週/月是日數據的加總
        'Sell_Pressure': 'sum' 
    }
    
    # 使用 Pandas 標準的重取樣功能
    df_resampled = df.resample(resample_period).apply(ohlcv_dict)
    
    # 移除因為重取樣產生但無數據的行
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
            <span class="sub-title">數據來源：Google Sheet 分析數據 | 週期重組</span>
        </div>
    """, unsafe_allow_html=True)

    # 1. 讀取 Google Sheet 分析數據
    df_analysis = get_data()
    
    if df_analysis.empty:
        st.warning("⚠️ 資料庫為空，無法顯示分析數據。")
        return

    # --- 資料清理與準備 ---
    df_analysis.columns = df_analysis.columns.str.strip() 
    # 確保所有數字欄位都被正確處理，包括 Volume 和 Sell_Pressure
    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 'Long_Cost', 'Short_Cost', 'Sell_Pressure', 'Volume']
    for col in numeric_cols:
        if col in df_analysis.columns:
            # 處理千分位逗號和 NaN 錯誤
            df_analysis[col] = df_analysis[col].astype(str).str.replace(',', '').replace('nan', '')
            df_analysis[col] = pd.to_numeric(df_analysis[col], errors='coerce')
    
    # 設置 Date 為索引
    df_analysis['Date'] = pd.to_datetime(df_analysis['Date'])
    df_analysis = df_analysis.sort_values(by="Date").set_index("Date")
    
    if 'Sell_Pressure' in df_analysis.columns:
        df_analysis['Sell_Pressure'] = df_analysis['Sell_Pressure'].fillna(0)
    
    # 提取最新的日資料用於頂部卡片
    last_row = df_analysis.iloc[-1]
    ref_divider = float(last_row.get('Divider', 0))
    ref_long = float(last_row.get('Long_Cost', 0))
    ref_short = float(last_row.get('Short_Cost', 0))

    def fmt(val):
        try: return str(int(val))
        except: return "0"

    # --- 頂部資訊看板 ---
    st.header("📌 交易分析數據 (最新日資料)")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: display_card("📅 最新日期", last_row.name.strftime("%Y-%m-%d"))
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

    # 重新取樣數據
    df_resampled = resample_data(df_analysis, selected_period)
    
    # ★ 調整：顯示近 100 筆數據 (確保週K/月K有足夠長度)
    df_chart = df_resampled.tail(100)
    
    if df_chart.empty:
        st.warning(f"⚠️ 數據不足！Google Sheet 中沒有足夠的數據來組成 {selected_period} K 線圖。")
        return

    # 繪圖設定
    mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
    s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True, figcolor='w')
    
    add_plots = []
    
    # 賣壓副圖：只在日 K 且有 Sell_Pressure 數據時顯示
    has_sell_pressure = 'Sell_Pressure' in df_chart.columns and selected_period == "日 K"
    if has_sell_pressure:
        add_plots.append(mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='賣壓 (日K限定)', alpha=0.3))

    try:
        # 繪製 K 線圖
        fig, axlist = mpf.plot(
            df_chart, type='candle', style=s, title=f"台指期 {selected_period} 走勢圖 (數據量: {len(df_chart)} 筆)", 
            ylabel='指數', addplot=add_plots, 
            volume=False, 
            panel_ratios=(3, 1) if has_sell_pressure else (1, 0), # 只有日 K 有 Sell_Pressure 副圖
            returnfig=True, figsize=(12, 6), tight_layout=True
        )

        # 處理 X 軸和賣壓線的顯示 (僅限日 K)
        if selected_period == "日 K":
            # 調整 X 軸刻度顯示 (每 5 天標記一次)
            xtick_locs = []
            xtick_labels = []
            for i, date_val in enumerate(df_chart.index):
                if i % 5 == 0:
                    xtick_locs.append(i)
                    xtick_labels.append(date_val.strftime('%Y-%m-%d'))
            axlist[0].set_xticks(xtick_locs)
            axlist[0].set_xticklabels(xtick_labels)

            # 處理賣壓線的顯示
            if has_sell_pressure and len(axlist) > 2:
                ax_pressure = axlist[2]
                
                # 取得圖表範圍內的 Sell_Pressure 最大最小值
                p_max = df_chart['Sell_Pressure'].max()
                p_min = df_chart['Sell_Pressure'].min()
                
                x_end = len(df_chart)

                # 找到 Max/Min 發生在哪一天的索引位置
                try: 
                    idx_max = df_chart['Sell_Pressure'].idxmax()
                    idx_max_pos = df_chart.index.get_loc(idx_max)
                except: idx_max_pos = 0

                try: 
                    idx_min = df_chart['Sell_Pressure'].idxmin()
                    idx_min_pos = df_chart.index.get_loc(idx_min)
                except: idx_min_pos = 0

                # 畫線與標註
                if p_max > 0:
                    ax_pressure.plot([idx_max_pos, x_end], [p_max, p_max], color='red', linestyle='--', linewidth=1.5, zorder=10)
                    ax_pressure.text(x_end + 0.5, p_max, f'{p_max:.1f}', color='red', va='center', fontsize=10, fontweight='bold')
                if p_min > 0:
                    ax_pressure.plot([idx_min_pos, x_end], [p_min, p_min], color='green', linestyle='--', linewidth=1.5, zorder=10)
                    ax_pressure.text(x_end + 0.5, p_min, f'{p_min:.1f}', color='green', va='center', fontsize=10, fontweight='bold')
                
                ax_pressure.set_yticks([]) 
                ax_pressure.set_xticks([])

        st.pyplot(fig, use_container_width=True)

    except Exception as e:
        st.error(f"圖表繪製錯誤 (請確保 Google Sheet 數據格式正確): {e}")

    # 3. 詳細數據表格 (固定顯示日資料)
    st.markdown("---")
    with st.expander("查看詳細日歷史數據"):
        st.dataframe(df_analysis.sort_index(ascending=False), use_container_width=True)

if
