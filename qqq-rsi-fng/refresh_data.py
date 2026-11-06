#!/usr/bin/env python3
"""Refresh the embedded QQQ and CNN Fear & Greed history in index.html."""

from __future__ import annotations

import json
import math
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / "index.html"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)
START_DATE = date(2023, 10, 13)
MAX_ATTEMPTS = 3

# 訊號門檻：與 index.html 中的 JS 常數保持一致，修改時兩邊須同步。
RSI_PERIOD = 6
RSI_THRESHOLD = 22       # 條件① RSI(6) < 22：短線超賣
FNG_THRESHOLD = 20       # 條件② CNN 指數 < 20：觸發
VIX_THRESHOLD = 25       # 條件③ VIX > 25：進入高波動
VIX_DAILY_CHANGE_THRESHOLD = 30  # 條件④ VIX 單日漲幅 > 30%：急升觸發


class RefreshError(Exception):
    """Raised when an external data source or local file cannot be refreshed."""


def fetch_json(url: str, *, referer: str | None = None) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if referer:
        headers.update(
            {"Referer": referer, "Origin": "https://www.cnn.com"}
        )

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            retryable = error.code in {429, 500, 502, 503, 504}
            if not retryable or attempt == MAX_ATTEMPTS:
                raise RefreshError(
                    f"API 回應 HTTP {error.code}: {url}"
                ) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            if attempt == MAX_ATTEMPTS:
                raise RefreshError(f"無法取得或解析 API 資料：{error}") from error

        time.sleep(attempt * 2)

    raise RefreshError("API 重試次數已用盡。")


