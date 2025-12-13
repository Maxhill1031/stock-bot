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

# --- 設定區 ---
SHEET_NAME = "Daily_Stock_Data"  # 您的 Google Sheet 名稱
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 關閉 SSL 警告 (因為期交所憑證問題)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_google_sheet():
    # 讀取 GitHub Actions 環境變數中的金鑰
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

def fetch_data_by_date(target_date):
    """
    使用 get_history_to_excel.py 的嚴謹邏輯抓取單日資料
    """
    date_slash = target_date.strftime("%Y/%m/%d")  
    date_no_slash = target_date.strftime("%Y%m%d") 
    date_db = target_date.strftime("%Y-%m-%d")     
    
    print(f"[{date_db}] 正在抓取...", end=" ")

    # =========================================================================
    # 1. 期貨行情 (Excel 通道)
    # =========================================================================
    ohlc = None
    try:
        url_ohlc = "https://www.taifex.com.tw/cht/3/futDailyMarketExcel" 
        params_ohlc = {
            'queryType': '2', 'marketCode': '0', 'commodity_id': 'TX', 
            'queryDate': date_slash, 'dateaddcnt': '', 'commodity_id2': ''
        }
        # 使用 verify=False 避開憑證錯誤
        r = requests.get(url_ohlc, params=params_ohlc, headers=HEADERS, verify=False)
        
        if r.status_code == 200 and len(r.content) > 500:
            dfs = pd.read_html(io.BytesIO(r.content))
            df = dfs[0]
            
            mask = df.apply(lambda x: x.astype(str).str.contains('盤後').any(), axis=1)
            target = df[~mask]
            
            if not target.empty:
                d = target.iloc[0] 
                if '-' in str(d[2]) or '-' in str(d[5]):
                    print("休市/無數據", end=" | ")
                    return None
                
                open_p = clean_number(d[2])
                high_p = clean_number(d[3])
                low_p = clean_number(d[4])
                close_p = clean_number(d[5])
                
                # --- 計算三關價 (並強制取整數) ---
                mid_pass = (high_p + low_p) / 2
                upper_pass = low_p + (high_p - low_p) * 1.382
                lower_pass = high_p - (high_p - low_p) * 1.382
                
                # ★ 這裡加上 int(round(...)) 符合您的要求
                mid_pass = int(round(mid_pass))
                upper_pass = int(round(upper_pass))
                lower_pass = int(round(lower_pass))
                
                # 順序: 開, 高, 低, 收, 上, 中, 下
                ohlc = [open_p, high_p, low_p, close_p, upper_pass, mid_pass, lower_pass]
                print("✅ 行情OK", end=" ")
            else:
                print("查無TX資料", end=" | ")
                return None
        else:
             print("請求被擋或內容過短", end=" | ")
             return None
    except Exception as e:
        print(f"行情錯誤: {e}", end=" | ")
        return None

    if not ohlc: return None 

    # =========================================================================
    # 2. 期貨籌碼 (ffill + 鎖定欄位 + 取整數)
    # =========================================================================
    long_cost, short_cost = 0, 0
    try:
        url_chip = "https://www.taifex.com.tw/cht/3/futContractsDateExcel"
        params_chip = {
            'queryType': '1', 'goDay': '', 'doQuery': '1', 
            'queryDate': date_slash, 'commodityId': ''
        }
        r = requests.get(url_chip, params=params_chip, headers=HEADERS, verify=False)
        
        if r.status_code == 200:
            dfs = pd.read_html(io.BytesIO(r.content))
            
            target_df = None
            for df in dfs:
                if "外資" in str(df.values):
                    target_df = df
                    break
            
            if target_df is not None:
                # 舊版 pandas 用 fillna(method='ffill')
                # 新版 pandas 建議用 ffill()，這裡保持兼容性
                try:
                    df = target_df.ffill()
                except:
                    df = target_df.fillna(method='ffill')

                target_row = None
                for idx, row in df.iterrows():
                    row_str = " ".join(row.astype(str).values)
                    if "臺股期貨" in row_str and "外資" in row_str:
                        target_row = row
                        break
                
                if target_row is not None:
                    try:
                        vals = target_row.values.tolist()
                        start_idx = -1
                        for i, v in enumerate(vals):
                            if str(v).strip() == "外資":
                                start_idx = i
                                break
                        
                        if start_idx != -1 and (start_idx+4) < len(vals):
                            idx_base = start_idx
                        else:
                            idx_base = 2 

                        long_vol = clean_number(vals[idx_base + 1]) 
                        long_amt = clean_number(vals[idx_base + 2]) 
                        short_vol = clean_number(vals[idx_base + 3]) 
                        short_amt = clean_number(vals[idx_base + 4]) 

                        # ★ 成本計算 & 取整數
                        if long_vol > 0: 
                            raw_val = (long_amt * 1000) / long_vol / 200
                            long_cost = int(round(raw_val)) 
                        
                        if short_vol > 0: 
                            raw_val = (short_amt * 1000) / short_vol / 200
                            short_cost = int(round(raw_val))
                            
                        print(f"(成本: 多{long_cost}/空{short_cost})", end=" ")
                    except:
                        pass
    except Exception as e:
        print(f"籌碼錯誤: {e}", end=" ")

    # =========================================================================
    # 3. 賣壓 (JSON + verify=False + 取小數點第一位)
    # =========================================================================
    pressure = 0
    try:
        url_twse = f"https://www.twse.com.tw/exchangeReport/MI_5MINS?response=json&date={date_no_slash}"
        r = requests.get(url_twse, headers=HEADERS, verify=False)
        
        if r.status_code == 200:
            data = r.json()
            if data.get('stat') == 'OK':
                found_time = False
                for row in data['data']:
                    if '09:00:00' in row[0]:
                        val_str = row[4].replace(',', '')
                        # ★ 取小數點第一位
                        pressure = round(float(val_str) / 10000, 1)
                        found_time = True
                        break
                
                if found_time:
                    print(f"(賣壓: {pressure})", end=" ")
                else:
                    print("(無09:00數據)", end=" ")
    except Exception as e:
        print(f"賣壓錯誤: {e}", end=" ")

    print("") # 換行
    
    # 返回整合好的資料字典
    return {
        "Date": date_db, 
        "ohlc_list": ohlc, # [開, 高, 低, 收, 上, 中, 下]
        "long_cost": long_cost,
        "short_cost": short_cost,
        "pressure": pressure
    }

