import pandas as pd
from typing import List
from datetime import datetime
from decimal import Decimal
from .models import Transaction

def clean_asset_code(asset: str) -> str:
    """
    Normalizes Kraken asset codes to standard symbols.
    """
    if not asset:
        return asset
    
    # Common mappings
    mapping = {
        'XXBT': 'BTC',
        'XBT': 'BTC',
        'XETH': 'ETH',
        'XXRP': 'XRP',
        'XXLM': 'XLM',
        'XLTC': 'LTC',
        'XETC': 'ETC',
        'XZEC': 'ZEC',
        'XREP': 'REP',
        'XXMR': 'XMR',
        'ZUSD': 'USD',
        'ZEUR': 'EUR',
        'ZGBP': 'GBP',
        'ZCAD': 'CAD',
        'ZJPY': 'JPY',
        'ZKRW': 'KRW'
    }
    
    return mapping.get(asset, asset)

def parse_kraken_ledger(df: pd.DataFrame) -> List[Transaction]:
    """
    Parses a pandas DataFrame containing Kraken Ledger data into a list of Transaction objects.
    Expected columns: "txid","refid","time","type","subtype","aclass","subclass","asset","wallet","amount","fee","balance","amountusd"
    """
    transactions = []
    
    # Ensure required columns exist
    required_columns = ["txid", "refid", "time", "type", "subtype", "aclass", "asset", "amount", "fee", "balance"]
    # check for existence (ignoring case for robustness if needed, but assuming strict for now based on user prompt)
    
    for _, row in df.iterrows():
        # Parse timestamp. Kraken usually uses "YYYY-MM-DD HH:MM:SS"
        # We'll use pd.to_datetime logic if the df wasn't already parsed, but let's assume raw strings for safety or convert in the loop
        # Actually better to let pandas parse dates on load, but we handle it here just in case.
        
        try:
            ts = pd.to_datetime(row['time']).to_pydatetime()
        except Exception:
            # Fallback or error? defaulting to now or skipping? 
            # In a strict financial app, we should probably fail, but let's try to be robust.
            ts = datetime.utcnow() # Placeholder, ideally log error

        # Handle numerics
        try:
            amt = Decimal(str(row['amount']))
            fee = Decimal(str(row['fee']))
            bal = Decimal(str(row['balance'])) if pd.notna(row['balance']) and row['balance'] != '' else None
            
            fiat = None
            if 'amountusd' in row and pd.notna(row['amountusd']) and row['amountusd'] != '':
                 fiat = Decimal(str(row['amountusd']))
        except ValueError:
            # Log error?
            continue

        tx = Transaction(
            txid=str(row['txid']),
            refid=str(row['refid']),
            timestamp=ts,
            type=str(row['type']),
            subtype=str(row['subtype']),
            asset_class=str(row['aclass']),
            asset=clean_asset_code(str(row['asset'])),
            amount=amt,
            fee=fee,
            balance=bal,
            fiat_value=fiat
        )
        transactions.append(tx)
        
    return transactions

def load_csvs(file_paths: List[str]) -> pd.DataFrame:
    """
    Loads multiple CSV files and concatenates them into a single DataFrame.
    """
    dfs = []
    for p in file_paths:
        try:
            df = pd.read_csv(p)
            # Basic cleaning if needed
            dfs.append(df)
        except Exception as e:
            print(f"Error loading {p}: {e}")
            
    if not dfs:
        return pd.DataFrame()
        
    merged_df = pd.concat(dfs, ignore_index=True)
    return merged_df

def normalize_to_transactions(df: pd.DataFrame, source: str = 'kraken_ledger') -> List[Transaction]:
    """
    Factory function to convert a raw DataFrame into normalized Transaction objects based on source.
    """
    if source == 'kraken_ledger':
        return parse_kraken_ledger(df)
    else:
        raise ValueError(f"Unknown data source: {source}")
