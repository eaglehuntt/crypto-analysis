import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import re
from src.loader import load_csvs, normalize_to_transactions
from src.engine import FIFOEngine
from src.analytics import calculate_portfolio_performance

st.set_page_config(page_title="Crypto Portfolio Analysis", layout="wide")

st.title("Crypto Portfolio Analytics")

# --- Sidebar: Upload & Settings ---
st.sidebar.header("Data Upload")
uploaded_files = st.sidebar.file_uploader("Upload Kraken Ledger CSVs", accept_multiple_files=True, type=['csv'])

st.sidebar.header("Settings")
withdrawals_as_held = st.sidebar.checkbox(
    "Treat withdrawals as Held (Cold Wallet)", 
    value=True, 
    help="If checked, withdrawals (transfers) will NOT be removed from your portfolio inventory. Use this to combine your Cold Wallet holdings with your Exchange history."
)
deposits_as_returns = st.sidebar.checkbox(
    "Treat deposits as Returns (Ignore)", 
    value=False, 
    help="If checked, Deposits will NOT add new assets to your inventory. Use this if you are just moving assets BACK from your Cold Wallet to the Exchange, to avoid double counting."
)

def is_valid_hex_tx(tx_string):
    """Checks if the string is a valid 64-character hex string (likely a blockchain hash)."""
    if not tx_string:
        return False
    # Bitcoin TxID is usually 64 hex chars.
    return bool(re.fullmatch(r'^[0-9a-fA-F]{64}$', str(tx_string)))