def fetch_and_save():
    print("🚀 Bot 開始執行...")
    
    # 判斷要抓取的日期：預設為今天
    # 如果您通常在盤後（下午/晚上）執行，這裡用 today 是對的
    target_date = datetime.date.today()
    
    # 週末防呆
    if target_date.weekday() >= 5:
        print("今天是週末，不執行抓取。")
        return

    # 執行抓取
    data = fetch_data_by_date(target_date)
    
    if data:
        # --- 寫入 Google Sheet ---
        sheet = get_google_sheet()
        if sheet:
            # 組合資料列，對應您原本的欄位順序：
            # [日期, 開, 高, 低, 收, 上關, 中關, 下關, 多本, 空本, 賣壓] 
            # (請確認您 Sheet 的欄位順序，這裡我依照原本 bot.py 的邏輯調整)
            
            # 原本 bot.py 順序是: [日期] + ohlc(含三關) + [多本, 空本, 賣壓]
            # 其中 ohlc = [Open, High, Low, Close, Upper, Mid, Lower]
            
            row_to_write = [data["Date"]] + data["ohlc_list"] + [data["long_cost"], data["short_cost"], data["pressure"]]
            
            # 檢查是否已存在
            try:
                existing_data = sheet.get_all_values()
                dates = [row[0] for row in existing_data]
                
                if data["Date"] in dates:
                    print(f"✅ {data['Date']} 資料已存在 Google Sheet，跳過寫入。")
                else:
                    sheet.append_row(row_to_write)
                    print(f"✅ 成功寫入 Google Sheet：{row_to_write}")
            except Exception as e:
                print(f"寫入 Google Sheet 發生錯誤: {e}")
    else:
        print("❌ 今日無法取得完整資料 (可能是假日或資料尚未更新)。")

if __name__ == "__main__":
    fetch_and_save()