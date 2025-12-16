import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta, datetime
import plotly.graph_objects as go
from plotly.subplots import make_subplots

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

# --- 資料重取樣工具 ---
def resample_df(df, rule):
    logic = {
        'Open': 'first',
        'High': 'max',
        'Low': 'min',
        'Close': 'last',
        'Sell_Pressure': 'sum'
    }
    if 'Volume' in df.columns:
        logic['Volume'] = 'sum'
    resampled = df.resample(rule).agg(logic)
    resampled = resampled.dropna(subset=['Open', 'High', 'Low', 'Close'])
    return resampled

# --- ★ 核心：繪製互動式圖表 (Plotly) ---
def plot_interactive_chart(df, p_max=0, p_min=0, date_max=None, date_min=None):
    # 建立子圖表：上層是 K 線 (row=1)，下層是賣壓 (row=2)
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.7, 0.3],
        subplot_titles=("指數走勢", "賣壓指標")
    )

    # 1. 繪製 K 線圖 (台灣配色：紅漲綠跌)
    # Plotly 預設綠漲紅跌，需手動設定 increasing/decreasing
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color='red', decreasing_line_color='green',
        name='K線'
    ), row=1, col=1)

    # 2. 繪製賣壓 Bar 圖
    fig.add_trace(go.Bar(
        x=df.index, 
        y=df['Sell_Pressure'],
        marker_color='blue', opacity=0.3,
        name='賣壓'
    ), row=2, col=1)

    # 3. 畫出上個月最大/最小賣壓虛線 (僅當 p_max > 0 時)
    # 注意：在 Plotly 中，畫線是使用 "shapes"
    if p_max > 0:
        # 最大賣壓紅虛線
        fig.add_shape(type="line",
            x0=df.index[0], x1=df.index[-1], y0=p_max, y1=p_max,
            line=dict(color="red", width=1.5, dash="dash"),
            row=2, col=1
        )
        # 標註文字
        fig.add_annotation(
            x=df.index[-1], y=p_max, text=f"{p_max:.1f}",
            showarrow=False, xanchor="left", yanchor="middle",
            font=dict(color="red"), row=2, col=1
        )

    if p_min > 0:
        # 最小賣壓綠虛線
        fig.add_shape(type="line",
            x0=df.index[0], x1=df.index[-1], y0=p_min, y1=p_min,
            line=dict(color="green", width=1.5, dash="dash"),
            row=2, col=1
        )
        # 標註文字
        fig.add_annotation(
            x=df.index[-1], y=p_min, text=f"{p_min:.1f}",
            showarrow=False, xanchor="left", yanchor="middle",
            font=dict(color="green"), row=2, col=1
        )

    # 4. 版面調整
    fig.update_layout(
        margin=dict(l=10, r=50, t=30, b=10), # 邊界
        height=500, # 圖表高度
        xaxis_rangeslider_visible=False, # 隱藏底部的範圍滑桿 (太佔空間)
        hovermode='x unified', # 游標移上去時，顯示同一時間點的所有數據
        showlegend=False, # 隱藏圖例
        plot_bgcolor='white', # 背景白
        paper_bgcolor='white'
    )
    
    # 設定網格線
    fig.update_xaxes(showgrid=True, gridcolor='#eee', gridwidth=1)
    fig.update_yaxes(showgrid=True, gridcolor='#eee', gridwidth=1)

    # 渲染圖表
    st.plotly_chart(fig, use_container_width=True)


# --- 主程式 ---
def main():
    # CSS
    st.markdown("""
        <style>
            .block-container { padding-top: 1rem; padding-bottom: 1rem; }
            .header-container { display: flex; align-items: baseline; padding-bottom: 8px; border-bottom: 1px solid #eee; margin-bottom: 15px; }
            .main-title { font-size: 1.5rem; font-weight: bold; color: #333; margin-right: 12px; }
            .sub-title { font-size: 0.8rem; color: #888; font-weight: normal; }
            /* 調整 Tab 標籤樣式 */
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
        
        # 設定 Date 為 Index
        df = df.set_index('Date')

        # 最新一筆資料
        last_row = df.iloc[-1]
        
        def fmt(val):
            try: return str(int(val))
            except: return "0"

        ref_divider = float(last_row.get('Divider', 0))
        ref_long = float(last_row.get('Long_Cost', 0))
        ref_short = float(last_row.get('Short_Cost', 0))

        # --- 2. 顯示頂部資訊卡片 ---
        c1, c2, c3, c4, c5 = st.columns([1, 1, 2, 1, 1])
        with c1: display_card("📅 最新日期", last_row.name.strftime("%Y-%m-%d"))
        with c2: display_card("⚖️ 明日多空分界", fmt(ref_divider), color="#333", help_text="(開+低+收)/3")
        with c3: display_card("🔮 明日三關價", f"{fmt(last_row.get('Upper_Pass',0))}/{fmt(last_row.get('Mid_Pass',0))}/{fmt(last_row.get('Lower_Pass',0))}", color="#555")
        with c4: display_card("🔴 外資多方成本", fmt(ref_long), color="#d63031")
        with c5: display_card("🟢 外資空方成本", fmt(ref_short), color="#00b894")

        # --- 3. 準備「上個月賣壓」數據 (僅用於日K) ---
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
        else:
            p_max, p_min = 0.0, 0.0

        # ==========================================
        # ★ 標籤切換區 (D / W / M)
        # ==========================================
        tab_d, tab_w, tab_m = st.tabs(["D", "W", "M"])

        # --- Tab D: 日 K ---
        with tab_d:
            # 使用 Plotly 畫圖，傳入賣壓紅綠線數值
            plot_interactive_chart(df.tail(60), p_max, p_min)

        # --- Tab W: 週 K ---
        with tab_w:
            df_w = resample_df(df, 'W-FRI')
            # 週線不傳入 p_max, p_min，所以不畫紅綠線
            plot_interactive_chart(df_w.tail(60))

        # --- Tab M: 月 K ---
        with tab_m:
            df_m = resample_df(df, 'ME')
            # 月線不傳入 p_max, p_min
            plot_interactive_chart(df_m.tail(60))

        # --- 詳細數據 ---
        with st.expander("查看詳細歷史數據"):
            st.dataframe(df.sort_index(ascending=False), use_container_width=True)

    else:
        st.warning("⚠️ 資料庫為空或無法讀取，請檢查 Google Sheet 連線。")

if __name__ == "__main__":
    main()
