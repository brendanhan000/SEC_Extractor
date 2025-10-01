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
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import sys
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# ============================================================================
# CONFIGURATION
# ============================================================================
DAYS_BACK = 2  # How many days to look back for 8-K filings
OUTPUT_FILENAME = "exhibit_99_1_filings.csv"
USER_AGENT = "Mozilla/5.0 (SEC Exhibit Extractor; brendanwbhan@gmail.com)"  # REQUIRED by SEC
REQUEST_DELAY = 0.11  # 0.11 seconds = ~9 requests/second (under SEC limit)
MAX_RETRIES = 3
MAX_WORKERS = 8  # Number of parallel threads for processing filings
MIN_OPTIONS_VOLUME = 0  # Minimum daily options volume to include stock
ENABLE_CLAUDE_ANALYSIS = True  # Enable Claude AI analysis of Exhibit 99.1 content
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # Set via environment variable

# SEC EDGAR API endpoints
SEC_BASE_URL = "https://www.sec.gov"
SEC_DATA_URL = "https://data.sec.gov"

# Thread-safe rate limiting
rate_limit_lock = threading.Lock()
last_request_time = 0

# Cache for company tickers (load once at startup)
TICKER_CACHE = {}
TICKER_CACHE_LOADED = False

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

def load_ticker_cache():
    """
    Load the SEC company tickers file into cache (CIK -> Ticker mapping)
    This is called once at startup to avoid repeated API calls
    """
    global TICKER_CACHE, TICKER_CACHE_LOADED

    if TICKER_CACHE_LOADED:
        return

    try:
        print("Loading SEC company ticker cache...")
        url = f"{SEC_DATA_URL}/files/company_tickers.json"

        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov"
        }

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        data = response.json()

        # Structure: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        for key, company in data.items():
            if isinstance(company, dict):
                cik_str = str(company.get("cik_str", "")).zfill(10)
                ticker = company.get("ticker", "")
                if cik_str and ticker:
                    TICKER_CACHE[cik_str] = ticker.upper()

        TICKER_CACHE_LOADED = True
        print(f"✓ Loaded {len(TICKER_CACHE)} company tickers into cache")

    except Exception as e:
        print(f"⚠️  Warning: Could not load ticker cache: {e}")
        print("   Ticker lookups will use slower API method")
        TICKER_CACHE_LOADED = True  # Don't try again

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
    Retrieve ticker symbol for a given CIK using cache-first approach

    Args:
        cik: Company CIK number

    Returns:
        Ticker symbol or empty string if not found
    """
    if not cik or not cik.strip():
        return ""

    cik_padded = cik.strip().zfill(10)

    # Method 1: Check cache first (FASTEST - no API call)
    if cik_padded in TICKER_CACHE:
        return TICKER_CACHE[cik_padded]

    # Method 2: Try API lookup as fallback (slower)
    try:
        rate_limit()
        url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"

        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov"
        }

        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()

            # Check "tickers" array
            if "tickers" in data and isinstance(data["tickers"], list) and len(data["tickers"]) > 0:
                ticker = data["tickers"][0]
                if ticker and isinstance(ticker, str) and len(ticker) <= 10:
                    ticker_upper = ticker.strip().upper()
                    # Cache for future lookups
                    TICKER_CACHE[cik_padded] = ticker_upper
                    return ticker_upper

            # Check "ticker" string field
            if "ticker" in data and data["ticker"]:
                ticker = data["ticker"]
                if isinstance(ticker, str) and len(ticker) <= 10:
                    ticker_upper = ticker.strip().upper()
                    TICKER_CACHE[cik_padded] = ticker_upper
                    return ticker_upper

        return ""

    except Exception as e:
        return ""

def get_options_volume(ticker: str) -> int:
    """
    Get the average daily options volume for a ticker

    Args:
        ticker: Stock ticker symbol

    Returns:
        Average daily options volume, or 0 if unavailable
    """
    if not ticker or not ticker.strip():
        return 0

    # Validate ticker format (basic check)
    ticker = ticker.strip().upper()
    if not ticker.replace('.', '').replace('-', '').isalnum():
        return 0

    try:
        import yfinance as yf
        import pandas as pd

        # Get stock data
        stock = yf.Ticker(ticker)

        # Try to get options data
        try:
            # Get available expiration dates
            exp_dates = stock.options
            if not exp_dates or len(exp_dates) == 0:
                return 0

            # Get the nearest expiration date
            nearest_exp = exp_dates[0]

            # Get option chain for nearest expiration
            opt_chain = stock.option_chain(nearest_exp)

            # Calculate total volume from calls and puts, handling NaN
            calls_volume = 0
            puts_volume = 0

            if 'volume' in opt_chain.calls.columns:
                calls_sum = opt_chain.calls['volume'].sum()
                calls_volume = 0 if pd.isna(calls_sum) else int(calls_sum)

            if 'volume' in opt_chain.puts.columns:
                puts_sum = opt_chain.puts['volume'].sum()
                puts_volume = 0 if pd.isna(puts_sum) else int(puts_sum)

            total_volume = calls_volume + puts_volume
            return max(0, total_volume)  # Ensure non-negative

        except Exception as inner_e:
            # If options data unavailable, return 0
            return 0

    except Exception as e:
        # If any error occurs, return 0 (assume no options or unavailable)
        return 0

def analyze_exhibit_with_claude(exhibit_url: str, company_name: str) -> str:
    """
    Fetch Exhibit 99.1 content and analyze it with Claude AI for private offerings

    Args:
        exhibit_url: URL to the Exhibit 99.1 document
        company_name: Name of the company

    Returns:
        Analysis summary or error message
    """
    if not ENABLE_CLAUDE_ANALYSIS or not ANTHROPIC_API_KEY:
        return "Analysis disabled"

    try:
        # Fetch the document content
        rate_limit()
        response = requests.get(exhibit_url, headers=get_sec_headers(), timeout=30)

        if response.status_code != 200:
            return "Unable to fetch document"

        content = response.text

        # Strip HTML tags for cleaner analysis
        # Simple regex to remove HTML (not perfect but good enough)
        text_content = re.sub(r'<[^>]+>', ' ', content)
        text_content = re.sub(r'\s+', ' ', text_content).strip()

        # Limit content to avoid token limits (~100k chars = ~25k tokens)
        if len(text_content) > 100000:
            text_content = text_content[:100000] + "... [truncated]"

        # Initialize Anthropic client
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_API_KEY)

        # Analyze with Claude
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            temperature=0,
            messages=[{
                "role": "user",
                "content": f"""Analyze this SEC Exhibit 99.1 filing for {company_name} and determine if it mentions any private offering, PIPE transaction, private placement, or similar equity financing.

