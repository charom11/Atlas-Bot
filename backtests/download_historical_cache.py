#!/usr/bin/env python3
"""Download and cache Binance Futures 15M OHLCV historical datasets."""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import requests
import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent / "historical_data_cache"

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
    "XRPUSDT", "ADAUSDT", "DOGEUSDT", "NEARUSDT", "BNBUSDT", "SUIUSDT",
]


def fetch_and_cache(symbol: str, dataset: str = "1year", cache_dir: Path = CACHE_DIR) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    if dataset == "4year":
        start_str = "2022-09-01"
        cache_file = cache_dir / f"{symbol}_15m_4year_2022-09-01.csv"
    else:
        start_str = "2025-07-01"
        cache_file = cache_dir / f"{symbol}_15m_from_2025-07-01.csv"

    if cache_file.exists() and cache_file.stat().st_size > 1000:
        print(f"[CACHED] {symbol}: {cache_file.name} already exists.")
        return cache_file

    start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    curr_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(time.time() * 1000)

    print(f"[DOWNLOADING] {symbol} 15m from {start_str} to present...", flush=True)
    all_rows = []
    limit = 1500

    while curr_ts < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&startTime={curr_ts}&limit={limit}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if not data:
                    break
                all_rows.extend(data)
                curr_ts = data[-1][0] + (15 * 60 * 1000)
                if len(data) < limit:
                    break
                time.sleep(0.05)
            elif r.status_code == 400 and "startTime" in r.text:
                # Symbol listed after start date (e.g. SUIUSDT listed in May 2023)
                r_earliest = requests.get(f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=15m&limit=1", timeout=10)
                if r_earliest.status_code == 200 and r_earliest.json():
                    curr_ts = r_earliest.json()[0][0]
                else:
                    break
            else:
                print(f"[API ERROR] {symbol}: HTTP {r.status_code}")
                time.sleep(1)
        except Exception as e:
            print(f"[FETCH EXCEPTION] {symbol}: {e}")
            time.sleep(1)

    if not all_rows:
        print(f"[WARN] No data returned for {symbol}")
        return cache_file

    df = pd.DataFrame(all_rows, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "tb_base_vol", "tb_quote_vol", "ignore"
    ])
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
        df[col] = df[col].astype(float)

    df = df.drop_duplicates(subset=["open_time"]).sort_values("open_time").reset_index(drop=True)
    df.to_csv(cache_file, index=False)
    print(f"[CACHED] {symbol}: {len(df):,} bars saved to {cache_file.name}")
    return cache_file


def main():
    parser = argparse.ArgumentParser(description="Download Binance Futures 15M datasets")
    parser.add_argument("--dataset", choices=("1year", "4year", "both"), default="1year")
    parser.add_argument("--symbols", nargs="+", default=SYMBOLS)
    args = parser.parse_args()

    datasets = ["1year", "4year"] if args.dataset == "both" else [args.dataset]
    for ds in datasets:
        print(f"\n=== Downloading {ds} datasets for {len(args.symbols)} symbols ===")
        for sym in args.symbols:
            fetch_and_cache(sym, dataset=ds)


if __name__ == "__main__":
    main()
