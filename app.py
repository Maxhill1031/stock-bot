import streamlit as st
import pandas as pd
import mplfinance as mpf
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import timedelta

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
            data = sheet.get_all_records()
            return pd.DataFrame(data)
        else:
            st.error("找不到 Secrets 設定")
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
            <span class="sub-title">數據來源：期交所/證交所 | 自動更新</span>
        </div>
    """, unsafe_allow_html=True)

    df = get_data()
    
    if not df.empty:
        # --- 資料處理 ---
        df['Date'] = pd.to_datetime(df['Date'])
        df = df.sort_values(by="Date")

        numeric_cols = ['Open', 'High', 'Low', 'Close', 
                        'Upper_Pass', 'Mid_Pass', 'Lower_Pass', 'Divider', 
                        'Long_Cost', 'Short_Cost', 'Sell_Pressure']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        if 'Sell_Pressure' in df.columns:
            df['Sell_Pressure'] = df['Sell_Pressure'].fillna(0)

        last_row = df.iloc[-1]
        
        # --- 1. 計算「上個月」的賣壓極值與發生日期 ---
        current_date = last_row['Date']
        first_day_this_month = current_date.replace(day=1)
        last_day_prev_month = first_day_this_month - timedelta(days=1)
        target_year = last_day_prev_month.year
        target_month = last_day_prev_month.month
        
        # 篩選上個月資料
        mask = (df['Date'].dt.year == target_year) & (df['Date'].dt.month == target_month)
        prev_month_df = df[mask]
        
        if not prev_month_df.empty:
            # 數值
            p_max = float(prev_month_df['Sell_Pressure'].max())
            p_min = float(prev_month_df['Sell_Pressure'].min())
            # 發生日期 (重要：用來決定線畫到哪裡)
            date_max = prev_month_df.loc[prev_month_df['Sell_Pressure'].idxmax(), 'Date']
            date_min = prev_month_df.loc[prev_month_df['Sell_Pressure'].idxmin(), 'Date']
        else:
            p_max, p_min = 0.0, 0.0
            date_max, date_min = current_date, current_date

        def fmt(val):
            try: return str(int(val))
            except: return "0"

        # --- 2. 頂部資訊看板 ---
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1: display_card("📅 最新日期", last_row['Date'].strftime("%Y-%m-%d"))
        with c2: display_card("⚖️ 明日多空分界", fmt(last_row.get('Divider', 0)), color="#333", help_text="(開+低+收)/3")
        with c3: display_card("🔮 明日三關價", f"{fmt(last_row.get('Upper_Pass',0))}/{fmt(last_row.get('Mid_Pass',0))}/{fmt(last_row.get('Lower_Pass',0))}", color="#555")
        with c4: display_card("🔴 外資多方成本", fmt(last_row.get('Long_Cost', 0)), color="#d63031")
        with c5: display_card("🟢 外資空方成本", fmt(last_row.get('Short_Cost', 0)), color="#00b894")

        # --- 3. 繪圖 ---
        df_chart = df.tail(60).set_index("Date")
        
        # 線段設定：[ [(起點, 數值), (終點, 數值)], ... ]
        # 起點：圖表最左邊 (df_chart.index[0])
        # 終點：上個月發生的那一天 (date_max / date_min)
        lines_seq = [
            [(df_chart.index[0], p_max), (date_max, p_max)], # 上月最高 (紅)
            [(df_chart.index[0], p_min), (date_min, p_min)]  # 上月最低 (綠)
        ]
        lines_colors = ['red', 'green']

        mc = mpf.make_marketcolors(up='r', down='g', inherit=True)
        s = mpf.make_mpf_style(marketcolors=mc, gridstyle='--', y_on_right=True)
        
        add_plots = []
        if 'Sell_Pressure' in df_chart.columns:
            add_plots.append(mpf.make_addplot(df_chart['Sell_Pressure'], panel=1, color='blue', type='bar', ylabel='', alpha=0.3))

        try:
            fig, axlist = mpf.plot(
                df_chart, 
                type='candle', 
                style=s, 
                title="", 
                ylabel='', 
                addplot=add_plots, 
                # 使用 alines 畫指定長度的線
                alines=dict(alines=lines_seq, colors=lines_colors, linestyle='dashed', linewidths=1.5),
                volume=False, 
                panel_ratios=(3, 1), 
                returnfig=True,
                figsize=(10, 5),
                tight_layout=True
            )

            # X 軸每 5 天標記
            xtick_locs = []
            xtick_labels = []
            for i, date_val in enumerate(df_chart.index):
                if i % 5 == 0:
                    xtick_locs.append(i)
                    xtick_labels.append(date_val.strftime('%Y-%m-%d'))
            axlist[0].set_xticks(xtick_locs)
            axlist[0].set_xticklabels(xtick_labels)

            # ★ 副圖 Y 軸與數值標註
            if len(axlist) > 2:
                ax_pressure = axlist[2]
                
                # 1. 取消預設標值
                ax_pressure.set_yticks([]) 
                
                # 2. 標註數值 (使用 len(df_chart) 讓文字顯示在圖表右側外)
                # 紅色最高值
                ax_pressure.text(
                    len(df_chart) + 0.5, p_max, 
                    f'{p_max:.1f}', 
                    color='red', va='center', fontsize=10, fontweight='bold'
                )
                
                # 綠色最低值
                ax_pressure.text(
                    len(df_chart) + 0.5, p_min, 
                    f'{p_min:.1f}', 
                    color='green', va='center', fontsize=10, fontweight='bold'
                )

            st.pyplot(fig, use_container_width=True)
            
        except Exception as e:
            st.error(f"繪圖錯誤: {e}")

        with st.expander("查看詳細歷史數據"):
            st.dataframe(df.sort_index(ascending=False), use_container_width=True)
            
    else:
        st.warning("⚠️ 資料庫為空，請確認 Bot 是否已執行寫入。")

if __name__ == "__main__":
    main()