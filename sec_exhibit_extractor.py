#!/usr/bin/env python3
"""
SEC EDGAR 8-K Exhibit 99.1 Extractor
Searches recent 8-K filings and extracts Exhibit 99.1 information to CSV
"""

import requests
import csv
import time
import re
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sys
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ============================================================================
# CONFIGURATION
# ============================================================================
DAYS_BACK = 7  # How many days to look back for 8-K filings
OUTPUT_FILENAME = "exhibit_99_1_filings.csv"
USER_AGENT = "Mozilla/5.0 (SEC Exhibit Extractor; brendanwbhan@gmail.com)"  # REQUIRED by SEC
REQUEST_DELAY = 0.11  # 0.11 seconds = ~9 requests/second (under SEC limit)
MAX_RETRIES = 3
MAX_WORKERS = 8  # Number of parallel threads for processing filings
MIN_OPTIONS_VOLUME = 10000  # Minimum daily options volume to include stock

# SEC EDGAR API endpoints
SEC_BASE_URL = "https://www.sec.gov"
SEC_DATA_URL = "https://data.sec.gov"

# Thread-safe rate limiting
rate_limit_lock = threading.Lock()
last_request_time = 0

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_sec_headers():
    """Return required headers for SEC EDGAR API requests"""
    return {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Host": "www.sec.gov"
    }

def rate_limit():
    """Enforce rate limiting to comply with SEC guidelines (thread-safe)"""
    global last_request_time
    with rate_limit_lock:
        current_time = time.time()
        time_since_last = current_time - last_request_time
        if time_since_last < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - time_since_last)
        last_request_time = time.time()

def parse_date(date_str: str) -> str:
    """Convert various date formats to YYYY-MM-DD"""
    try:
        # Handle YYYY-MM-DD format
        if len(date_str) == 10 and date_str[4] == '-':
            return date_str
        # Handle YYYYMMDD format
        elif len(date_str) == 8:
            return f"{date_str[0:4]}-{date_str[4:6]}-{date_str[6:8]}"
        else:
            return date_str
    except:
        return date_str

# ============================================================================
# SEC EDGAR DATA EXTRACTION
# ============================================================================

def get_company_tickers() -> Dict:
    """
    Fetch the company tickers JSON file from SEC

    Returns:
        Dictionary mapping CIK to company info
    """
    try:
        rate_limit()
        url = f"{SEC_DATA_URL}/files/company_tickers.json"
        response = requests.get(url, headers=get_sec_headers(), timeout=30)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Warning: Could not fetch company tickers: {e}")
        return {}

def get_recent_8k_filings(days_back: int = 30) -> List[Dict]:
    """
    Fetch recent 8-K filings from SEC EDGAR using daily index files

    Args:
        days_back: Number of days to look back for filings

    Returns:
        List of dictionaries containing filing information
    """
    filings = []
    cutoff_date = datetime.now() - timedelta(days=days_back)

    print(f"Searching for 8-K filings from {cutoff_date.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}...")
    print("Using SEC daily index files for comprehensive coverage...")

    # Use daily index files for maximum coverage
    filings = get_filings_from_daily_index(days_back)

    if not filings:
        print("  Daily index method failed, trying RSS feed...")
        # Fallback to RSS feed if daily index fails
        filings = get_filings_from_rss_feed()

    return filings

def get_filings_from_rss_feed() -> List[Dict]:
    """
    Fetch recent 8-K filings from SEC's RSS feed (limited to ~100 most recent)

    Returns:
        List of filing dictionaries
    """
    filings = []
    url = f"{SEC_BASE_URL}/cgi-bin/browse-edgar"

    params = {
        "action": "getcurrent",
        "type": "8-K",
        "count": "100",
        "output": "atom"
    }

    try:
        rate_limit()
        response = requests.get(url, params=params, headers=get_sec_headers(), timeout=30)
        response.raise_for_status()

        content = response.text
        entries = re.findall(r'<entry>(.*?)</entry>', content, re.DOTALL)

        print(f"  Found {len(entries)} recent 8-K filings from RSS feed")

        for entry in entries:
            filing_data = parse_atom_entry(entry)
            if filing_data:
                filings.append(filing_data)

    except Exception as e:
        print(f"  Error fetching RSS feed: {e}")

    return filings

