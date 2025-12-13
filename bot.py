import pandas as pd
import requests
import datetime
import os
import json
import gspread
import time
from oauth2client.service_account import ServiceAccountCredentials

# --- 設定 ---
SHEET_NAME = "Daily_Stock_Data" # 您的 Google Sheet 名稱
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def get_google_sheet():
    # 讀取 GitHub Actions 環境變數中的金鑰
    json_creds = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if not json_creds:
        print("錯誤：找不到 GCP_SERVICE_ACCOUNT_JSON 環境變數")
        return None
    
    creds_dict = json.loads(json_creds)
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    try:
        sheet = client.open(SHEET_NAME).sheet1
        return sheet
    except Exception as e:
        print(f"無法開啟 Google Sheet: {e}")
        return None

def fetch_and_save():
    print("🚀 開始執行每日爬蟲...")
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    
    # --- 1. 抓取期貨籌碼 (精準版) ---
    long_cost, short_cost = 0, 0
    try:
        url = "https://www.taifex.com.tw/cht/3/futContractsDate"
        dfs = pd.read_html(url)
        df = dfs[0]
        # 篩選 "臺股期貨" 且 "外資"
        target = df[df.iloc[:, 1].astype(str).str.contains("臺股期貨", na=False) & 
                    df.iloc[:, 2].astype(str).str.contains("外資", na=False)]
        
        if not target.empty:
            # 資料清洗：去除逗號並轉浮點數
            def clean_num(x):
                return float(str(x).replace(',', ''))

            long_vol = clean_num(target.iloc[0, 3])  # 多方口數
            long_amt = clean_num(target.iloc[0, 4])  # 多方金額
            short_vol = clean_num(target.iloc[0, 5]) # 空方口數
            short_amt = clean_num(target.iloc[0, 6]) # 空方金額
            
            # 計算成本 (單位: 千元 -> *1000, 點值: 200)
            long_cost = (long_amt * 1000) / long_vol * 1000 / 200 if long_vol > 0 else 0
            # ★ 修正公式：空方金額 / 空方口數
            short_cost = (short_amt * 1000) / short_vol * 1000 / 200 if short_vol > 0 else 0
            
            print(f"籌碼數據: 多本{long_cost:.2f}, 空本{short_cost:.2f}")
        else:
            print("⚠️ 查無外資期貨資料 (可能無數據)")
    except Exception as e:
        print(f"❌ 籌碼抓取失敗: {e}")
        return # 籌碼失敗通常代表沒開盤，直接結束

    # --- 2. 抓取期貨行情 (OHLC) ---
    ohlc = None
    try:
        url = "https://www.taifex.com.tw/cht/3/futDailyMarketReport"
        dfs = pd.read_html(url)
        df = dfs[0]
        # 篩選 "臺股期貨" 且 "一般" (非盤後)
        target = df[df.iloc[:, 0].astype(str).str.contains("臺股期貨", na=False) & 
                    ~df.iloc[:, 0].astype(str).str.contains("盤後", na=False)]
        
        if not target.empty:
            d = target.iloc[0]
            # 欄位：開盤(2), 最高(3), 最低(4), 收盤(5)
            open_p = float(d[2])
            high_p = float(d[3])
            low_p = float(d[4])
            close_p = float(d[5])
            
            # 計算三關價
            mid_pass = (high_p + low_p) / 2
            upper_pass = low_p + (high_p - low_p) * 1.382
            lower_pass = high_p - (high_p - low_p) * 1.382
            
            ohlc = [open_p, high_p, low_p, close_p, upper_pass, mid_pass, lower_pass]
            print(f"行情數據: 收盤{close_p}")
        else:
            print("⚠️ 查無期貨行情")
            return
    except Exception as e:
        print(f"❌ 行情抓取失敗: {e}")
        return

    # --- 3. 抓取證交所賣壓 (9:00 第一筆) ---
    pressure = 0
    try:
        url = "https://www.twse.com.tw/exchangeReport/MI_5MINS?response=json"
        # 增加 retry 機制，因為證交所 API 偶爾會擋
        for _ in range(3):
            r = requests.get(url, headers=HEADERS)
            if r.status_code == 200:
                break
            time.sleep(2)
            
        data = r.json()
        if data['stat'] == 'OK':
            first_row = data['data'][0]
            # 確認時間是否包含 09:00
            if "09:00" in first_row[0]:
                # 欄位 4 是累積委賣 (依據 JSON 結構)
                sell_orders = float(first_row[4].replace(',', ''))
                pressure = sell_orders / 10000
                print(f"賣壓數據: {pressure:.2f}")
    except Exception as e:
        print(f"⚠️ 賣壓抓取失敗 (可能是假日或無資料): {e}")
        # 賣壓失敗不影響主流程，設為 0

    # --- 4. 寫入 Google Sheet ---
    sheet = get_google_sheet()
    if sheet:
        # 組合資料列
        # [日期, 開, 高, 低, 收, 多本, 空本, 上關, 中關, 下關, 賣壓]
        new_row = [today_str] + ohlc + [long_cost, short_cost, pressure]
        
        # 檢查是否已存在 (避免重複寫入)
        try:
            existing_data = sheet.get_all_values()
            # 檢查第一欄 (日期)
            dates = [row[0] for row in existing_data]
            
            if today_str in dates:
                print("✅ 今日資料已存在，跳過寫入。")
            else:
                sheet.append_row(new_row)
                print(f"✅ 成功寫入資料：{new_row}")
                
                # 保留最新 60 筆 (可選)
                if len(existing_data) > 65: # 標題+60筆緩衝
                    # 這裡比較複雜，暫時只做寫入，Google Sheet 容量很大不用擔心
                    pass
        except Exception as e:
            print(f"寫入 Google Sheet 發生錯誤: {e}")

if __name__ == "__main__":
    fetch_and_save()