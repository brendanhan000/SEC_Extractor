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
DAYS_BACK = 30  # How many days to look back for 8-K filings
OUTPUT_FILENAME = "exhibit_99_1_filings.csv"
USER_AGENT = "Mozilla/5.0 (SEC Exhibit Extractor; brendanwbhan@gmail.com)"  # REQUIRED by SEC
REQUEST_DELAY = 0.11  # 0.11 seconds = ~9 requests/second (under SEC limit)
MAX_RETRIES = 3
MAX_WORKERS = 8  # Number of parallel threads for processing filings

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
    """Enforce rate limiting to comply with SEC guidelines"""
    time.sleep(REQUEST_DELAY)

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
    Fetch recent 8-K filings from SEC EDGAR using the RSS feed

    Args:
        days_back: Number of days to look back for filings

    Returns:
        List of dictionaries containing filing information
    """
    filings = []
    cutoff_date = datetime.now() - timedelta(days=days_back)

    print(f"Searching for 8-K filings from {cutoff_date.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}...")

    # Use SEC's RSS feed for recent filings
    # The RSS feed provides the most recent filings across all companies
    url = f"{SEC_BASE_URL}/cgi-bin/browse-edgar"

    params = {
        "action": "getcurrent",
        "type": "8-K",
        "count": "100",  # Max per request
        "output": "atom"
    }

    try:
        rate_limit()
        response = requests.get(url, params=params, headers=get_sec_headers(), timeout=30)
        response.raise_for_status()

        content = response.text

        # Parse the Atom feed for filing entries
        entries = re.findall(r'<entry>(.*?)</entry>', content, re.DOTALL)

        print(f"  Found {len(entries)} recent 8-K filings")

        for entry in entries:
            filing_data = parse_atom_entry(entry)
            if filing_data:
                # Check if filing is within our date range
                try:
                    filing_date = datetime.strptime(filing_data['filing_date'], '%Y-%m-%d')
                    if filing_date >= cutoff_date:
                        filings.append(filing_data)
                except:
                    # If date parsing fails, include it anyway
                    filings.append(filing_data)

        print(f"Total 8-K filings in date range: {len(filings)}")

    except Exception as e:
        print(f"  Error fetching filings: {e}")
        print(f"  Trying alternative method...")

        # Fallback: Try to get recent filings by checking the daily index files
        filings = get_filings_from_daily_index(days_back)

    return filings

def get_filings_from_daily_index(days_back: int = 30) -> List[Dict]:
    """
    Fetch 8-K filings from SEC's daily index files

    Args:
        days_back: Number of days to look back

    Returns:
        List of filing dictionaries
    """
    filings = []
    print("  Using daily index files method...")

    # Iterate through each day in the range
    for day_offset in range(days_back):
        date = datetime.now() - timedelta(days=day_offset)

        # Skip weekends
        if date.weekday() >= 5:
            continue

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

                            filings.append({
                                "company_name": company_name,
                                "cik": cik,
                                "filing_date": filing_date,
                                "accession": accession_no_dashes,
                                "filing_url": filing_url
                            })

                if day_offset % 5 == 0:
                    print(f"    Processed {day_offset + 1}/{days_back} days, found {len(filings)} filings so far...")

        except Exception as e:
            # It's normal for some dates to not have index files (holidays, etc.)
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
                    "Filing Date": row.get("filing_date", ""),
                    "Exhibit 99.1 URL": row.get("exhibit_url", ""),
                    "Filing Accession Number": row.get("accession", "")
                })

        print(f"\n✓ Successfully wrote {len(data)} records to {filename}")

    except Exception as e:
        print(f"\n✗ Error writing CSV file: {e}")
        sys.exit(1)

# ============================================================================
# MAIN WORKFLOW
# ============================================================================

def main():
    """Main execution function"""
    print("=" * 70)
    print("SEC EDGAR 8-K Exhibit 99.1 Extractor")
    print("=" * 70)
    print()

    # Step 1: Fetch recent 8-K filings
    filings = get_recent_8k_filings(days_back=DAYS_BACK)

    if not filings:
        print("\nNo 8-K filings found in the specified date range.")
        sys.exit(0)

    # Step 2: Process each filing to find Exhibit 99.1
    print(f"\nProcessing {len(filings)} filings to locate Exhibit 99.1...")
    results = []

    for idx, filing in enumerate(filings, 1):
        print(f"  [{idx}/{len(filings)}] Processing {filing['company_name'][:50]}...", end="")

        # Find Exhibit 99.1
        exhibit_url = find_exhibit_99_1(
            filing['cik'],
            filing['accession'],
            filing['filing_url']
        )

        if exhibit_url:
            print(" ✓ Found")

            # Get ticker (optional, may be slow)
            # ticker = get_ticker_from_cik(filing['cik'])
            ticker = ""  # Comment out above line and uncomment this to skip ticker lookup

            results.append({
                "company_name": filing['company_name'],
                "cik": filing['cik'],
                "ticker": ticker,
                "filing_date": parse_date(filing['filing_date']),
                "exhibit_url": exhibit_url,
                "accession": filing['accession']
            })
        else:
            print(" ✗ Not found")

    # Step 3: Write results to CSV
    print(f"\nFound Exhibit 99.1 in {len(results)} out of {len(filings)} filings")

    if results:
        write_to_csv(results, OUTPUT_FILENAME)
        print(f"\nSample output:")
        print(f"  Company: {results[0]['company_name']}")
        print(f"  CIK: {results[0]['cik']}")
        print(f"  Date: {results[0]['filing_date']}")
        print(f"  URL: {results[0]['exhibit_url'][:70]}...")
    else:
        print("\nNo filings with Exhibit 99.1 found.")

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