import pandas as pd
import requests
import datetime
import os
import json
import io
import time
import urllib3
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 設定 ---
SHEET_NAME = "Daily_Stock_Data" 
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_google_sheet():
    json_creds = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if not json_creds:
        print("錯誤：找不到 GCP_SERVICE_ACCOUNT_JSON 環境變數")
        return None
    try:
        creds_dict = json.loads(json_creds)
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_NAME).sheet1
        return sheet
    except Exception as e:
        print(f"無法開啟 Google Sheet: {e}")
        return None

def clean_number(x):
    try:
        return float(str(x).replace(',', '').strip())
    except:
        return 0.0

def fetch_data_and_save():
    print("🚀 GitHub Action Bot 開始執行...")
    
    # 邏輯：永遠抓今天的日期，若為週末則不執行
    target_date = datetime.date.today()
    if target_date.weekday() >= 5:
        print("今天是週末，Bot 休息。")
        return

    date_slash = target_date.strftime("%Y/%m/%d")
    date_db = target_date.strftime("%Y-%m-%d") # 存入 Sheet 的格式
    print(f"目標日期: {date_db}")

    # 1. 抓取行情 (含三關價 & 多空分界)
    ohlc_data = None
    try:
        url = "https://www.taifex.com.tw/cht/3/futDailyMarketExcel"
        params = {'queryType':'2', 'marketCode':'0', 'commodity_id':'TX', 'queryDate':date_slash}
        r = requests.get(url, params=params, headers=HEADERS, verify=False)
        if r.status_code == 200 and len(r.content) > 500:
            df = pd.read_html(io.BytesIO(r.content))[0]
            mask = df.apply(lambda x: x.astype(str).str.contains('盤後').any(), axis=1)
            target = df[~mask]
            
            if not target.empty:
                d = target.iloc[0]
                if '-' not in str(d[2]):
                    open_p = clean_number(d[2])
                    high_p = clean_number(d[3])
                    low_p = clean_number(d[4])
                    close_p = clean_number(d[5])
                    
                    # --- 計算三關價 (給隔天用) ---
                    upper = int(round(low_p + (high_p - low_p) * 1.382))
                    mid = int(round((high_p + low_p) / 2))
                    lower = int(round(high_p - (high_p - low_p) * 1.382))
                    
                    # --- ★新增計算：多空分界線 (當日用) ---
                    # 公式：(開盤 + 最低 + 收盤) / 3，並取整數
                    divider = int(round((open_p + low_p + close_p) / 3))
                    
                    # 儲存結構: [開, 高, 低, 收, 上, 中, 下, 分界]
                    ohlc_data = [open_p, high_p, low_p, close_p, upper, mid, lower, divider]
                    print(f"✅ 行情抓取成功: 收{close_p} 分界{divider}")
    except Exception as e:
        print(f"❌ 行情抓取失敗: {e}")

    if not ohlc_data:
        print("無法取得行情，結束程式。")
        return

    # 2. 抓取籌碼 (成本)
    long_cost, short_cost = 0, 0
    try:
        url = "https://www.taifex.com.tw/cht/3/futContractsDateExcel"
        params = {'queryType':'1', 'doQuery':'1', 'queryDate':date_slash}
        r = requests.get(url, params=params, headers=HEADERS, verify=False)
        if r.status_code == 200:
            dfs = pd.read_html(io.BytesIO(r.content))
            target_df = None
            for df in dfs:
                if "外資" in str(df.values):
                    target_df = df
                    break
            
            if target_df is not None:
                df = target_df.ffill()
                for idx, row in df.iterrows():
                    row_str = " ".join(row.astype(str).values)
                    if "臺股期貨" in row_str and "外資" in row_str:
                        vals = row.values.tolist()
                        try:
                            start_idx = -1
                            for i, v in enumerate(vals):
                                if str(v).strip() == "外資":
                                    start_idx = i
                                    break
                            
                            idx_base = start_idx if start_idx != -1 else 2
                            
                            l_vol = clean_number(vals[idx_base+1])
                            l_amt = clean_number(vals[idx_base+2])
                            s_vol = clean_number(vals[idx_base+3])
                            s_amt = clean_number(vals[idx_base+4])
                            
                            if l_vol > 0: long_cost = int(round((l_amt*1000)/l_vol/200))
                            if s_vol > 0: short_cost = int(round((s_amt*1000)/s_vol/200))
                            print(f"✅ 籌碼抓取成功: 多本{long_cost} 空本{short_cost}")
                        except:
                            pass
                        break
    except Exception as e:
        print(f"❌ 籌碼抓取失敗: {e}")

    # 3. 抓取賣壓 (簡化處理)
    pressure = 0
    try:
        url_twse = f"https://www.twse.com.tw/exchangeReport/MI_5MINS?response=json&date={target_date.strftime('%Y%m%d')}"
        r = requests.get(url_twse, headers=HEADERS, verify=False)
        if r.status_code == 200:
            data = r.json()
            if data.get('stat') == 'OK':
                for row in data['data']:
                    if '09:00:00' in row[0]:
                        pressure = round(float(row[4].replace(',', '')) / 10000, 1)
                        break
    except:
        pass

    # 4. 寫入 Google Sheet
    sheet = get_google_sheet()
    if sheet:
        # 欄位順序: Date, Open, High, Low, Close, Upper, Mid, Lower, ★Divider, Long_Cost, Short_Cost, Pressure
        row = [date_db] + ohlc_data + [long_cost, short_cost, pressure]
        
        try:
            existing = sheet.get_all_values()
            dates = [r[0] for r in existing]
            if date_db in dates:
                print("⚠️ 今日資料已存在，跳過寫入。")
            else:
                sheet.append_row(row)
                print(f"🎉 資料已寫入 (含多空分界): {row}")
        except Exception as e:
            print(f"Google Sheet 寫入錯誤: {e}")

if __name__ == "__main__":
    fetch_data_and_save()