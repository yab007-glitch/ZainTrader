from backtester import ZainBacktester
import pandas as pd

def run_comparison():
    print("⚡️ ZAIN BANK LAB: Initializing...")
    tester = ZainBacktester(instrument="EUR_USD", granularity="M5")
    data = tester.fetch_historical_data(1000) # Longer history for SMC
    
    strategies = ["Zain-Fractal", "Zain-SMC-Advanced"]
    report = []

    for strat in strategies:
        print(f"Testing {strat}...")
        tester.bot.active_strategy = strat
        num_trades, win_rate = tester.test_strategy(data)
        
        rr = 4 if "SMC" in strat else 3
        expectancy = (win_rate * rr) - (1 - win_rate) if num_trades > 0 else 0
        
        report.append({
            "Strategy": strat,
            "Trades": num_trades,
            "Win Rate": f"{win_rate*100:.1f}%",
            "Expectancy": f"{expectancy:.2f}"
        })

    print("\n--- ZAIN BANK STRATEGY REPORT ---")
    df_report = pd.DataFrame(report)
    print(df_report.to_string(index=False))
    return strategies[0]

if __name__ == "__main__":
    run_comparison()
