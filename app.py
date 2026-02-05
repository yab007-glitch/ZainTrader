from flask import Flask, render_template, jsonify
from bot import TradingBot
import threading
import json
import os

app = Flask(__name__)
bot = None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_bot():
    global bot
    if not bot:
        try:
            print("Initializing TradingBot...")
            bot = TradingBot()
            print("Starting bot loop...")
            bot.start()
            return jsonify({"status": "started", "message": "Bot initialized and started."})
        except Exception as e:
            print(f"CRITICAL ERROR starting bot: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "running", "message": "Bot is already running."})

@app.route('/api/stop', methods=['POST'])
def stop_bot():
    global bot
    if bot:
        bot.stop()
        bot = None
        return jsonify({"status": "stopped", "message": "Bot stopped."})
    return jsonify({"status": "stopped", "message": "Bot was not running."})

@app.route('/api/state')
def get_state():
    try:
        with open('bot_state.json', 'r') as f:
            data = json.load(f)
            return jsonify(data)
    except FileNotFoundError:
        return jsonify({"status": "Waiting for data..."})

if __name__ == '__main__':
    # Auto-start bot on launch
    try:
        print("Auto-initializing TradingBot...")
        bot = TradingBot()
        bot.start()
        print("Bot started successfully.")
    except Exception as e:
        print(f"Failed to auto-start bot: {e}")

    # Get port from environment variable for Railway compatibility
    port = int(os.environ.get('PORT', 5005))
    print(f"Starting Interface on http://0.0.0.0:{port}")
    app.run(debug=False, host='0.0.0.0', port=port)
