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
# 新增參數 show_pressure 來控制是否顯示賣壓
def plot_interactive_chart(df, p_max=0, p_min=0, date_max=None, date_min=None, show_pressure=True):
    # 複製一份資料並建立字串格式的日期 (消除假日空隙)
    df = df.copy()
    df['Date_Str'] = df.index.strftime('%Y-%m-%d')
    
    # 定義 Tooltip 格式 (不顯示 K，只顯示數字)
    hover_text_k = (
        "<b>%{x}</b><br>" +
        "開盤: %{open:.0f}<br>" +
        "最高: %{high:.0f}<br>" +
        "最低: %{low:.0f}<br>" +
        "收盤: %{close:.0f}" +
        "<extra></extra>" 
    )

    # --- 情況 A: 要顯示賣壓 (日K) ---
    if show_pressure:
        fig = make_subplots(
            rows=2, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.03, 
            row_heights=[0.7, 0.3],
            subplot_titles=("指數走勢", "賣壓指標")
        )

        # 1. K 線圖 (放在第 1 列)
        fig.add_trace(go.Candlestick(
            x=df['Date_Str'], 
            open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            increasing_line_color='red', decreasing_line_color='green',
            name='K線',
            hovertemplate=hover_text_k
        ), row=1, col=1)

        # 2. 賣壓 Bar 圖 (放在第 2 列)
        hover_text_bar = (
            "<b>%{x}</b><br>" +
            "賣壓: %{y:.1f}" +
            "<extra></extra>"
        )
        fig.add_trace(go.Bar(
            x=df['Date_Str'], 
            y=df['Sell_Pressure'],
            marker_color='blue', opacity=0.3,
            name='賣壓',
            hovertemplate=hover_text_bar
        ), row=2, col=1)

        # 3. 畫賣壓虛線 (僅在顯示賣壓時才畫)
        chart_start_date = df.index[0]
        chart_end_date_str = df['Date_Str'].iloc[-1]

        if p_max > 0 and date_max is not None:
            if date_max < chart_start_date:
                start_x = df['Date_Str'].iloc[0]
            else:
                try: start_x = date_max.strftime('%Y-%m-%d')
                except: start_x = df['Date_Str'].iloc[0]

            fig.add_shape(type="line", x0=start_x, x1=chart_end_date_str, y0=p_max, y1=p_max,
                line=dict(color="red", width=1.5, dash="dash"), row=2, col=1)
            fig.add_annotation(x=chart_end_date_str, y=p_max, text=f"{p_max:.1f}",
                showarrow=False, xanchor="left", yanchor="middle", font=dict(color="red"), row=2, col=1)

        if p_min > 0 and date_min is not None:
            if date_min < chart_start_date:
                start_x = df['Date_Str'].iloc[0]
            else:
                try: start_x = date_min.strftime('%Y-%m-%d')
                except: start_x = df['Date_Str'].iloc[0]

            fig.add_shape(type="line", x0=start_x, x1=chart_end_date_str, y0=p_min, y1=p_min,
                line=dict(color="green", width=1.5, dash="dash"), row=2, col=1)
            fig.add_annotation(x=chart_end_date_str, y=p_min, text=f"{p_min:.1f}",
                showarrow=False, xanchor="left", yanchor="middle", font=dict(color="green"), row=2, col=1)

    # --- 情況 B: 不顯示賣壓 (週K/月K) ---
    else:
        # 只有單一圖表，不需要 subplots
        fig = go.Figure()

        # 只加 K 線圖
        fig.add_trace(go.Candlestick(
            x=df['Date_Str'], 
            open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
            increasing_line_color='red', decreasing_line_color='green',
            name='K線',
            hovertemplate=hover_text_k
        ))

    # --- 通用版面設定 ---
    fig.update_layout(
        margin=dict(l=10, r=50, t=30, b=10),
        height=500, # 高度統一
        xaxis_rangeslider_visible=False,
        showlegend=False,
        plot_bgcolor='white',
        paper_bgcolor='white',
        yaxis=dict(tickformat=".0f"), # Y軸不顯示 K
    )
    
    # 強制 X 軸為類別模式 (移除空隙)
    fig.update_xaxes(type='category', showgrid=True, gridcolor='#eee', gridwidth=1, 
                     tickmode='auto', nticks=10)
    fig.update_yaxes(showgrid=True, gridcolor='#eee', gridwidth=1)

    st.plotly_chart(fig, use_container_width=True)


