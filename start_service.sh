#!/bin/bash
echo "⚡️ Initializing ZAIN TRADER Environment..."

# 1. Create venv if missing
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 2. Activate
source venv/bin/activate

# 3. Install deps
echo "Installing dependencies..."
pip install -r requirements.txt

# 4. Check for .env
if [ ! -f ".env" ]; then
    echo "⚠️  WARNING: .env file missing!"
    echo "Creating template..."
    echo "OANDA_API_KEY=your_key_here" > .env
    echo "OANDA_ACCOUNT_ID=your_id_here" >> .env
    echo "OANDA_ENV=practice" >> .env
    echo "Please edit .env with your real credentials."
    exit 1
fi

# 5. Run Server (with auto-restart)
echo "Starting Interface (with persistence)..."
while true; do
    python app.py
    echo "⚠️  Process crashed or exited. Restarting in 5s..."
    sleep 5
done