def get_filings_from_daily_index(days_back: int = 30) -> List[Dict]:
    """
    Fetch 8-K filings from SEC's daily index files (optimized with parallel downloads)

    Args:
        days_back: Number of days to look back

    Returns:
        List of filing dictionaries
    """
    filings = []
    print("  Using daily index files method...")

    # Generate list of dates to check (skip weekends)
    dates_to_check = []
    for day_offset in range(days_back):
        date = datetime.now() - timedelta(days=day_offset)
        # Skip weekends
        if date.weekday() < 5:
            dates_to_check.append(date)

    print(f"  Checking {len(dates_to_check)} business days...")

    def fetch_daily_index(date: datetime) -> List[Dict]:
        """Fetch a single day's index"""
        daily_filings = []
        year = date.strftime("%Y")
        quarter = f"QTR{(date.month - 1) // 3 + 1}"
        date_str = date.strftime("%Y%m%d")

        # SEC daily index URL
        index_url = f"{SEC_BASE_URL}/Archives/edgar/daily-index/{year}/{quarter}/master.{date_str}.idx"

        try:
            rate_limit()
            response = requests.get(index_url, headers=get_sec_headers(), timeout=30)

            if response.status_code == 200:
                lines = response.text.split('\n')

                # Skip header lines (first 10 lines are headers)
                for line in lines[10:]:
                    if '|8-K|' in line or '|8-K/A|' in line:
                        parts = line.split('|')
                        if len(parts) >= 5:
                            cik = parts[0].strip()
                            company_name = parts[1].strip()
                            form_type = parts[2].strip()
                            filing_date = parts[3].strip()
                            filename = parts[4].strip()

                            # Construct the filing URL
                            accession = filename.split('/')[-1].replace('.txt', '')
                            accession_no_dashes = accession.replace('-', '')

                            filing_url = f"{SEC_BASE_URL}/Archives/edgar/data/{cik}/{accession_no_dashes}/{accession}-index.htm"

                            daily_filings.append({
                                "company_name": company_name,
                                "cik": cik,
                                "filing_date": filing_date,
                                "accession": accession_no_dashes,
                                "filing_url": filing_url
                            })
        except Exception as e:
            # It's normal for some dates to not have index files (holidays, etc.)
            pass

        return daily_filings

    # Fetch daily indices in parallel (limited parallelism for rate limiting)
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_date = {executor.submit(fetch_daily_index, date): date for date in dates_to_check}

        processed = 0
        for future in as_completed(future_to_date):
            processed += 1
            try:
                daily_filings = future.result()
                filings.extend(daily_filings)

                if processed % 5 == 0 or processed == len(dates_to_check):
                    print(f"    Processed {processed}/{len(dates_to_check)} days, found {len(filings)} filings so far...")
            except Exception as e:
                pass

    print(f"  Total 8-K filings found from daily index: {len(filings)}")
    return filings

def parse_atom_entry(entry_xml: str) -> Optional[Dict]:
    """Parse an Atom feed entry to extract filing information"""
    try:
        # Extract company name from title (format: "8-K - COMPANY NAME (CIK)")
        title_match = re.search(r'<title[^>]*>(.*?)</title>', entry_xml, re.DOTALL)
        title = title_match.group(1).strip() if title_match else ""

        # Parse company name from title
        company_match = re.search(r'8-K[^-]*-\s*(.+?)\s*\(', title)
        company_name = company_match.group(1).strip() if company_match else "Unknown"

        # Extract filing date from updated tag
        date_match = re.search(r'<updated>(.*?)</updated>', entry_xml)
        filing_date_raw = date_match.group(1).strip() if date_match else ""

        # Parse date (format: YYYY-MM-DDTHH:MM:SS-HH:MM)
        filing_date = filing_date_raw.split('T')[0] if 'T' in filing_date_raw else filing_date_raw

        # Extract filing link
        link_match = re.search(r'<link[^>]+href="([^"]+)"[^>]*rel="alternate"', entry_xml)
        filing_url = link_match.group(1).strip() if link_match else ""

        # Extract CIK and accession from URL
        # URL format: https://www.sec.gov/cgi-bin/viewer?action=view&cik=####&accession_number=####
        cik_match = re.search(r'cik=(\d+)', filing_url)
        accession_match = re.search(r'accession_number=([0-9\-]+)', filing_url)

        cik = cik_match.group(1) if cik_match else ""
        accession = accession_match.group(1).replace('-', '') if accession_match else ""

        # Construct proper filing index URL
        if cik and accession:
            filing_url = f"{SEC_BASE_URL}/cgi-bin/viewer?action=view&cik={cik}&accession_number={accession.replace('-', '')}"

        return {
            "company_name": company_name,
            "cik": cik,
            "filing_date": filing_date,
            "accession": accession,
            "filing_url": filing_url
        }
    except Exception as e:
        return None

