import pandas as pd
from typing import List, Dict, Deque
from collections import deque
from decimal import Decimal
from .models import Transaction

class FIFOEngine:
    def __init__(self, transactions: List[Transaction], withdrawals_as_transfers: bool = True, deposits_as_transfers: bool = False):
        self.transactions = sorted(transactions, key=lambda x: x.timestamp)
        self.withdrawals_as_transfers = withdrawals_as_transfers
        self.deposits_as_transfers = deposits_as_transfers
        self.inventory: Dict[str, Deque] = {} # Asset -> Deque of (quantity, cost_per_unit_usd)
        self.last_known_prices: Dict[str, Decimal] = {} # Asset -> Price
        self.realized_gains: List[Dict] = []
        self.portfolio_history: List[Dict] = [] # Snapshots over time

    def run(self):
        """
        Process all transactions and return dataframes for analysis.
        """
        current_balances: Dict[str, Decimal] = {}
        # Reset internal state if running multiple times? 
        # Actually init resets state. run() should probably be called once.
        self.last_known_prices = {}
        cumulative_realized_gain = Decimal(0)
        
        for tx in self.transactions:
            asset = tx.asset
            amount = tx.amount
            
            # Skip fiat currency itself (e.g. ZUSD, USD) if we consider it the baseline
            # Assuming 'ZUSD', 'USD' are fiat. 
            # In a real app we'd need more robust config.
            is_fiat = asset in ['ZUSD', 'USD', 'ZEUR', 'EUR']
            
            # If fiat, we just update balance, no cost basis logic needed (tracking CASH basis is separate)
            if is_fiat:
                current_balances[asset] = current_balances.get(asset, Decimal(0)) + amount
            else:
                # Crypto Asset
                if amount > 0:
                    # BUY / DEPOSIT / RECEIVE
                    # Cost Basis: inferred from fiat_value or external price.
                    # If fiat_value is present, cost_basis = fiat_value
                    cost_basis_total = tx.fiat_value if tx.fiat_value is not None else Decimal(0)
                    cost_per_unit = cost_basis_total / amount if amount != 0 else Decimal(0)
                    
                    # Double Counting Prevention:
                    # If this is a Deposit (not a Buy) and deposits_as_transfers is True,
                    # We assume this is a "Return" of assets we already hold (from a withdrawal).
                    # So we SKIP adding it.
                    is_deposit_transfer = False
                    if self.deposits_as_transfers and tx.type.lower() in ['deposit', 'transfer', 'receive']:
                         is_deposit_transfer = True
                    
                    if not is_deposit_transfer:
                        if asset not in self.inventory:
                            self.inventory[asset] = deque()
                        
                        self.inventory[asset].append({
                            'qty': amount,
                            'unit_cost': cost_per_unit,
                            'date': tx.timestamp
                        })
                        
                        current_balances[asset] = current_balances.get(asset, Decimal(0)) + amount
                    else:
                        # It is a return. We assume we already have the inventory.
                        pass
                    
                    # Update implicit price
                    if amount != 0:
                         self.last_known_prices[asset] = abs(cost_basis_total / amount)
                    
                elif amount < 0:
                    # SELL / WITHDRAWAL / SEND
                    qty_to_sell = abs(amount)
                    proceeds_total = tx.fiat_value if tx.fiat_value is not None else Decimal(0)
                    # Note: If fiat_value is usually positive in CSV for value? Or negative?
                    # Assuming fiat_value is the positive USD equivalent.
                    # If parsed as negative (because amount is negative), take abs.
                    proceeds_total = abs(proceeds_total)
                    
                    # Update implicit price
                    if qty_to_sell != 0:
                        self.last_known_prices[asset] = proceeds_total / qty_to_sell
                    
                    # Determine nature of transaction
                    is_transfer = False
                    if self.withdrawals_as_transfers:
                        # Only consider it a transfer if it is explicitly a movement type
                        # AND NOT a trade/margin/spend (unless spend is send? Spend is usually card)
                        type_lower = tx.type.lower()
                        if type_lower in ['withdrawal', 'transfer', 'send', 'deposit']: 
                            # Deposit is usually positive, but if negative? 
                            is_transfer = True
                        
                        # Explicitly ensure trades/spends are NOT transfers
                        # Some conversions might show up as 'trade' with negative amount
                        # 'spend' is a taxable event (goods/services), not a self-transfer
                        if type_lower in ['trade', 'margin', 'settled', 'spend']:
                            is_transfer = False
                    
                    # If it's a transfer (self-transfer to cold wallet), we do NOT sell.
                    # We keep the assets in inventory (Portfolio View).
                    if is_transfer:
                        # Update implicit price if we can derive it?
                        # Often transfers have fee but no value. 
                        # If meaningful logic needed here, insert it.
                        # For now, we simple SKIP the "sell" logic.
                        # We still update current_balances (fiat/raw tracking) if we want?
                        # Actually current_balances is just for fiat in this code.
                        pass 
                    else:
                        # It is a SALE. Consume inventory.
                        total_cost_basis = Decimal(0)
                        if asset in self.inventory:
                            queue = self.inventory[asset]
                            
                            while qty_to_sell > 0 and queue:
                                lot = queue[0]
                                lot_qty = lot['qty']
                                lot_price = lot['unit_cost']
                                
                                if lot_qty <= qty_to_sell:
                                    # Consume entire lot
                                    total_cost_basis += lot_qty * lot_price
                                    qty_to_sell -= lot_qty
                                    queue.popleft()
                                else:
                                    # Partial lot consumption
                                    total_cost_basis += qty_to_sell * lot_price
                                    lot['qty'] -= qty_to_sell
                                    qty_to_sell = Decimal(0)
                        
                        gain = proceeds_total - total_cost_basis
                        cumulative_realized_gain += gain
                        
                        self.realized_gains.append({
                            'date': tx.timestamp,
                            'asset': asset,
                            'quantity': abs(amount),
                            'proceeds': proceeds_total,
                            'cost_basis': total_cost_basis,
                            'gain_usd': gain,
                            'tx_type': tx.type
                        })
                    
                    self.realized_gains.append({
                        'date': tx.timestamp,
                        'asset': asset,
                        'gain_usd': gain
                    })
                    
                    current_balances[asset] = current_balances.get(asset, Decimal(0)) + amount

            # Calculate Portfolio Metrics
            total_cost_basis_held = Decimal(0)
            total_market_value_est = Decimal(0)
            
            # Sum up inventory for cost basis
            for ast, queue in self.inventory.items():
                asset_qty = Decimal(0)
                asset_cost = Decimal(0)
                for lot in queue:
                    asset_qty += lot['qty']
                    asset_cost += lot['qty'] * lot['unit_cost']
                
                total_cost_basis_held += asset_cost
                
                # Estimate market value
                # Use current price if available, else use cost? Or last known.
                # If we have a last known price, use it.
                price = self.last_known_prices.get(ast, Decimal(0))
                total_market_value_est += asset_qty * price

            # Add Fiat balances to Market Value (1:1 for USD)
            for fiat_currency, bal in current_balances.items():
                if fiat_currency in ['ZUSD', 'USD']:
                     total_cost_basis_held += bal # Cash is its own basis
                     total_market_value_est += bal
                # Handle others if needed

            self.portfolio_history.append({
                'timestamp': tx.timestamp,
                'total_realized_gain': cumulative_realized_gain,
                'total_cost_basis': total_cost_basis_held,
                'total_market_value': total_market_value_est,
                # Snapshot detailed asset state
                'asset_details': {
                    ast: {
                        'qty': sum(lot['qty'] for lot in self.inventory[ast]),
                        'cost_basis': sum(lot['qty'] * lot['unit_cost'] for lot in self.inventory[ast])
                    }
                    for ast in self.inventory if self.inventory[ast]
                }
            })
            
    def get_realized_gains_df(self):
        return pd.DataFrame(self.realized_gains)
    
    def get_history_df(self):
        return pd.DataFrame(self.portfolio_history)

    def get_holdings_summary(self) -> pd.DataFrame:
        """
        Returns a DataFrame summarizing current holdings per asset.
        Columns: Asset, Quantity, UnitPrice, MarketValue, TotalCostBasis, UnrealizedGain
        """
        data = []
        for asset, queue in self.inventory.items():
            qty = sum(lot['qty'] for lot in queue)
            if qty > 0: # Only show positive holdings
                cost_basis = sum(lot['qty'] * lot['unit_cost'] for lot in queue)
                price = self.last_known_prices.get(asset, Decimal(0))
                market_value = qty * price
                
                data.append({
                    'Asset': asset,
                    'Quantity': float(qty),
                    'Unit Price': float(price),
                    'Market Value': float(market_value),
                    'Cost Basis': float(cost_basis),
                    'Avg Buy Price': float(cost_basis / qty) if qty > 0 else 0.0,
                    'Unrealized Gain': float(market_value - cost_basis)
                })
        
        # Also include fiat balances if any? (Not tracked in inventory, need to track separate balance dict if we want that)
        # Ignoring fiat for "Holdings" usually implies Crypto Holdings.
        
        return pd.DataFrame(data)
