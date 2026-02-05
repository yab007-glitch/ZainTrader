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
            bot = TradingBot()
            bot.start()
            return jsonify({"status": "started", "message": "Bot initialized and started."})
        except Exception as e:
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
    # Start the Flask app
    print("Starting Interface on http://localhost:5002")
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=5002)