def get_ticker_from_cik(cik: str) -> str:
    """
    Attempt to retrieve ticker symbol for a given CIK

    Args:
        cik: Company CIK number

    Returns:
        Ticker symbol or empty string if not found
    """
    try:
        rate_limit()
        # Use SEC's company information endpoint
        url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
        response = requests.get(url, headers=get_sec_headers(), timeout=10)

        if response.status_code == 200:
            data = response.json()
            tickers = data.get("tickers", [])
            return tickers[0] if tickers else ""
        return ""
    except:
        return ""

def get_options_volume(ticker: str) -> int:
    """
    Get the average daily options volume for a ticker

    Args:
        ticker: Stock ticker symbol

    Returns:
        Average daily options volume, or 0 if unavailable
    """
    if not ticker:
        return 0

    try:
        import yfinance as yf

        # Get stock data
        stock = yf.Ticker(ticker)

        # Try to get options data
        try:
            # Get available expiration dates
            exp_dates = stock.options
            if not exp_dates:
                return 0

            # Get the nearest expiration date
            nearest_exp = exp_dates[0]

            # Get option chain for nearest expiration
            opt_chain = stock.option_chain(nearest_exp)

            # Calculate total volume from calls and puts
            calls_volume = opt_chain.calls['volume'].sum() if 'volume' in opt_chain.calls else 0
            puts_volume = opt_chain.puts['volume'].sum() if 'volume' in opt_chain.puts else 0

            total_volume = int(calls_volume + puts_volume)
            return total_volume

        except:
            # If options data unavailable, return 0
            return 0

    except Exception as e:
        # If any error occurs, return 0 (assume no options or unavailable)
        return 0

