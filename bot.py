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

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ZainTrader")

class TradingBot:
    def __init__(self):
        self.token = os.environ.get("OANDA_API_KEY")
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID")
        self.env = os.environ.get("OANDA_ENV", "practice")
        
        # Debugging (Sanitized)
        print(f"DEBUG: OANDA_API_KEY exists: {bool(self.token)}")
        print(f"DEBUG: OANDA_ACCOUNT_ID exists: {bool(self.account_id)}")
        print(f"DEBUG: OANDA_ENV: {self.env}")

        if not self.token or not self.account_id:
            missing = []
            if not self.token: missing.append("OANDA_API_KEY")
            if not self.account_id: missing.append("OANDA_ACCOUNT_ID")
            raise ValueError(f"Missing environment variables: {', '.join(missing)}")

        self.client = oandapyV20.API(access_token=self.token, environment=self.env)
        
        # Configuration
        self.instruments = ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "USD_CAD"]
        self.timeframe = "M5"
        self.risk_per_trade = 0.01  # 1% risk
        self.state_file = "bot_state.json"
        
        # State
        self.running = False
        self.active_trades = {}
        self.latest_data = {}

    def get_candles(self, instrument, count=200):
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
        # EMAs
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = exp1 - exp2
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['hist'] = df['macd'] - df['signal']
        
        # ATR
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=14).mean()
        
        return df

    def analyze_market(self, instrument):
        df = self.get_candles(instrument)
        df = self.calculate_indicators(df)
        
        curr = df.iloc[-1]
        prev = df.iloc[-2]
        
        signal = "HOLD"
        reason = ""
        
        # Strategy: Trend Pullback
        # Uptrend: EMA 50 > EMA 200
        is_uptrend = curr['ema_50'] > curr['ema_200']
        is_downtrend = curr['ema_50'] < curr['ema_200']
        
        if is_uptrend:
            # Buy Dip: RSI < 40 and MACD Hist ticking up
            if curr['rsi'] < 45 and curr['hist'] > prev['hist']:
                signal = "BUY"
                reason = "Uptrend Dip Buy"
        elif is_downtrend:
            # Sell Rally: RSI > 60 and MACD Hist ticking down
            if curr['rsi'] > 55 and curr['hist'] < prev['hist']:
                signal = "SELL"
                reason = "Downtrend Rally Sell"
                
        # Update latest data for dashboard
        self.latest_data[instrument] = {
            "price": curr['close'],
            "rsi": round(curr['rsi'], 2),
            "trend": "UP" if is_uptrend else "DOWN",
            "last_updated": datetime.now().isoformat()
        }
        
        return signal, reason, curr['atr']

    def execute_trade(self, instrument, signal, atr):
        # 1. Get Account Balance
        r = accounts.AccountSummary(self.account_id)
        self.client.request(r)
        balance = float(r.response['account']['balance'])
        
        # 2. Risk Management
        risk_amount = balance * self.risk_per_trade
        sl_pips = (atr * 1.5)  # SL is 1.5x ATR
        
        # Calculate Units
        # Simplified: Assuming USD quote currency for now (pip value ~ $0.0001 per unit)
        # Real impl needs specific pip value calc per pair
        pip_size = 0.0001
        if "JPY" in instrument: pip_size = 0.01
            
        sl_distance = sl_pips
        units = int(risk_amount / sl_distance)
        
        if units <= 0:
            logger.warning(f"Calculated units 0 for {instrument}. Skipping.")
            return

        # 3. Place Order
        # Market Order with SL/TP attached
        current_price = self.latest_data[instrument]['price']
        
        if signal == "BUY":
            sl_price = current_price - sl_distance
            tp_price = current_price + (sl_distance * 2) # 1:2 Risk/Reward
            units = units # Positive for Buy
        else:
            sl_price = current_price + sl_distance
            tp_price = current_price - (sl_distance * 2)
            units = -units # Negative for Sell
            
        order_data = {
            "order": {
                "instrument": instrument,
                "units": str(units),
                "type": "MARKET",
                "positionFill": "DEFAULT",
                "stopLossOnFill": {"price": f"{sl_price:.5f}"},
                "takeProfitOnFill": {"price": f"{tp_price:.5f}"}
            }
        }
        
        logger.info(f"PLACING ORDER: {signal} {instrument} | Units: {units} | SL: {sl_price} | TP: {tp_price}")
        
        try:
            r = orders.OrderCreate(self.account_id, data=order_data)
            self.client.request(r)
            logger.info(f"Order Successful: {r.response}")
        except Exception as e:
            logger.error(f"Order Failed: {e}")

    def update_state(self):
        # Dump state to JSON for the UI to read
        state = {
            "status": "Running" if self.running else "Stopped",
            "account_id": self.account_id,
            "latest_data": self.latest_data,
            "active_trades": self.get_open_trades() # Fetch from API
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def get_open_trades(self):
        try:
            r = list(positions.OpenPositions(self.account_id).request(self.client.request))
            # OANDA returns a list, need to parse
            # Simplified for now: just return raw response or empty
            if 'positions' in r[0]:
                 return r[0]['positions']
            return []
        except:
            return []

    def run_loop(self):
        self.running = True
        logger.info("Bot Loop Started")
        
        while self.running:
            for inst in self.instruments:
                try:
                    signal, reason, atr = self.analyze_market(inst)
                    if signal != "HOLD":
                        logger.info(f"SIGNAL FOUND: {inst} {signal} ({reason})")
                        self.execute_trade(inst, signal, atr)
                    else:
                        logger.info(f"Scanning {inst}... No Signal.")
                except Exception as e:
                    logger.error(f"Error scanning {inst}: {e}")
            
            self.update_state()
            time.sleep(60) # Scan every minute

    def start(self):
        t = threading.Thread(target=self.run_loop)
        t.daemon = True
        t.start()

    def stop(self):
        self.running = False