if uploaded_files:
    with st.spinner("Loading and processing data..."):
        # Load Data
        df = load_csvs(uploaded_files)
        
        if df.empty:
            st.error("No data found in uploaded files.")
        else:
            try:
                transactions = normalize_to_transactions(df)
                
                # Toast for successful load
                st.toast(f"Loaded {len(transactions)} transactions.", icon='✅')
                
                # --- ASSET FILTER ---
                all_assets = sorted(list(set(t.asset for t in transactions)))
                # Default to BTC if present, else All
                default_sel = ['BTC'] if 'BTC' in all_assets else all_assets
                
                selected_assets_filter = st.sidebar.multiselect(
                    "Active Assets (Filter)", 
                    options=all_assets, 
                    default=default_sel,
                    help="Select which assets to include in the analysis. Unselected assets are ignored."
                )
                
                if selected_assets_filter:
                    transactions = [t for t in transactions if t.asset in selected_assets_filter]
                
                st.toast(f"Analyzing {len(transactions)} transactions for: {', '.join(selected_assets_filter)}", icon='ℹ️')

                # Run Engine
                engine = FIFOEngine(transactions, withdrawals_as_transfers=withdrawals_as_held, deposits_as_transfers=deposits_as_returns)
                engine.run()
                
                # Metrics
                history_df = engine.get_history_df()
                realized_gains_df = engine.get_realized_gains_df()
                holdings_df = engine.get_holdings_summary()
                
                # --- DEFENSIVE CAST TO FLOAT ---
                # Ensure absolutely no Decimals remain to prevent TypeErrors
                for c in ['Quantity', 'Unit Price', 'Market Value', 'Cost Basis', 'Avg Buy Price', 'Unrealized Gain']:
                    if c in holdings_df.columns:
                        holdings_df[c] = holdings_df[c].astype(float)

                # Daily series with External Pricing
                with st.spinner("Fetching historical prices from Yahoo Finance..."):
                     daily_df = calculate_portfolio_performance(history_df)
                
                # --- SYNC HOLDINGS WITH FRESH PRICES ---
                if not daily_df.empty and not holdings_df.empty:
                    latest_row = daily_df.iloc[-1]
                    
                    for asset in holdings_df['Asset']:
                        qty_col = f"{asset}_qty"
                        mv_col = f"{asset}_mv"
                        
                        if qty_col in daily_df.columns and mv_col in daily_df.columns:
                            # Safe access with valid columns
                            qty = latest_row[qty_col]
                            mv = latest_row[mv_col]
                            
                            idx = holdings_df[holdings_df['Asset'] == asset].index
                            
                            if qty > 0:
                                price = mv / qty
                                
                                # Direct float assignment safe now
                                holdings_df.loc[idx, 'Unit Price'] = price
                                holdings_df.loc[idx, 'Market Value'] = holdings_df.loc[idx, 'Quantity'] * price
                                holdings_df.loc[idx, 'Unrealized Gain'] = holdings_df.loc[idx, 'Market Value'] - holdings_df.loc[idx, 'Cost Basis']

                # --- Dashboard ---
                
                # KPIS - Use Daily DF for totals (Includes Cold Wallet MV)
                if not daily_df.empty:
                    latest = daily_df.iloc[-1]
                    
                    unrealized_gain = latest['total_market_value'] - latest['total_cost_basis']
                    
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Total Realized Gain", f"${latest['total_realized_gain']:,.2f}")
                    col2.metric("Total Cost Basis (Held)", f"${latest['total_cost_basis']:,.2f}")
                    col3.metric("Est. Market Value", f"${latest['total_market_value']:,.2f}")
                    col4.metric("Unrealized Gain", f"${unrealized_gain:,.2f}", delta_color="normal")
                    
                    # (REMOVED: Top-level Performance Section - moved to Asset Explorer tab)

                tab1, tab2, tab3, tab4, tab5 = st.tabs(["Overview", "Holdings", "Asset Explorer", "Realized Gains", "Transactions"])
                
                with tab1:
                    st.subheader("Portfolio Growth Over Time")
                    if not daily_df.empty:
                        fig_growth = px.line(daily_df, y=['total_cost_basis', 'total_market_value'], title="Cost Basis vs Market Value")
                        st.plotly_chart(fig_growth, use_container_width=True)
                        
                        st.subheader("Cumulative Realized Gains")
                        fig_gains = px.area(daily_df, y='total_realized_gain', title="Cumulative Realized Gains")
                        st.plotly_chart(fig_gains, use_container_width=True)
                    else:
                        st.info("Not enough data for chart.")

                with tab2:
                    st.subheader("Current Asset Allocation")
                    if not holdings_df.empty:
                        # Pie Chart
                        pie_df = holdings_df[holdings_df['Market Value'] > 1.0] 
                        
                        col_chart, col_table = st.columns([1, 1])
                        
                        with col_chart:
                            fig_pie = px.pie(pie_df, values='Market Value', names='Asset', title='Portfolio Allocation (Market Value)')
                            st.plotly_chart(fig_pie, use_container_width=True)
                            
                        with col_table:
                            # INCREASED PRECISION
                            format_dict = {
                                'Quantity': '{:,.8f}', 
                                'Unit Price': '${:,.2f}',
                                'Market Value': '${:,.2f}',
                                'Cost Basis': '${:,.2f}',
                                'Avg Buy Price': '${:,.2f}',
                                'Unrealized Gain': '${:,.2f}'
                            }
                            st.dataframe(holdings_df.style.format(format_dict))
                    else:
                        st.info("No current holdings found.")

                with tab3:
                    st.subheader("Asset Explorer")
                    available_assets = [c.replace('_qty', '') for c in daily_df.columns if c.endswith('_qty')]
                    if available_assets:
                        # Default index: try to respect filter logic if possible, or just default to first
                        default_idx = 0
                        
                        selected_asset = st.selectbox("Select Asset to View Details", available_assets, index=default_idx)
                        
                        st.markdown(f"### {selected_asset} Performance")
                        
                        # --- Per-Asset Metrics (Moved from Top) ---
                        if not holdings_df.empty:
                             row = holdings_df[holdings_df['Asset'] == selected_asset]
                             if not row.empty:
                                 asset_row = row.iloc[0]
                                 m1, m2, m3 = st.columns(3)
                                 m1.metric("Quantity Held", f"{asset_row['Quantity']:,.8f} {selected_asset}")
                                 m2.metric("Avg Buy Price", f"${asset_row['Avg Buy Price']:,.2f}")
                                 m3.metric("Current Price", f"${asset_row['Unit Price']:,.2f}")
                             else:
                                 st.info(f"No current holdings of {selected_asset} (Sold out or Historic only).")
                        
                        st.divider()
                        
                        cb_col = f"{selected_asset}_cb"
                        mv_col = f"{selected_asset}_mv"
                        
                        if cb_col in daily_df.columns and mv_col in daily_df.columns:
                            fig_asset = go.Figure()
                            fig_asset.add_trace(go.Scatter(x=daily_df.index, y=daily_df[cb_col], mode='lines', name='Cost Basis'))
                            fig_asset.add_trace(go.Scatter(x=daily_df.index, y=daily_df[mv_col], mode='lines', name='Market Value'))
                            fig_asset.update_layout(title=f"{selected_asset} - Cost Basis vs Market Value", hovermode="x unified")
                            st.plotly_chart(fig_asset, use_container_width=True)
                        else:
                            st.warning(f"No detailed history found for {selected_asset}")
                    else:
                        st.info("No assets found in history.")

                with tab4:
                    st.subheader("Realized Gains Log")
                    all_assets = realized_gains_df['asset'].unique().tolist() if not realized_gains_df.empty else []
                    
                    selected_assets = st.multiselect("Filter by Asset", all_assets, default=all_assets)
                    
                    if not realized_gains_df.empty:
                        filtered_gains = realized_gains_df[realized_gains_df['asset'].isin(selected_assets)]
                        display_cols = ['date', 'asset', 'quantity', 'proceeds', 'cost_basis', 'gain_usd', 'tx_type']
                        display_df = filtered_gains[[c for c in display_cols if c in filtered_gains.columns]]
                        
                        # INCREASED PRECISION
                        st.dataframe(display_df.style.format({
                            "quantity": "{:,.8f}",
                            "proceeds": "${:,.2f}",
                            "cost_basis": "${:,.2f}",
                            "gain_usd": "${:,.2f}"
                        }))
                        
                        if not filtered_gains.empty:
                            total_selected_gain = filtered_gains['gain_usd'].sum()
                            st.metric(f"Realized Gain ({', '.join(selected_assets) if len(selected_assets) < 5 else 'Selected'})", f"${total_selected_gain:,.2f}")
                    else:
                        st.info("No realized gains yet.")

                with tab5:
                    st.subheader("Transaction History")
                    
                    # Convert list of transactions objects to DataFrame
                    if transactions:
                        tx_data = []
                        for t in transactions:
                            # LINK LOGIC
                            # Validate if txid is a valid hex hash for Blockchain (64 chars, hex)
                            # If not, try refid? (Often Kraken refid is the real blockchain hash for deposits/withdrawals)
                            
                            explorer_url = None
                            
                            if t.asset == 'BTC':
                                target_hash = None
                                
                                # Try txid first
                                if is_valid_hex_tx(t.txid):
                                    target_hash = t.txid
                                # Try refid second
                                elif is_valid_hex_tx(t.refid):
                                    target_hash = t.refid
                                
                                if target_hash:
                                    explorer_url = f"https://mempool.space/tx/{target_hash}"
                                
                            tx_data.append({
                                'Date': t.timestamp,
                                'Type': t.type,
                                'Asset': t.asset,
                                'Amount': float(t.amount),
                                'Fee': float(t.fee),
                                'Fiat Value': float(t.fiat_value) if t.fiat_value is not None else 0.0,
                                'TxID': t.txid,
                                'RefID': t.refid,
                                'Explorer': explorer_url
                            })
                        
                        tx_df = pd.DataFrame(tx_data)
                        
                        # Display with Column Config for Links
                        st.dataframe(
                            tx_df,
                            column_config={
                                "Explorer": st.column_config.LinkColumn("Explorer", display_text="Mempool.space"),
                                "Amount": st.column_config.NumberColumn("Amount", format="%.8f"),
                                "Fee": st.column_config.NumberColumn("Fee", format="%.8f"),
                                "Fiat Value": st.column_config.NumberColumn("Fiat Value", format="$%.2f"),
                                "Date": st.column_config.DatetimeColumn("Date", format="D MMM YYYY, HH:mm")
                            },
                            column_order=['Date', 'Type', 'Asset', 'Amount', 'Fee', 'Fiat Value', 'Explorer', 'TxID', 'RefID'],
                            use_container_width=True
                        )
                        
                        st.caption(f"Showing {len(tx_df)} transactions.")
                    else:
                        st.info("No transactions to display.")

            except Exception as e:
                st.error(f"Error processing data: {e}")
                import traceback
                st.code(traceback.format_exc())
else:
    st.info("Please upload your Kraken Ledger CSV files to begin.")
