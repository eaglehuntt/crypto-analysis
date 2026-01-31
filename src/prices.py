import yfinance as yf
import pandas as pd
from typing import List, Dict
from datetime import datetime

def get_historical_prices(assets: List[str], start_date: datetime) -> pd.DataFrame:
    """
    Fetches daily close prices for a list of assets from yfinance.
    Returns a DataFrame where index is Date and columns are Asset Symbols.
    """
    if not assets:
        return pd.DataFrame()

    # Map internal symbols to YFinance tickers
    # e.g. BTC -> BTC-USD, ETH -> ETH-USD
    # Stablecoins: USD -> skip (price 1), USDT -> USDT-USD
    
    ticker_map = {}
    valid_tickers = []
    
    for asset in set(assets):
        if asset in ['USD', 'ZUSD', 'EUR', 'ZEUR', 'GBP', 'ZGBP']:
            continue # Fiat is 1.0 (relative to itself, or handle exchange rates primarily in USD)
            
        # Basic heuristic for crypto
        # If it's already a clean symbol like BTC, ETH
        yf_ticker = f"{asset}-USD"
        ticker_map[asset] = yf_ticker
        valid_tickers.append(yf_ticker)
        
    if not valid_tickers:
        return pd.DataFrame()
        
    print(f"Fetching prices for: {valid_tickers}")
    
    try:
        # Download data
        # start_date should be the earliest transaction date
        start_str = start_date.strftime('%Y-%m-%d')
        
        # yfinance download
        # period='max' or start=...
        data = yf.download(valid_tickers, start=start_str, progress=False)
        
        if data.empty:
            return pd.DataFrame()
            
        # Extract 'Close' prices
        # result structure covers MultiIndex if multiple tickers
        if len(valid_tickers) > 1:
            closes = data['Close']
        else:
            # If single ticker, it's a Series or DF with 'Close' column
            closes = pd.DataFrame(data['Close'])
            closes.columns = [valid_tickers[0]]
            
        # Rename columns back to internal Asset ID
        # Invert map? {BTC-USD: BTC}
        inv_map = {v: k for k, v in ticker_map.items()}
        closes = closes.rename(columns=inv_map)
        
        # Fill missing values (weekends? Crypto is 24/7 but sometimes data gaps)
        closes = closes.ffill()
        
        return closes
        
    except Exception as e:
        print(f"Error fetching prices: {e}")
        return pd.DataFrame()
