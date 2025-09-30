# SEC EDGAR 8-K Exhibit 99.1 Extractor

## Overview
This Python script automatically searches all public company 8-K filings from the last 30 days, identifies those containing Exhibit 99.1 (typically press releases), filters by options trading volume (≥10,000), and extracts key information into a CSV file.

## Features
- ✓ **Options Volume Filter** - Automatically excludes stocks with options volume < 10,000
- ✓ **Parallel Processing** - Uses multi-threading to process up to 8 filings simultaneously
- ✓ **Comprehensive Coverage** - Searches SEC daily index files for complete 8-K filing data
- ✓ **SEC Compliant** - Thread-safe rate limiting and proper User-Agent headers
- ✓ **Ticker Resolution** - Automatically looks up ticker symbols for each company
- ✓ **Configurable Date Range** - Search 7-90+ days of filings
- ✓ **Smart Exhibit Detection** - Multiple regex patterns to find Exhibit 99.1 variants
- ✓ **CSV Export** - Clean output with company details, options volume, dates, and URLs
- ✓ **Progress Tracking** - Real-time updates showing processing status
- ✓ **Robust Error Handling** - Graceful failures and automatic fallback methods

## Requirements
- Python 3.8 or higher
- `requests` library (HTTP requests to SEC)
- `yfinance` library (options volume data)

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Update User-Agent (REQUIRED):**
   Edit `sec_exhibit_extractor.py` line 19 to include your contact information:
   ```python
   USER_AGENT = "Mozilla/5.0 (Your Name; your.email@example.com)"
   ```
   The SEC requires this for compliance with their fair access policy.

## Usage

### Basic Usage
```bash
python3 sec_exhibit_extractor.py
```

### Configuration
Edit the configuration section at the top of `sec_exhibit_extractor.py`:

```python
DAYS_BACK = 30  # How many days to look back (default: 30)
OUTPUT_FILENAME = "exhibit_99_1_filings.csv"  # Output file name
REQUEST_DELAY = 0.11  # Delay between requests (stay under 10/sec)
MAX_WORKERS = 8  # Number of parallel threads (default: 8)
MIN_OPTIONS_VOLUME = 10000  # Minimum daily options volume (default: 10,000)
```

### Testing with Smaller Date Range
For initial testing, modify `DAYS_BACK` to a smaller value:
```python
DAYS_BACK = 7  # Test with just 7 days of data
```

## Output Format

The script generates a CSV file with the following columns:

| Column | Description | Example |
|--------|-------------|---------|
| Company Name | Full legal name of the company | Apple Inc. |
| CIK Number | SEC Central Index Key | 0000320193 |
| Ticker Symbol | Stock ticker symbol | AAPL |
| Options Volume | Daily options trading volume | 125,430 |
| Filing Date | Date filed in YYYY-MM-DD format | 2024-11-15 |
| Exhibit 99.1 URL | Direct link to the document | https://www.sec.gov/... |
| Filing Accession Number | Unique filing identifier | 0000320193-24-000123 |

### Sample Output
```csv
Company Name,CIK Number,Ticker Symbol,Options Volume,Filing Date,Exhibit 99.1 URL,Filing Accession Number
Apple Inc.,0000320193,AAPL,125430,2024-11-15,https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/ex99-1.htm,0000320193-24-000123
```

## Expected Runtime

With **parallel processing** (8 workers) and **options volume filtering**:
- **7 days:** ~2-4 minutes (approximately 50-150 filings, ~10-40 after filtering)
- **30 days:** ~5-12 minutes (approximately 200-800 filings, ~40-150 after filtering)
- **60 days:** ~12-25 minutes (approximately 500-1,500 filings, ~100-300 after filtering)

Runtime varies based on:
- Number of 8-K filings in the date range (weekdays only)
- Options volume lookups (adds ~1-2 seconds per filing with Exhibit 99.1)
- Network speed and SEC server response times
- Yahoo Finance API availability for options data
- Time of day (slower during market hours: 9:30 AM - 4:00 PM ET)
- Number of parallel workers (configurable via MAX_WORKERS)

**Note:** The options volume filter significantly reduces the final result set, focusing only on liquid, actively traded stocks.

