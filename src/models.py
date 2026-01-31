from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

@dataclass(frozen=True)
class Transaction:
    """
    Represents a normalized crypto transaction.
    Generic enough to support multiple exchanges, but initially tailored for Kraken Ldeger data.
    """
    txid: str
    refid: str
    timestamp: datetime
    type: str # e.g., 'deposit', 'withdrawal', 'trade', 'margin'
    subtype: str
    
    # Asset details
    asset_class: str # e.g., 'currency'
    asset: str # e.g., 'XXBT', 'ZUSD'
    
    # Financials
    amount: Decimal # Change in balance (positive or negative)
    fee: Decimal
    balance: Optional[Decimal] # Running balance related to this transaction
    
    # Financials in Fiat (USD)
    fiat_value: Optional[Decimal] = None # Total value of this transaction in USD
    spot_price_usd: Optional[Decimal] = None # Price of asset at time of tx in USD
