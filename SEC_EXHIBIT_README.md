# SEC EDGAR 8-K Exhibit 99.1 Extractor

## Overview
This Python script automatically searches all public company 8-K filings from the last 30 days, identifies those containing Exhibit 99.1 (typically press releases), and extracts key information into a CSV file.

## Features
- ✓ Complies with SEC EDGAR API requirements (rate limiting, User-Agent headers)
- ✓ Searches recent 8-K filings with configurable date range
- ✓ Identifies and extracts Exhibit 99.1 document URLs
- ✓ Exports results to CSV with company details
- ✓ Progress indicators for long-running operations
- ✓ Robust error handling and retry logic

## Requirements
- Python 3.8 or higher
- `requests` library (see requirements.txt)

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
| Ticker Symbol | Stock ticker (optional) | AAPL |
| Filing Date | Date filed in YYYY-MM-DD format | 2024-11-15 |
| Exhibit 99.1 URL | Direct link to the document | https://www.sec.gov/... |
| Filing Accession Number | Unique filing identifier | 0000320193-24-000123 |

### Sample Output
```csv
Company Name,CIK Number,Ticker Symbol,Filing Date,Exhibit 99.1 URL,Filing Accession Number
Apple Inc.,0000320193,AAPL,2024-11-15,https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/ex99-1.htm,0000320193-24-000123
```

## Expected Runtime

- **7 days:** ~2-5 minutes (approximately 50-150 filings)
- **30 days:** ~10-20 minutes (approximately 200-600 filings)

Runtime varies based on:
- Number of 8-K filings in the date range
- Network speed and SEC server response times
- Time of day (slower during market hours)

## Limitations

1. **Rate Limiting:** The script enforces SEC's <10 requests/second limit. Do not modify `REQUEST_DELAY` below 0.1 seconds.

2. **Exhibit Detection:** Some companies may format Exhibit 99.1 references differently. The script includes multiple detection patterns but may miss non-standard formats.

3. **Ticker Symbols:** Ticker lookup is disabled by default for performance. To enable, uncomment line 373:
   ```python
   ticker = get_ticker_from_cik(filing['cik'])
   ```

4. **Document Types:** The script locates Exhibit 99.1 URLs, which may be in HTML, PDF, or TXT format.

5. **Historical Limits:** The SEC EDGAR search API may have practical limits on how far back you can search efficiently.

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