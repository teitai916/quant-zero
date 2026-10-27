# QQQ RSI × CNN 恐懼貪婪指數

## 每次更新

在檔案總管雙擊 `refresh.cmd`。程式會從 Yahoo Finance 和 CNN 擷取資料、更新 `index.html`，並在瀏覽器開啟更新後的頁面。

也可以在命令提示字元執行：

```cmd
cd /d E:\codespaces\quant-zero\qqq-rsi-fng
py -3 refresh_data.py
```

更新後若頁面已經開啟，請在瀏覽器重新整理，讀取更新後的歷史資料。

## 需求與資料來源

- Windows 與 Python 3.10 以上版本（使用內建標準函式庫，不需 `pip install`）。
- QQQ 日線收盤價：Yahoo Finance Chart API，讀取 `chart.result[].timestamp` 和 `indicators.quote[].close`。
- CNN 恐懼貪婪歷史分數：CNN Fear & Greed Graph Data API，讀取 `fear_and_greed_historical.data[].x/y`。
- 資料從 `refresh_data.py` 中的 `START_DATE` 起算，目前設定為 `2023-10-13`。

程式使用的公開資料端點：

- `https://query1.finance.yahoo.com/v8/finance/chart/QQQ`
- `https://production.dataviz.cnn.io/index/fearandgreed/graphdata/2023-10-13`

API 是公開網站使用的資料端點，沒有官方服務保證；若端點、連線或回應格式改變，程式會顯示錯誤並保留原本頁面，不會把失敗結果寫入檔案。

## 指標規則

- RSI 使用 QQQ 日收盤價計算，Wilder 平滑週期為 6。
- RSI 嚴格小於 22 時標記 RSI 超賣。
- CNN 指數嚴格小於 10 時標記極度恐懼。
- 兩項條件須在同一交易日均有資料且同時成立，才標記雙條件訊號。

這些歷史條件是觀察指標，不構成投資建議，也不保證未來表現。
