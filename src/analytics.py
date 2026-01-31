import pandas as pd
import numpy as np
from typing import Dict, List
from .prices import get_historical_prices
import streamlit as st

def calculate_portfolio_performance(history_df: pd.DataFrame) -> pd.DataFrame:
    """
    Combines manual transaction history with external price feeds to create
    an accurate 'Market Value' chart over time.
    Calculates metrics for BOTH the efficient Total Portfolio and Individual Assets.
    """
    if history_df.empty:
        return pd.DataFrame()
    
    history_df['timestamp'] = pd.to_datetime(history_df['timestamp'])
    df = history_df.set_index('timestamp').sort_index()
    
    # --- 1. Expand Asset Details ---
    # asset_details is a list of dicts: [{'BTC': {'qty': 1, 'cost_basis': 100}}, ...]
    details_list = df['asset_details'].tolist()
    
    # We want to create time-series for Qty and CostBasis per asset
    # normalize structure:
    # We will create a list of flattened dicts per row: {'BTC_qty': 1, 'BTC_cb': 100, ...}
    flattened_rows = []
    
    for item in details_list:
        row = {}
        for asset, data in item.items():
            row[f"{asset}_qty"] = data['qty']
            row[f"{asset}_cb"] = data['cost_basis']
        flattened_rows.append(row)
        
    details_df = pd.DataFrame(flattened_rows, index=df.index)
    details_df = details_df.astype(float)
    
    # Resample everything to Daily
    # Combine with Totals
    daily_totals = df[['total_realized_gain', 'total_cost_basis', 'total_market_value']].resample('D').last().ffill()
    
    # Resample details (forward fill holding state)
    daily_details = details_df.resample('D').last().ffill().fillna(0)
    
    # Merge
    daily_df = pd.concat([daily_totals, daily_details], axis=1)
    
    # --- 2. Get External Prices ---
    # Extract asset names from columns (ending in _qty)
    assets = [c.replace('_qty', '') for c in daily_details.columns if c.endswith('_qty')]
    
    if daily_df.index.tz is not None:
        daily_df.index = daily_df.index.tz_localize(None)

    # Fetch Prices
    start_date = daily_df.index.min()
    price_df = pd.DataFrame()
    
    if assets:
        try:
             price_df = get_historical_prices(assets, start_date)
        except Exception as e:
             st.warning(f"Price fetch warning: {e}")
             
    if not price_df.empty:
        if price_df.index.tz is not None:
             price_df.index = price_df.index.tz_localize(None)
        
        # Align
        combined_index = daily_df.index.union(price_df.index)
        daily_df = daily_df.reindex(combined_index).ffill().fillna(0)
        price_df = price_df.reindex(combined_index).ffill()
    else:
        combined_index = daily_df.index
    
    # --- 3. Calculate Market Values ---
    total_calculated_value = pd.Series(0.0, index=combined_index)
    has_external_data = False
    
    for asset in assets:
        qty_col = f"{asset}_qty"
        cb_col = f"{asset}_cb"
        mv_col = f"{asset}_mv"
        
        # Default MV to 0
        mv_series = pd.Series(0.0, index=combined_index)
        
        if not price_df.empty and asset in price_df.columns:
            # Calc Market Value = Qty * External Price
            mv_series = daily_df[qty_col] * price_df[asset]
            has_external_data = True
        else:
            # Fallback? We don't have per-asset engine MV estimate easily available for history 
            # (unless we calculated it in engine).
            # We can't do much. MV is 0.
            pass
            
        daily_df[mv_col] = mv_series.fillna(0)
        total_calculated_value = total_calculated_value + daily_df[mv_col]

    # --- 4. Final Totals Logic ---
    # If we have valid external data, overwrite the Engine's total estimates
    if has_external_data and total_calculated_value.sum() > 0:
        daily_df['total_market_value'] = total_calculated_value
    else:
        # Keep Engine's 'total_market_value' which was resampled
        pass

    return daily_df.astype(float)
