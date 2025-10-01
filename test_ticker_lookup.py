#!/usr/bin/env python3
"""
Quick diagnostic script to test ticker lookup for known companies
"""

import requests
import json
import time

USER_AGENT = "Mozilla/5.0 (SEC Exhibit Extractor; brendanwbhan@gmail.com)"

def test_ticker_lookup(cik, expected_ticker, company_name):
    """Test ticker lookup for a specific CIK"""
    print(f"\n{'='*70}")
    print(f"Testing: {company_name}")
    print(f"CIK: {cik}")
    print(f"Expected Ticker: {expected_ticker}")
    print(f"{'='*70}")

    cik_padded = cik.strip().zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Host": "data.sec.gov"
    }

    print(f"URL: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            # Print relevant fields
            print("\nResponse Structure:")
            print(f"  Keys in response: {list(data.keys())[:10]}")

            print("\nTicker-related fields:")
            print(f"  'tickers': {data.get('tickers', 'NOT FOUND')}")
            print(f"  'ticker': {data.get('ticker', 'NOT FOUND')}")
            print(f"  'name': {data.get('name', 'NOT FOUND')}")
            print(f"  'entityType': {data.get('entityType', 'NOT FOUND')}")

            # Try extraction
            if "tickers" in data and data["tickers"]:
                print(f"\n✓ Found ticker: {data['tickers'][0]}")
            else:
                print(f"\n✗ Ticker not found in 'tickers' field")

        elif response.status_code == 403:
            print("\n⚠️  403 FORBIDDEN - Rate limited or blocked!")
            print("   The SEC API may be blocking requests")

        else:
            print(f"\n✗ HTTP {response.status_code}")

    except Exception as e:
        print(f"\n✗ Error: {e}")

    time.sleep(0.2)  # Rate limit

# Test known companies from the user's output
print("SEC EDGAR Ticker Lookup Diagnostic")
print("="*70)

test_ticker_lookup("1861449", "BYND", "Beyond Meat Inc")
test_ticker_lookup("1740516", "ONDS", "Ondas Holdings Inc")
test_ticker_lookup("1702732", "MRUS", "Merus N.V.")
test_ticker_lookup("1792580", "OVV", "Ovintiv Inc")

print(f"\n{'='*70}")
print("Diagnostic Complete")
print(f"{'='*70}")
