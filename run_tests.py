from backtester import ZainBacktester
import pandas as pd

def run_comparison():
    print("⚡️ ZAIN STRATEGY LAB: Initializing...")
    tester = ZainBacktester(instrument="EUR_USD", granularity="M5")
    
    print("Fetching historical data (500 candles)...")
    data = tester.fetch_historical_data(500)
    
    strategies = ["Multi-Regime", "Zain-Fractal"]
    report = []

    for strat in strategies:
        print(f"Testing {strat}...")
        tester.bot.active_strategy = strat
        num_trades, win_rate = tester.test_strategy(data)
        report.append({
            "Strategy": strat,
            "Trades": num_trades,
            "Win Rate": f"{win_rate*100:.1f}%",
            "Expected Profit": f"{(num_trades * win_rate * 3) - (num_trades * (1-win_rate))} units"
        })

    print("\n--- ZAIN TRADER STRATEGY REPORT ---")
    df_report = pd.DataFrame(report)
    print(df_report.to_string(index=False))
    
    # Auto-select the best one
    best_strat = strategies[0]
    # Simple heuristic: Trades * Win Rate
    # (Actually we want Expectancy: (WR * 3) - (L*1))
    best_expectancy = -999
    for r in report:
        wr = float(r["Win Rate"].replace('%','')) / 100
        expectancy = (wr * 3) - (1 - wr)
        if expectancy > best_expectancy:
            best_expectancy = expectancy
            best_strat = r["Strategy"]
            
    print(f"\n🏆 WINNER: {best_strat}")
    return best_strat

if __name__ == "__main__":
    run_comparison()