def get_daily_closes(ticker: str, start_date: date) -> dict[str, float]:
    period1 = int(
        datetime.combine(start_date, datetime.min.time(), timezone.utc).timestamp()
    )
    period2 = int(datetime.now(timezone.utc).timestamp()) + 86400
    query = urlencode(
        {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "div,splits",
        }
    )
    payload = fetch_json(f"{YAHOO_URL}/{quote(ticker, safe='')}?{query}")
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RefreshError(f"Yahoo Finance {ticker} 錯誤：{chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise RefreshError(f"Yahoo Finance 沒有回傳 {ticker} 日線資料。")

    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = result.get("indicators", {}).get("quote") or []
    closes = quotes[0].get("close") if quotes else None
    if closes is None or len(timestamps) != len(closes):
        raise RefreshError(
            f"Yahoo Finance {ticker} 回傳的日期與收盤價資料不完整。"
        )

    rows = {}
    for timestamp, close in zip(timestamps, closes):
        if close is None or not math.isfinite(close):
            continue
        trading_date = datetime.fromtimestamp(
            timestamp, timezone.utc
        ).date().isoformat()
        if trading_date >= start_date.isoformat():
            rows[trading_date] = float(close)

    if len(rows) < 100:
        raise RefreshError(
            f"Yahoo Finance {ticker} 僅回傳 {len(rows)} 筆資料，"
            "少於預期；頁面未更新。"
        )
    return rows


def get_cnn_scores(start_date: date) -> dict[str, float]:
    payload = fetch_json(
        f"{CNN_URL}/{start_date.isoformat()}",
        referer="https://www.cnn.com/markets/fear-and-greed",
    )
    history = payload.get("fear_and_greed_historical", {})
    points = history.get("data") or []
    rows = {}
    for point in points:
        timestamp = point.get("x")
        score = point.get("y")
        if timestamp is None or score is None:
            continue
        if not math.isfinite(timestamp) or not math.isfinite(score):
            continue
        score_date = datetime.fromtimestamp(
            timestamp / 1000, timezone.utc
        ).date().isoformat()
        if score_date >= start_date.isoformat() and 0 <= score <= 100:
            rows[score_date] = float(score)

    if len(rows) < 100:
        raise RefreshError(
            f"CNN 僅回傳 {len(rows)} 筆有效資料，少於預期；頁面未更新。"
        )
    return rows


def calculate_rsi(prices: list[float], period: int = RSI_PERIOD) -> list[float | None]:
    values: list[float | None] = [None] * len(prices)
    if len(prices) <= period:
        return values

    gains = 0.0
    losses = 0.0
    for index in range(1, period + 1):
        change = prices[index] - prices[index - 1]
        gains += max(change, 0)
        losses += max(-change, 0)

    average_gain = gains / period
    average_loss = losses / period

    def rsi_value(gain: float, loss: float) -> float:
        if loss == 0:
            return 50.0 if gain == 0 else 100.0
        return 100 - 100 / (1 + gain / loss)

    values[period] = rsi_value(average_gain, average_loss)
    for index in range(period + 1, len(prices)):
        change = prices[index] - prices[index - 1]
        average_gain = (
            average_gain * (period - 1) + max(change, 0)
        ) / period
        average_loss = (
            average_loss * (period - 1) + max(-change, 0)
        ) / period
        values[index] = rsi_value(average_gain, average_loss)
    return values


def make_dataset() -> dict:
    qqq = get_daily_closes("QQQ", START_DATE)
    vix = get_daily_closes("^VIX", START_DATE)
    cnn = get_cnn_scores(START_DATE)
    common_dates = set(qqq) & set(cnn) & set(vix)
    if len(common_dates) < 100:
        raise RefreshError(
            f"QQQ、CNN 與 VIX 只有 {len(common_dates)} 個共同日期；頁面未更新。"
        )
    latest_common_date = max(common_dates)
    dates = [day for day in sorted(qqq) if day <= latest_common_date]
    if not dates:
        raise RefreshError("沒有可用的 QQQ 交易日資料。")

    closes = [qqq[day] for day in dates]
    rsi = calculate_rsi(closes)
    aligned_fng = [cnn.get(day) for day in dates]
    aligned_vix = [vix.get(day) for day in dates]
    if aligned_fng[-1] is None or aligned_vix[-1] is None:
        print(
            f"注意：最新共同交易日為 {dates[-1]}；"
            "部分資料來源的最新交易日不同。",
            file=sys.stderr,
        )

    return {
        "dates": dates,
        "close": closes,
        "rsi6": rsi,
        "fng": aligned_fng,
        "vix": aligned_vix,
    }


def evaluate_latest_signal(data: dict) -> str:
    """依 index.html 相同的四條件規則評估最新交易日訊號分級。"""
    rsi = data["rsi6"]
    fng = data["fng"]
    vix = data["vix"]
    index = len(data["dates"]) - 1

    previous_vix = vix[index - 1] if index >= 1 else None
    vix_daily_change = None
    if vix[index] is not None and previous_vix not in (None, 0):
        vix_daily_change = (vix[index] / previous_vix - 1) * 100

    flags = {
        "RSI 超賣": rsi[index] is not None and rsi[index] < RSI_THRESHOLD,
        "CNN 恐懼": fng[index] is not None and fng[index] < FNG_THRESHOLD,
        "VIX 高波動": vix[index] is not None and vix[index] > VIX_THRESHOLD,
        "VIX 急升": (
            vix_daily_change is not None
            and vix_daily_change > VIX_DAILY_CHANGE_THRESHOLD
        ),
    }
    triggered = [name for name, hit in flags.items() if hit]
    count = len(triggered)
    tier = {
        4: "ALL IN 訊號",
        3: "三條件高亮訊號",
        2: "雙條件訊號",
        1: "單個指標觸發",
        0: "未觸發",
    }[count]
    detail = f"（{ '、'.join(triggered) }）" if triggered else ""
    return f"{tier}{detail}［{count}/4 條件］"


def update_html(data: dict) -> None:
    try:
        html = HTML_PATH.read_text(encoding="utf-8")
    except OSError as error:
        raise RefreshError(f"無法讀取 {HTML_PATH.name}：{error}") from error

    pattern = re.compile(
        r"const DATA = \{.*?\};(?=\s*const RSI_PERIOD)", re.DOTALL
    )
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    replacement = f"const DATA = {serialized};"
    updated_html, replacements = pattern.subn(
        lambda _: replacement, html, count=1
    )
    if replacements != 1:
        raise RefreshError(
            "找不到預期的資料區塊，HTML 未變更。"
            "請確認 index.html 未移除 const DATA 區塊。"
        )

    temporary_path = HTML_PATH.with_suffix(".html.tmp")
    try:
        temporary_path.write_text(updated_html, encoding="utf-8", newline="\n")
        temporary_path.replace(HTML_PATH)
    except OSError as error:
        temporary_path.unlink(missing_ok=True)
        raise RefreshError(f"無法寫入更新後的 HTML：{error}") from error


def main() -> int:
    print("正在從 Yahoo Finance 和 CNN 擷取最新歷史資料…")
    data = make_dataset()
    update_html(data)
    latest = len(data["dates"]) - 1
    print(
        f"更新完成：共同資料日期 {data['dates'][0]} 至 {data['dates'][latest]}，"
        f"共 {len(data['dates'])} 個 QQQ 交易日。"
    )
    print(
        f"最新 QQQ 收盤（{data['dates'][latest]}）："
        f"${data['close'][latest]:.2f}"
    )
    print(
        f"最新 RSI(6)（{data['dates'][latest]}）："
        f"{data['rsi6'][latest]:.2f}"
        if data["rsi6"][latest] is not None
        else f"最新 RSI(6)（{data['dates'][latest]}）：資料不足"
    )
    print(
        f"最新 CNN 指數（{data['dates'][latest]}）："
        f"{data['fng'][latest]:.2f}"
        if data["fng"][latest] is not None
        else f"最新 CNN 指數（{data['dates'][latest]}）：CNN 尚未發布此日資料"
    )
    print(
        f"最新 VIX（{data['dates'][latest]}）：{data['vix'][latest]:.2f}"
        if data["vix"][latest] is not None
        else f"最新 VIX（{data['dates'][latest]}）：資料尚未發布"
    )
    print(f"最新訊號（{data['dates'][latest]}）：{evaluate_latest_signal(data)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RefreshError as error:
        print(f"更新失敗：{error}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\n已取消更新；頁面維持未修改狀態。", file=sys.stderr)
        raise SystemExit(130)
