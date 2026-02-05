import os
import pandas as pd
import numpy as np
from bot import TradingBot
import oandapyV20.endpoints.instruments as instruments
from dotenv import load_dotenv

load_dotenv()

class ZainBacktester:
    def __init__(self, instrument="EUR_USD", granularity="M5"):
        self.bot = TradingBot()
        self.instrument = instrument
        self.granularity = granularity

    def fetch_historical_data(self, count=500):
        params = {"granularity": self.granularity, "count": count}
        r = instruments.InstrumentsCandles(instrument=self.instrument, params=params)
        self.bot.client.request(r)
        
        data = []
        for c in r.response['candles']:
            if c['complete']:
                data.append({
                    'time': c['time'],
                    'open': float(c['mid']['o']),
                    'high': float(c['mid']['h']),
                    'low': float(c['mid']['l']),
                    'close': float(c['mid']['c']),
                })
        return pd.DataFrame(data)

    def test_strategy(self, df, strategy_name="Multi-Regime"):
        # This simulates the bot's analyze_market logic over historical data
        # For simplicity, we'll use a basic version of the bot's logic
        df = self.bot.calculate_indicators(df)
        results = []
        
        for i in range(50, len(df)):
            curr_df = df.iloc[:i+1]
            # Mock the bot's internal state for this slice
            self.bot.latest_data[self.instrument] = {"price": curr_df.iloc[-1]['close']}
            
            signal, reason, atr = self.bot.analyze_market_slice(curr_df)
            if signal != "HOLD":
                # Check outcome (look ahead)
                entry_price = curr_df.iloc[-1]['close']
                sl_dist = atr * 2.0
                tp_dist = sl_dist * 3.0
                
                win = None
                for j in range(i+1, len(df)):
                    future_price = df.iloc[j]['close']
                    if signal == "BUY":
                        if future_price >= entry_price + tp_dist: win = True; break
                        if future_price <= entry_price - sl_dist: win = False; break
                    else:
                        if future_price <= entry_price - tp_dist: win = True; break
                        if future_price >= entry_price + sl_dist: win = False; break
                
                if win is not None:
                    results.append(win)
        
        win_rate = sum(results) / len(results) if results else 0
        return len(results), win_rate

# Add analyze_market_slice to bot.py for testing
