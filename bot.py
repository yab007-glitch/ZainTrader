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
        self.active_strategy = "Zain-Fractal" # Winning strategy from backtest

    def get_candles(self, instrument, count=300):
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
        # Base indicators
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))
        df['ma_20'] = df['close'].rolling(window=20).mean()
        df['std_20'] = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['ma_20'] + (df['std_20'] * 2)
        df['bb_lower'] = df['ma_20'] - (df['std_20'] * 2)
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()
        
        # ADX
        df['up_move'] = df['high'] - df['high'].shift()
        df['down_move'] = df['low'].shift() - df['low']
        df['plus_dm'] = np.where((df['up_move'] > df['down_move']) & (df['up_move'] > 0), df['up_move'], 0)
        df['minus_dm'] = np.where((df['down_move'] > df['up_move']) & (df['down_move'] > 0), df['down_move'], 0)
        df['plus_di'] = 100 * (df['plus_dm'].rolling(14).mean() / df['atr'].replace(0, 1))
        df['minus_di'] = 100 * (df['minus_dm'].rolling(14).mean() / df['atr'].replace(0, 1))
        df['dx'] = 100 * (abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di']).replace(0, 1))
        df['adx'] = df['dx'].rolling(14).mean()

        # ZAIN ORIGINAL: Fractal Complexity (Efficiency Ratio)
        # Price change over N periods / sum of absolute changes
        n = 10
        df['net_change'] = (df['close'] - df['close'].shift(n)).abs()
        df['sum_changes'] = (df['close'].diff().abs()).rolling(n).sum()
        df['fractal_efficiency'] = df['net_change'] / df['sum_changes'].replace(0, 1)

        return df

    def analyze_market_slice(self, df):
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        signal = "HOLD"
        reason = ""
        
        if self.active_strategy == "Multi-Regime":
            regime = "TRENDING" if curr['adx'] > 25 else "RANGING"
            if regime == "RANGING":
                if curr['close'] >= curr['bb_upper'] and curr['rsi'] > 70:
                    signal = "SELL"; reason = "MR-Ranging-Sell"
                elif curr['close'] <= curr['bb_lower'] and curr['rsi'] < 30:
                    signal = "BUY"; reason = "MR-Ranging-Buy"
            else:
                is_uptrend = curr['ema_50'] > curr['ema_200']
                if is_uptrend and curr['rsi'] < 45 and curr['close'] > curr['ema_50']:
                    signal = "BUY"; reason = "MR-Trending-Buy"
                elif not is_uptrend and curr['rsi'] > 55 and curr['close'] < curr['ema_50']:
                    signal = "SELL"; reason = "MR-Trending-Sell"
                    
        elif self.active_strategy == "Zain-Fractal":
            # Strategy: High Efficiency (Clear Move) + Overstretched RSI
            # If efficiency > 0.6, it's a very clean move
            if curr['fractal_efficiency'] > 0.6:
                if curr['rsi'] > 75: signal = "SELL"; reason = "Zain-Fractal-Top"
                elif curr['rsi'] < 25: signal = "BUY"; reason = "Zain-Fractal-Bottom"

        return signal, reason, curr['atr']

    def analyze_market(self, instrument):
        df = self.get_candles(instrument)
        df = self.calculate_indicators(df)
        signal, reason, atr = self.analyze_market_slice(df)
        
        curr = df.iloc[-1]
        self.latest_data[instrument] = {
            "price": curr['close'],
            "rsi": round(curr['rsi'], 2),
            "trend": "Trending" if curr['adx'] > 25 else "Ranging",
            "efficiency": round(curr['fractal_efficiency'], 2),
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
            sl_distance = (atr * 2.0)
            units = int(risk_amount / sl_distance)
            current_price = self.latest_data[instrument]['price']
            est_margin = (current_price * units) / 20
            if est_margin > margin_available:
                units = int(units * (margin_available * 0.8) / est_margin)
            if units <= 0: return
            if signal == "BUY":
                sl_price = current_price - sl_distance
                tp_price = current_price + (sl_distance * 3)
            else:
                sl_price = current_price + sl_distance
                tp_price = current_price - (sl_distance * 3)
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
            logger.info(f"TRADE [{self.active_strategy}]: {instrument} {signal} | Units: {units}")
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
        logger.info(f"ZAIN ENGINE: Active (Strategy: {self.active_strategy})")
        while self.running:
            for inst in self.instruments:
                try:
                    signal, reason, atr = self.analyze_market(inst)
                    if signal != "HOLD":
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