def find_exhibit_99_1(cik: str, accession: str, filing_url: str) -> Optional[str]:
    """
    Parse filing document to find Exhibit 99.1 PDF URL

    Args:
        cik: Company CIK number
        accession: Filing accession number (without dashes)
        filing_url: URL to the filing page

    Returns:
        Direct URL to Exhibit 99.1 PDF or None if not found
    """
    try:
        rate_limit()

        # Construct the filing detail page URL
        # Format: https://www.sec.gov/Archives/edgar/data/CIK/ACCESSION/ACCESSION-index.htm
        accession_with_dashes = f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"
        index_url = f"{SEC_BASE_URL}/Archives/edgar/data/{cik}/{accession}/{accession_with_dashes}-index.htm"

        # Try the index page first
        response = requests.get(index_url, headers=get_sec_headers(), timeout=30)

        # If index page doesn't work, try alternative URLs
        if response.status_code != 200:
            # Try without -index.htm
            index_url = f"{SEC_BASE_URL}/Archives/edgar/data/{cik}/{accession}/{accession_with_dashes}.txt"
            response = requests.get(index_url, headers=get_sec_headers(), timeout=30)

        if response.status_code != 200:
            # Try the filing_url directly
            response = requests.get(filing_url, headers=get_sec_headers(), timeout=30)

        if response.status_code != 200:
            return None

        content = response.text

        # Look for Exhibit 99.1 references
        # Pattern matches various formats: "99.1", "99 1", "ex99-1", "ex99_1", etc.
        exhibit_patterns = [
            # Match exhibit links in table rows
            r'<tr[^>]*>.*?<td[^>]*>.*?99\.1.*?</td>.*?<a[^>]+href="([^"]+)"',
            r'<tr[^>]*>.*?<td[^>]*>.*?ex(?:hibit)?\s*99\.1.*?</td>.*?<a[^>]+href="([^"]+)"',
            # Match direct links with exhibit text
            r'<a[^>]+href="([^"]+)"[^>]*>.*?ex(?:hibit)?[\s_-]?99[\s._-]1',
            r'<a[^>]+href="([^"]+)"[^>]*>.*?99[\s._-]1',
            # Match filename patterns
            r'href="([^"]*ex99[\-_]?1[^"]*\.(?:htm|html|pdf|txt))"',
            r'href="([^"]*ex99[\-_]?01[^"]*\.(?:htm|html|pdf|txt))"',
            # Match with description containing 99.1
            r'<a[^>]+href="([^"]+)"[^>]*>\s*99\.1\s*</a>',
        ]

        found_urls = []

        for pattern in exhibit_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
            for match in matches:
                # Convert relative URL to absolute
                if match.startswith('/'):
                    doc_url = f"{SEC_BASE_URL}{match}"
                elif not match.startswith('http'):
                    doc_url = f"{SEC_BASE_URL}/Archives/edgar/data/{cik}/{accession}/{match}"
                else:
                    doc_url = match

                # Verify it's a document (htm, html, pdf, txt)
                if any(ext in doc_url.lower() for ext in ['.htm', '.html', '.pdf', '.txt']):
                    # Avoid duplicates
                    if doc_url not in found_urls:
                        found_urls.append(doc_url)

        # Return the first match (most likely to be correct)
        if found_urls:
            return found_urls[0]

        # If no matches found with patterns, try searching the raw content
        # Look for lines containing "99.1" and extract nearby URLs
        lines_with_991 = [line for line in content.split('\n') if '99.1' in line or '99 1' in line]
        for line in lines_with_991:
            url_matches = re.findall(r'href="([^"]+\.(?:htm|html|pdf|txt))"', line, re.IGNORECASE)
            for match in url_matches:
                if match.startswith('/'):
                    doc_url = f"{SEC_BASE_URL}{match}"
                elif not match.startswith('http'):
                    doc_url = f"{SEC_BASE_URL}/Archives/edgar/data/{cik}/{accession}/{match}"
                else:
                    doc_url = match
                return doc_url

        return None

    except Exception as e:
        # Don't print errors for each filing - too noisy
        return None

# ============================================================================
# CSV EXPORT
# ============================================================================

def write_to_csv(data: List[Dict], filename: str):
    """
    Write extracted filing data to CSV file

    Args:
        data: List of filing dictionaries
        filename: Output CSV filename
    """
    fieldnames = [
        "Company Name",
        "CIK Number",
        "Ticker Symbol",
        "Options Volume",
        "Filing Date",
        "Exhibit 99.1 URL",
        "Filing Accession Number"
    ]

    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in data:
                writer.writerow({
                    "Company Name": row.get("company_name", ""),
                    "CIK Number": row.get("cik", ""),
                    "Ticker Symbol": row.get("ticker", ""),
                    "Options Volume": row.get("options_volume", 0),
                    "Filing Date": row.get("filing_date", ""),
                    "Exhibit 99.1 URL": row.get("exhibit_url", ""),
                    "Filing Accession Number": row.get("accession", "")
                })

        print(f"\n✓ Successfully wrote {len(data)} records to {filename}")

    except Exception as e:
        print(f"\n✗ Error writing CSV file: {e}")
        sys.exit(1)

# ============================================================================
# PARALLEL PROCESSING
# ============================================================================