# --- 主程式 ---
def main():
    st.markdown("""
        <style>
            .block-container { padding-top: 1rem; padding-bottom: 1rem; }
            .header-container { display: flex; align-items: baseline; padding-bottom: 8px; border-bottom: 1px solid #eee; margin-bottom: 15px; }
            .main-title { font-size: 1.5rem; font-weight: bold; color: #333; margin-right: 12px; }
            .sub-title { font-size: 0.8rem; color: #888; font-weight: normal; }
            button[data-baseweb="tab"] > div { font-size: 1.2rem; font-weight: bold; width: 50px; text-align: center; }
        </style>
        <div class="header-container">
            <span class="main-title">📊 台股期貨盤後分析</span>
            <span class="sub-title">數據來源：Google Sheet | 每日更新</span>
        </div>
    """, unsafe_allow_html=True)

    df = get_data()
    
    if not df.empty:
        # 資料清洗
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")

        numeric_cols = ['Open', 'High', 'Low', 'Close', 'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 'Long_Cost', 'Short_Cost', 'Sell_Pressure', 'Volume']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '').replace('nan', '')
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        if 'Sell_Pressure' in df.columns:
            df['Sell_Pressure'] = df['Sell_Pressure'].fillna(0)
        
        df = df.set_index('Date')
        last_row = df.iloc[-1]
        
        def fmt(val):
            try: return str(int(val))
            except: return "0"

        ref_divider = float(last_row.get('Divider', 0))
        ref_long = float(last_row.get('Long_Cost', 0))
        ref_short = float(last_row.get('Short_Cost', 0))

        # 頂部資訊卡片
        c1, c2, c3, c4, c5 = st.columns([1, 1, 2, 1, 1])
        with c1: display_card("📅 最新日期", last_row.name.strftime("%Y-%m-%d"))
        with c2: display_card("⚖️ 明日多空分界", fmt(ref_divider), color="#333", help_text="(開+低+收)/3")
        with c3: display_card("🔮 明日三關價", f"{fmt(last_row.get('Upper_Pass',0))}/{fmt(last_row.get('Mid_Pass',0))}/{fmt(last_row.get('Lower_Pass',0))}", color="#555")
        with c4: display_card("🔴 外資多方成本", fmt(ref_long), color="#d63031")
        with c5: display_card("🟢 外資空方成本", fmt(ref_short), color="#00b894")

        # 準備上個月賣壓數據 (僅用於日K)
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
            date_max, date_min = None, None

        # 標籤切換區
        tab_d, tab_w, tab_m = st.tabs(["D", "W", "M"])

        with tab_d:
            # 日K：show_pressure=True
            plot_interactive_chart(df.tail(60), p_max, p_min, date_max, date_min, show_pressure=True)

        with tab_w:
            df_w = resample_df(df, 'W-FRI')
            # 週K：show_pressure=False
            plot_interactive_chart(df_w.tail(60), show_pressure=False)

        with tab_m:
            df_m = resample_df(df, 'ME')
            # 月K：show_pressure=False
            plot_interactive_chart(df_m.tail(60), show_pressure=False)

        with st.expander("查看詳細歷史數據"):
            st.dataframe(df.sort_index(ascending=False), use_container_width=True)

    else:
        st.warning("⚠️ 資料庫為空或無法讀取，請檢查 Google Sheet 連線。")

if __name__ == "__main__":
    main()
