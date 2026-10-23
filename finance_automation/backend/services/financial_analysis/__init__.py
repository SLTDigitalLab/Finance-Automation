"""
Financial Analysis Report (use case 28): quarterly P&L analysis built from the
monthly detail trial balances and the GL code mapping.

  periods.py         fiscal periods and quarters (financial year = Jan–Dec)
  tb_reader.py       reads a "Detail TB_<Mon> <YY>.xlsx" export into account balances
  mapping_reader.py  reads the "6.PL-EBITDA" GL code mapping into P&L line account ranges
  pl_engine.py       builds the P&L per period and the quarter / YTD comparisons
  tb_store.py        keeps each period's account balances in the database
  commentary.py      rule-based narrative for the report
  charts.py          monthly revenue / opex trend charts (PNG)
  report_generator.py  fills Finance's Word template with the analysis
"""