def process_single_filing(filing: Dict, idx: int, total: int) -> Optional[Dict]:
    """
    Process a single filing to find Exhibit 99.1 and check options volume (for parallel execution)

    Args:
        filing: Filing dictionary
        idx: Current index (for progress tracking)
        total: Total number of filings

    Returns:
        Result dictionary if Exhibit 99.1 found and options volume >= MIN_OPTIONS_VOLUME, None otherwise
    """
    company_name_short = filing['company_name'][:50] if len(filing['company_name']) > 50 else filing['company_name']

    # Find Exhibit 99.1
    exhibit_url = find_exhibit_99_1(
        filing['cik'],
        filing['accession'],
        filing['filing_url']
    )

    if exhibit_url:
        # Get ticker symbol (required for options volume check)
        ticker = get_ticker_from_cik(filing['cik'])

        if not ticker:
            # Skip if no ticker found (can't check options volume)
            if idx % 20 == 0:
                print(f"  [{idx}/{total}] ✗ {company_name_short} (no ticker)")
            return None

        # Get options volume
        options_volume = get_options_volume(ticker)

        # Filter by minimum options volume
        if options_volume >= MIN_OPTIONS_VOLUME:
            print(f"  [{idx}/{total}] ✓ {ticker} - {company_name_short} (Options Vol: {options_volume:,})")

            return {
                "company_name": filing['company_name'],
                "cik": filing['cik'],
                "ticker": ticker,
                "filing_date": parse_date(filing['filing_date']),
                "exhibit_url": exhibit_url,
                "accession": filing['accession'],
                "options_volume": options_volume
            }
        else:
            # Filtered out due to low options volume
            if idx % 20 == 0:
                print(f"  [{idx}/{total}] ✗ {ticker} (Options Vol: {options_volume:,} < {MIN_OPTIONS_VOLUME:,})")
            return None
    else:
        # Only print occasionally to reduce noise
        if idx % 50 == 0:
            print(f"  [{idx}/{total}] Processing...")
        return None

# ============================================================================
# MAIN WORKFLOW
# ============================================================================

def main():
    """Main execution function with parallel processing"""
    print("=" * 70)
    print("SEC EDGAR 8-K Exhibit 99.1 Extractor (Parallel Mode)")
    print("=" * 70)
    print()

    # Step 1: Fetch recent 8-K filings
    filings = get_recent_8k_filings(days_back=DAYS_BACK)

    if not filings:
        print("\nNo 8-K filings found in the specified date range.")
        sys.exit(0)

    # Step 2: Process filings in parallel to find Exhibit 99.1
    print(f"\nProcessing {len(filings)} filings with {MAX_WORKERS} parallel workers...")
    print("This may take a few minutes depending on the number of filings...\n")

    results = []
    processed_count = 0

    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_filing = {
            executor.submit(process_single_filing, filing, idx, len(filings)): filing
            for idx, filing in enumerate(filings, 1)
        }

        # Collect results as they complete
        for future in as_completed(future_to_filing):
            processed_count += 1
            try:
                result = future.result()
                if result:
                    results.append(result)
            except Exception as e:
                # Silently skip errors in individual filings
                pass

            # Print progress update every 50 filings
            if processed_count % 50 == 0:
                print(f"  Progress: {processed_count}/{len(filings)} filings processed, {len(results)} with Exhibit 99.1")

    # Step 3: Write results to CSV
    print(f"\n{'=' * 70}")
    print(f"FILTERING SUMMARY:")
    print(f"  Total 8-K filings: {len(filings)}")
    print(f"  Filings with Exhibit 99.1 and options volume >= {MIN_OPTIONS_VOLUME:,}: {len(results)}")
    print(f"  Success rate: {len(results)/len(filings)*100:.1f}%")

    if results:
        # Sort results by options volume (highest first)
        results.sort(key=lambda x: x.get('options_volume', 0), reverse=True)

        write_to_csv(results, OUTPUT_FILENAME)
        print(f"\nTop 5 results by options volume:")
        for i, result in enumerate(results[:5], 1):
            print(f"\n  {i}. {result['ticker']} - {result['company_name']}")
            print(f"     Options Volume: {result.get('options_volume', 0):,}")
            print(f"     Filing Date: {result['filing_date']}")
            print(f"     URL: {result['exhibit_url'][:60]}...")
    else:
        print(f"\nNo filings found with Exhibit 99.1 and options volume >= {MIN_OPTIONS_VOLUME:,}.")
        print(f"Consider lowering MIN_OPTIONS_VOLUME in the configuration.")

    print("\n" + "=" * 70)
    print("Processing complete!")
    print("=" * 70)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by user. Exiting...")
        sys.exit(0)
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        sys.exit(1)