Document content:
{text_content}

Provide a concise summary (2-3 sentences max) focusing ONLY on:
1. Is there a private offering/PIPE/placement mentioned? (Yes/No)
2. If yes, what are the key terms? (amount, price, investors)
3. If no private offering, what is the main topic of this filing?

Be specific and factual. Use numbers when available."""
            }]
        )

        # Extract the response
        analysis = message.content[0].text if message.content else "No analysis available"

        # Clean up and limit length for CSV
        analysis = analysis.replace('\n', ' ').replace('\r', ' ').strip()
        if len(analysis) > 500:
            analysis = analysis[:497] + "..."

        return analysis

    except Exception as e:
        return f"Analysis error: {str(e)[:50]}"

def find_exhibit_99_1(cik: str, accession: str, filing_url: str) -> Optional[str]:
    """
    Parse filing document to find Exhibit 99.1 URL using multiple strategies

    Args:
        cik: Company CIK number
        accession: Filing accession number (without dashes)
        filing_url: URL to the filing page

    Returns:
        Direct URL to Exhibit 99.1 or None if not found
    """
    try:
        rate_limit()

        # Remove any dashes if present
        accession_clean = accession.replace('-', '')

        # Construct the filing detail page URL
        if len(accession_clean) >= 18:
            # Standard format: 0001234567-24-000123 -> 0001234567-24-000123
            accession_with_dashes = f"{accession_clean[:10]}-{accession_clean[10:12]}-{accession_clean[12:]}"
        else:
            accession_with_dashes = accession_clean

        # Try multiple URL formats
        urls_to_try = [
            f"{SEC_BASE_URL}/Archives/edgar/data/{cik}/{accession_clean}/{accession_with_dashes}-index.htm",
            f"{SEC_BASE_URL}/Archives/edgar/data/{cik}/{accession_clean}/{accession_with_dashes}-index.html",
            f"{SEC_BASE_URL}/cgi-bin/viewer?action=view&cik={cik}&accession_number={accession_with_dashes}&xbrl_type=v",
            filing_url  # Fallback to provided URL
        ]

        content = None
        successful_url = None

        for url in urls_to_try:
            try:
                response = requests.get(url, headers=get_sec_headers(), timeout=30)
                if response.status_code == 200:
                    content = response.text
                    successful_url = url
                    break
            except:
                continue

        if not content:
            return None

        # Strategy 1: Parse HTML table structure
        # Most 8-K index pages have a table with exhibit numbers and links
        table_patterns = [
            # Table row with exhibit number and link
            r'<tr[^>]*>.*?<td[^>]*>\s*(?:Exhibit\s+)?99\.1\s*</td>.*?<td[^>]*>.*?<a[^>]+href=["\']([^"\']+)["\']',
            r'<tr[^>]*>.*?<td[^>]*>\s*99\.1\s*</td>.*?<a[^>]+href=["\']([^"\']+)["\']',
            # Row with EX-99.1 format
            r'<tr[^>]*>.*?<td[^>]*>\s*EX-99\.1\s*</td>.*?<a[^>]+href=["\']([^"\']+)["\']',
        ]

        for pattern in table_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
            for match in matches:
                doc_url = normalize_url(match, cik, accession_clean)
                if is_valid_document_url(doc_url):
                    return doc_url

        # Strategy 2: Look for direct exhibit links with 99.1 in the text
        link_text_patterns = [
            # Link with 99.1 in text
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>[^<]*?(?:Exhibit\s+)?99\.1[^<]*?</a>',
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>[^<]*?EX-99\.1[^<]*?</a>',
            # Link followed by 99.1 description
            r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>[^<]*?</a>[^<]*?99\.1',
        ]

        for pattern in link_text_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
            for match in matches:
                doc_url = normalize_url(match, cik, accession_clean)
                if is_valid_document_url(doc_url):
                    return doc_url

        # Strategy 3: Look for filename patterns (ex99-1, ex991, etc.)
        filename_patterns = [
            r'href=["\']([^"\']*(?:ex|exhibit)[-_]?99[-_\.]1[^"\']*?\.(?:htm|html|pdf|txt))["\']',
            r'href=["\']([^"\']*(?:ex|exhibit)[-_]?9901[^"\']*?\.(?:htm|html|pdf|txt))["\']',
            r'href=["\']([^"\']*d\d+dex991[^"\']*?\.(?:htm|html|pdf|txt))["\']',  # d123456dex991.htm format
        ]

        for pattern in filename_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                doc_url = normalize_url(match, cik, accession_clean)
                if is_valid_document_url(doc_url):
                    return doc_url

        # Strategy 4: Search for any mention of 99.1 and nearby links
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if '99.1' in line or '99 1' in line or 'EX-99.1' in line.upper():
                # Check current line and next 3 lines for links
                check_lines = lines[i:min(i+4, len(lines))]
                for check_line in check_lines:
                    url_matches = re.findall(r'href=["\']([^"\']+\.(?:htm|html|pdf|txt))["\']', check_line, re.IGNORECASE)
                    for match in url_matches:
                        doc_url = normalize_url(match, cik, accession_clean)
                        if is_valid_document_url(doc_url):
                            return doc_url

        return None

    except Exception as e:
        return None

def normalize_url(url: str, cik: str, accession: str) -> str:
    """Convert relative URLs to absolute URLs"""
    if url.startswith('http'):
        return url
    elif url.startswith('/'):
        return f"{SEC_BASE_URL}{url}"
    else:
        return f"{SEC_BASE_URL}/Archives/edgar/data/{cik}/{accession}/{url}"

def is_valid_document_url(url: str) -> bool:
    """Check if URL looks like a valid document"""
    if not url:
        return False
    url_lower = url.lower()
    # Must be a document file
    if not any(ext in url_lower for ext in ['.htm', '.html', '.pdf', '.txt']):
        return False
    # Exclude index pages and XML files
    if 'index.htm' in url_lower or '.xml' in url_lower:
        return False
    return True

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
    if not data:
        print(f"\n⚠️  No data to write to CSV")
        return

    fieldnames = [
        "Company Name",
        "CIK Number",
        "Ticker Symbol",
        "Options Volume",
        "Filing Date",
        "Exhibit 99.1 URL",
        "Filing Accession Number",
        "Claude Analysis"
    ]

    try:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in data:
                # Sanitize data to prevent CSV injection or formatting issues
                writer.writerow({
                    "Company Name": str(row.get("company_name", "")).replace('\n', ' ').replace('\r', ''),
                    "CIK Number": str(row.get("cik", "")).strip(),
                    "Ticker Symbol": str(row.get("ticker", "")).strip().upper(),
                    "Options Volume": int(row.get("options_volume", 0)),
                    "Filing Date": str(row.get("filing_date", "")).strip(),
                    "Exhibit 99.1 URL": str(row.get("exhibit_url", "")).strip(),
                    "Filing Accession Number": str(row.get("accession", "")).strip(),
                    "Claude Analysis": str(row.get("claude_analysis", "Not analyzed")).replace('\n', ' ').replace('\r', '')
                })

        print(f"\n✓ Successfully wrote {len(data)} records to {filename}")

    except Exception as e:
        print(f"\n✗ Error writing CSV file: {e}")
        import traceback
        traceback.print_exc()
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
        # Get ticker symbol
        ticker = get_ticker_from_cik(filing['cik'])

        # If options filtering is disabled (MIN_OPTIONS_VOLUME = 0), skip ticker requirement
        if MIN_OPTIONS_VOLUME == 0:
            # No filtering - include all filings with Exhibit 99.1
            options_volume = 0
            if ticker:
                # Try to get options volume if ticker available (for informational purposes)
                options_volume = get_options_volume(ticker)

            # Analyze with Claude if enabled
            analysis = "Not analyzed"
            if ENABLE_CLAUDE_ANALYSIS and ANTHROPIC_API_KEY:
                analysis = analyze_exhibit_with_claude(exhibit_url, filing['company_name'])

            if ticker:
                print(f"  [{idx}/{total}] ✓ {ticker} - {company_name_short} (Options Vol: {options_volume:,})")
            else:
                ticker = "N/A"
                print(f"  [{idx}/{total}] ✓ [No Ticker] - {company_name_short}")

            return {
                "company_name": filing['company_name'],
                "cik": filing['cik'],
                "ticker": ticker,
                "filing_date": parse_date(filing['filing_date']),
                "exhibit_url": exhibit_url,
                "accession": filing['accession'],
                "options_volume": options_volume,
                "claude_analysis": analysis
            }
        else:
            # Options filtering is enabled - ticker is required
            if not ticker:
                # Skip if no ticker found (can't check options volume)
                if idx % 20 == 0:
                    print(f"  [{idx}/{total}] ✗ {company_name_short} (no ticker)")
                return None

            # Get options volume
            options_volume = get_options_volume(ticker)

            # Filter by minimum options volume
            if options_volume >= MIN_OPTIONS_VOLUME:
                # Analyze with Claude if enabled
                analysis = "Not analyzed"
                if ENABLE_CLAUDE_ANALYSIS and ANTHROPIC_API_KEY:
                    analysis = analyze_exhibit_with_claude(exhibit_url, filing['company_name'])

                print(f"  [{idx}/{total}] ✓ {ticker} - {company_name_short} (Options Vol: {options_volume:,})")

                return {
                    "company_name": filing['company_name'],
                    "cik": filing['cik'],
                    "ticker": ticker,
                    "filing_date": parse_date(filing['filing_date']),
                    "exhibit_url": exhibit_url,
                    "accession": filing['accession'],
                    "options_volume": options_volume,
                    "claude_analysis": analysis
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

    # Warn if MAX_WORKERS is too high (could violate SEC rate limits)
    if MAX_WORKERS > 10:
        print(f"⚠️  WARNING: MAX_WORKERS={MAX_WORKERS} may exceed SEC rate limits")
        print(f"   Recommended: MAX_WORKERS <= 8 for reliable operation")
        print()

    # Load ticker cache at startup (one-time operation)
    load_ticker_cache()
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
    results_lock = threading.Lock()  # Thread-safe access to results list
    processed_count = 0
    count_lock = threading.Lock()  # Thread-safe counter

    # Use ThreadPoolExecutor for parallel processing
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all tasks
        future_to_filing = {
            executor.submit(process_single_filing, filing, idx, len(filings)): filing
            for idx, filing in enumerate(filings, 1)
        }

        # Collect results as they complete
        for future in as_completed(future_to_filing):
            with count_lock:
                processed_count += 1
                current_count = processed_count
                current_results = len(results)

            try:
                result = future.result()
                if result:
                    with results_lock:
                        results.append(result)
            except Exception as e:
                # Silently skip errors in individual filings
                pass

            # Print progress update every 50 filings
            if current_count % 50 == 0:
                with results_lock:
                    print(f"  Progress: {current_count}/{len(filings)} filings processed, {len(results)} with Exhibit 99.1")

    # Step 3: Write results to CSV
    print(f"\n{'=' * 70}")
    print(f"FILTERING SUMMARY:")
    print(f"  Total 8-K filings: {len(filings)}")

    if MIN_OPTIONS_VOLUME == 0:
        print(f"  Filings with Exhibit 99.1 (no filtering): {len(results)}")
    else:
        print(f"  Filings with Exhibit 99.1 and options volume >= {MIN_OPTIONS_VOLUME:,}: {len(results)}")

    if len(filings) > 0:
        print(f"  Success rate: {len(results)/len(filings)*100:.1f}%")
    else:
        print(f"  Success rate: N/A")

    if results:
        # Sort results by options volume (highest first)
        results.sort(key=lambda x: x.get('options_volume', 0), reverse=True)

        write_to_csv(results, OUTPUT_FILENAME)

        if MIN_OPTIONS_VOLUME == 0:
            print(f"\nTop 5 results (no filtering applied):")
        else:
            print(f"\nTop 5 results by options volume:")

        for i, result in enumerate(results[:5], 1):
            ticker_display = result.get('ticker', 'N/A')
            options_vol = result.get('options_volume', 0)

            print(f"\n  {i}. {ticker_display} - {result['company_name']}")
            if MIN_OPTIONS_VOLUME > 0 or options_vol > 0:
                print(f"     Options Volume: {options_vol:,}")
            print(f"     Filing Date: {result['filing_date']}")
            print(f"     URL: {result['exhibit_url'][:60]}...")
    else:
        if MIN_OPTIONS_VOLUME == 0:
            print(f"\nNo filings found with Exhibit 99.1.")
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