## Performance Optimization

The script uses **parallel processing** to significantly speed up extraction:

1. **Daily Index Downloads:** Fetches SEC daily index files with 3 parallel workers
2. **Filing Processing:** Analyzes up to 8 filings simultaneously (configurable via `MAX_WORKERS`)
3. **Thread-Safe Rate Limiting:** Ensures SEC compliance even with parallel requests
4. **Efficient Pattern Matching:** Multiple optimized regex patterns for Exhibit 99.1 detection

### Tuning Performance

- **Increase throughput:** Set `MAX_WORKERS = 12` (monitor rate limiting)
- **Conservative mode:** Set `MAX_WORKERS = 4` for slower connections
- **Maximum coverage:** Set `DAYS_BACK = 60` or `90` for more filings
- **Adjust options filter:** Lower `MIN_OPTIONS_VOLUME = 5000` for more results
- **Disable filtering:** Set `MIN_OPTIONS_VOLUME = 0` to include all stocks

## Limitations

1. **Rate Limiting:** Thread-safe enforcement of SEC's <10 requests/second limit. Do not modify `REQUEST_DELAY` below 0.1 seconds.

2. **Exhibit Detection:** Multiple regex patterns cover most formats, but some non-standard Exhibit 99.1 references may be missed.

3. **Options Volume Data:** Uses Yahoo Finance API via yfinance. Some tickers may have limited or unavailable options data.

4. **Ticker Resolution Required:** Stocks without valid ticker symbols are automatically excluded (can't check options volume).

5. **Options Volume Calculation:** Based on the nearest expiration date's total call + put volume. May not reflect true average daily volume.

6. **Document Types:** Returns direct URLs to Exhibit 99.1 in HTML, PDF, or TXT format.

7. **Weekend/Holiday Coverage:** Daily index files only available for business days (Mon-Fri, excluding SEC holidays).

8. **Processing Time:** Options volume lookups add ~1-2 seconds per filing, significantly increasing total runtime.

## Troubleshooting

### Error: "403 Forbidden"
- **Cause:** Invalid or missing User-Agent header
- **Solution:** Update the `USER_AGENT` variable with your contact information

### Error: "No filings found"
- **Cause:** Date range may be too narrow or SEC API issues
- **Solution:** Try expanding `DAYS_BACK` or run during off-peak hours

### Slow Performance
- **Cause:** High volume of filings or peak SEC server usage
- **Solution:** Run during evenings/weekends, or process in smaller date ranges

### Missing Exhibit 99.1
- **Cause:** Not all 8-Ks contain Exhibit 99.1; some use different exhibit numbers
- **Solution:** This is expected behavior. The script only reports filings that contain Exhibit 99.1

### No Results After Filtering
- **Cause:** Options volume filter (MIN_OPTIONS_VOLUME) is excluding all stocks
- **Solution:** Lower `MIN_OPTIONS_VOLUME` to 5,000 or 0 to include more stocks

### Yahoo Finance API Errors
- **Cause:** Rate limiting or temporary unavailability of options data
- **Solution:** Retry later or reduce `MAX_WORKERS` to avoid overwhelming the API

## Best Practices

1. **Initial Testing:** Start with `DAYS_BACK = 7` to verify everything works
2. **Off-Peak Hours:** Run during evenings/weekends for faster results
3. **User-Agent Compliance:** Always include valid contact information
4. **Backup Data:** Consider running periodically and archiving CSV outputs
5. **Rate Limiting:** Never modify request delays to be faster than 0.1 seconds

## SEC EDGAR Resources

- [SEC EDGAR Search](https://www.sec.gov/edgar/searchedgar/companysearch.html)
- [SEC API Documentation](https://www.sec.gov/edgar/sec-api-documentation)
- [8-K Filing Overview](https://www.sec.gov/fast-answers/answersform8khtm.html)
- [Fair Access Policy](https://www.sec.gov/os/accessing-edgar-data)

## License
This script is provided as-is for educational and research purposes. Users are responsible for compliance with SEC guidelines and applicable laws.

## Support
For issues or questions, refer to the SEC EDGAR documentation or consult with a qualified professional.