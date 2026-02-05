import os
import time
import logging
import json
import threading
from datetime import datetime
import pytz
import oandapyV20
import oandapyV20.endpoints.instruments as instruments
import oandapyV20.endpoints.orders as orders
import oandapyV20.endpoints.accounts as accounts
import oandapyV20.endpoints.pricing as pricing
import oandapyV20.endpoints.positions as positions
import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger("ZainTrader")

class TradingBot:
    def __init__(self):
        self.token = os.environ.get("OANDA_API_KEY")
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID")
        self.env = os.environ.get("OANDA_ENV", "practice")
        
        if not self.token or not self.account_id:
            raise ValueError("Missing OANDA_API_KEY or OANDA_ACCOUNT_ID")

        self.client = oandapyV20.API(access_token=self.token, environment=self.env)
        self.instruments = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
        self.timeframe = "M5"
        self.state_file = "bot_state.json"
        self.running = False
        self.latest_data = {}
        self.active_strategy = "Zain-SMC-Advanced" # The new Bank Strategy

    def get_candles(self, instrument, count=500):
        params = {"granularity": self.timeframe, "count": count}
        r = instruments.InstrumentsCandles(instrument=instrument, params=params)
        self.client.request(r)
        data = []
        for c in r.response['candles']:
            if c['complete']:
                data.append({
                    'time': c['time'],
                    'open': float(c['mid']['o']),
                    'high': float(c['mid']['h']),
                    'low': float(c['mid']['l']),
                    'close': float(c['mid']['c']),
                    'volume': int(c['volume'])
                })
        df = pd.DataFrame(data)
        df['time'] = pd.to_datetime(df['time'])
        return df

    def calculate_indicators(self, df):
        # 1. Volatility
        df['atr'] = (df['high'] - df['low']).rolling(window=14).mean()
        
        # 2. SMC: Liquidity Zones (H/L of the last 50 candles)
        df['swing_high'] = df['high'].rolling(50).max().shift(1)
        df['swing_low'] = df['low'].rolling(50).min().shift(1)
        
        # 3. SMC: Liquidity Sweep Detection
        # Bullish Sweep: Price went below swing_low then closed above it
        df['bull_sweep'] = (df['low'] < df['swing_low']) & (df['close'] > df['swing_low'])
        # Bearish Sweep: Price went above swing_high then closed below it
        df['bear_sweep'] = (df['high'] > df['swing_high']) & (df['close'] < df['swing_high'])
        
        # 4. SMC: Fair Value Gaps (Imbalance)
        df['bull_fvg'] = (df['high'].shift(2) < df['low'])
        df['bear_fvg'] = (df['low'].shift(2) > df['high'])
        
        # 5. Market Structure Shift (MSS)
        # Using a shorter 10-period window for reaction
        df['short_high'] = df['high'].rolling(10).max().shift(1)
        df['short_low'] = df['low'].rolling(10).min().shift(1)
        df['mss_bull'] = (df['close'] > df['short_high'])
        df['mss_bear'] = (df['close'] < df['short_low'])

        return df

    def analyze_market_slice(self, df):
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        signal = "HOLD"
        reason = ""
        
        if self.active_strategy == "Zain-SMC-Advanced":
            # The "Bank Reversal": 
            # 1. Price sweeps a major liquidity zone (swing high/low)
            # 2. Market Structure Shifts in the opposite direction
            # 3. Entry on the FVG created by the shift
            
            # For simplicity on M5: We look for the Sweep + MSS combo
            if curr['bull_sweep'] and curr['mss_bull']:
                signal = "BUY"; reason = "SMC-Bank-Liquidity-Sweep-Bull"
            elif curr['bear_sweep'] and curr['mss_bear']:
                signal = "SELL"; reason = "SMC-Bank-Liquidity-Sweep-Bear"
            
            # Alternative: FVG re-entry
            elif curr['mss_bull'] and curr['bull_fvg']:
                signal = "BUY"; reason = "SMC-Imbalance-Fill-Bull"
            elif curr['mss_bear'] and curr['bear_fvg']:
                signal = "SELL"; reason = "SMC-Imbalance-Fill-Bear"

        return signal, reason, curr['atr']

    def analyze_market(self, instrument):
        df = self.get_candles(instrument)
        df = self.calculate_indicators(df)
        signal, reason, atr = self.analyze_market_slice(df)
        
        curr = df.iloc[-1]
        self.latest_data[instrument] = {
            "price": curr['close'],
            "strategy": self.active_strategy,
            "sweep": "Bull" if curr['bull_sweep'] else ("Bear" if curr['bear_sweep'] else "None"),
            "structure": "Broken-High" if curr['mss_bull'] else ("Broken-Low" if curr['mss_bear'] else "Stable"),
            "last_updated": datetime.now().isoformat()
        }
        return signal, reason, atr

    def execute_trade(self, instrument, signal, atr):
        try:
            r = accounts.AccountSummary(self.account_id)
            self.client.request(r)
            balance = float(r.response['account']['balance'])
            margin_available = float(r.response['account']['marginAvailable'])
            risk_amount = balance * 0.005
            sl_distance = (atr * 1.5)
            units = int(risk_amount / sl_distance)
            current_price = self.latest_data[instrument]['price']
            est_margin = (current_price * units) / 20
            if est_margin > margin_available:
                units = int(units * (margin_available * 0.8) / est_margin)
            if units <= 0: return
            
            if signal == "BUY":
                sl_price = current_price - sl_distance
                tp_price = current_price + (sl_distance * 4) # SMC targets: 1:4
            else:
                sl_price = current_price + sl_distance
                tp_price = current_price - (sl_distance * 4)
                units = -units
                
            order_data = {
                "order": {
                    "instrument": instrument, "units": str(units), "type": "MARKET",
                    "positionFill": "DEFAULT",
                    "stopLossOnFill": {"price": f"{sl_price:.5f}"},
                    "takeProfitOnFill": {"price": f"{tp_price:.5f}"}
                }
            }
            r = orders.OrderCreate(self.account_id, data=order_data)
            self.client.request(r)
            logger.info(f"BANK TRADE [{self.active_strategy}]: {instrument} {signal}")
        except Exception as e:
            logger.error(f"Trade Failed: {e}")

    def update_state(self):
        state = {
            "status": "Running",
            "strategy": self.active_strategy,
            "account_id": self.account_id,
            "latest_data": self.latest_data,
            "active_trades": self.get_open_trades()
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def get_open_trades(self):
        try:
            r = positions.OpenPositions(accountID=self.account_id)
            self.client.request(r)
            return r.response.get('positions', [])
        except: return []

    def run_loop(self):
        self.running = True
        logger.info(f"ZAIN BANK ENGINE: Active (Strategy: {self.active_strategy})")
        while self.running:
            for inst in self.instruments:
                try:
                    signal, reason, atr = self.analyze_market(inst)
                    if signal != "HOLD":
                        logger.info(f"SMC SIGNAL [{inst}]: {signal} via {reason}")
                        self.execute_trade(inst, signal, atr)
                except Exception as e:
                    logger.error(f"Error: {e}")
            try: self.update_state()
            except: pass
            time.sleep(30)

    def start(self):
        t = threading.Thread(target=self.run_loop)
        t.daemon = True
        t.start()

    def stop(self):
        self.running = False
