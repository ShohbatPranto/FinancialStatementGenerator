# financial_statements_official_income.py
"""
Financial Statements Web App - Official Detailed Income Statement + Depreciation Schedule

Features:
- Manual entry page (separate) and CSV uploads merged
- Income Statement strictly uses Account field and groups into:
    - Revenue (Sales, Service Income)
    - COGS
    - Operating Expenses (Rent, Salaries, Depreciation)
    - Other Income/Expense
    - Income Before Tax, Income Tax (manual), Net Income
- Depreciation appears under operating expenses and on a separate Depreciation page
- Balance sheet (top-down), Cash flow (indirect)
- Generate button on Home; PDF (multi-page) and Excel output
"""

from flask import Flask, request, render_template_string, send_file, redirect, url_for, flash
import pandas as pd
import io, os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "dev-secret"
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------- Helpers ----------------
def safe_float(x):
    try:
        return float(x)
    except Exception:
        return 0.0

def ensure_df_columns(df, cols):
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols].copy()

# ---------------- Manual storage ----------------
manual_data = {
    'transactions': pd.DataFrame(columns=['Date','Account','Category','Amount','Type']),
    'balance_begin': pd.DataFrame(columns=['Account','Amount','Type']),
    'balance_end': pd.DataFrame(columns=['Account','Amount','Type']),
    'accruals': pd.DataFrame(columns=['Account','Amount','Affects','BalanceType']),
    'depreciation': pd.DataFrame(columns=['Asset','Cost','Salvage','LifeYears','Depreciation Expense']),
    'investing': pd.DataFrame(columns=['Account','Amount']),
    'financing': pd.DataFrame(columns=['Account','Amount']),
    'retained_begin': 0.0,
    'income_tax': 0.0  # manual tax amount
}

# ---------------- Classification keywords (simple) ----------------
# For this version we strictly follow Account names and map them to sections.
REVENUE_ACCOUNTS = {'Sales', 'Service Income'}
COGS_ACCOUNTS = {'COGS'}
OPERATING_ACCOUNTS = {'Rent', 'Salaries'}  # depreciation added separately
# Everything else of Type=='Expense' that isn't COGS goes to Operating by default
# Other income/expense will be anything Type=='Revenue' or 'Expense' not in above groups and flagged later.

# ---------------- Accounting computations ----------------

def compute_income_statement(trans_df, accruals_df, depreciation_df, income_tax_manual):
    trans_df = ensure_df_columns(trans_df, ['Date','Account','Category','Amount','Type'])
    accruals_df = ensure_df_columns(accruals_df, ['Account','Amount','Affects','BalanceType'])
    depreciation_df = ensure_df_columns(depreciation_df, ['Asset','Cost','Salvage','LifeYears','Depreciation Expense'])

    # Build line-by-line totals strictly following Account names
    # Revenue lines: accounts in REVENUE_ACCOUNTS or Type=='Revenue'
    # Expense lines: accounts from transactions where Type=='Expense'
    # We'll compute:
    # - revenue_lines: dict Account -> total
    # - cogs_lines: dict Account -> total (COGS_ACCOUNTS)
    # - operating_lines: dict Account -> total (OPERATING_ACCOUNTS + other expense accounts except COGS)
    # - other_lines: dict for other income/expense (if any)
    revenue_lines = {}
    cogs_lines = {}
    operating_lines = {}
    other_income_lines = {}
    other_expense_lines = {}

    # Sum transactions by Account and Type
    for _, r in trans_df.iterrows():
        acct = r.get('Account') or 'Unknown'
        amt = safe_float(r.get('Amount', 0.0))
        typ = (r.get('Type') or '').strip()
        # treat revenue accounts
        if acct in REVENUE_ACCOUNTS or typ == 'Revenue':
            revenue_lines[acct] = revenue_lines.get(acct, 0.0) + amt
        elif acct in COGS_ACCOUNTS or typ == 'Expense' and acct in COGS_ACCOUNTS:
            cogs_lines[acct] = cogs_lines.get(acct, 0.0) + amt
        elif typ == 'Expense':
            # If acct is explicitly in OPERATING_ACCOUNTS, place there
            if acct in OPERATING_ACCOUNTS:
                operating_lines[acct] = operating_lines.get(acct, 0.0) + amt
            else:
                # default: operating expense (except COGS handled above)
                operating_lines[acct] = operating_lines.get(acct, 0.0) + amt
        else:
            # fallback: treat as other income/expense based on Type
            if typ == 'Revenue':
                other_income_lines[acct] = other_income_lines.get(acct, 0.0) + amt
            else:
                # unknown type default to other expense
                other_expense_lines[acct] = other_expense_lines.get(acct, 0.0) + amt

    # Accruals that affect income (Affects column)
    if accruals_df is not None and not accruals_df.empty:
        for _, r in accruals_df.iterrows():
            affects = (r.get('Affects') or '').strip()
            acct = r.get('Account') or 'Accrual'
            amt = safe_float(r.get('Amount',0.0))
            if affects == 'Revenue':
                revenue_lines[acct] = revenue_lines.get(acct, 0.0) + amt
            elif affects == 'Expense':
                operating_lines[acct] = operating_lines.get(acct, 0.0) + amt
            # if 'Balance' it will be applied in balance sheet

    # Depreciation: treated as operating expense in income statement
    depr_total = 0.0
    if depreciation_df is not None and not depreciation_df.empty:
        # sum 'Depreciation Expense' column
        if 'Depreciation Expense' in depreciation_df.columns:
            depr_total = depreciation_df['Depreciation Expense'].apply(safe_float).sum()
        else:
            # maybe depreciation rows only have cost/life; compute none
            depr_total = 0.0
    # Add depreciation under operating lines with specific label
    if depr_total != 0.0:
        operating_lines['Depreciation Expense'] = operating_lines.get('Depreciation Expense', 0.0) + depr_total

    # Totals
    total_revenue = sum(revenue_lines.values())
    total_cogs = sum(cogs_lines.values())
    gross_profit = total_revenue - total_cogs
    total_operating = sum(operating_lines.values())
    operating_income = gross_profit - total_operating
    net_other_income = sum(other_income_lines.values()) - sum(other_expense_lines.values())
    income_before_tax = operating_income + net_other_income
    # Income tax: manual input (amount)
    income_tax = safe_float(income_tax_manual)
    net_income = income_before_tax - income_tax

    # Return structure with line-level details
    return {
        'revenue_lines': revenue_lines,
        'cogs_lines': cogs_lines,
        'operating_lines': operating_lines,
        'other_income_lines': other_income_lines,
        'other_expense_lines': other_expense_lines,
        'totals': {
            'total_revenue': total_revenue,
            'total_cogs': total_cogs,
            'gross_profit': gross_profit,
            'total_operating': total_operating,
            'operating_income': operating_income,
            'net_other_income': net_other_income,
            'income_before_tax': income_before_tax,
            'income_tax': income_tax,
            'net_income': net_income,
            'depreciation_total': depr_total
        }
    }

# Balance sheet, depreciation journal, and cash flow (reuse previously working logic)

def compute_balance_sheet(balance_end_df, accruals_df, depreciation_df, retained_begin, net_income):
    balance_end_df = ensure_df_columns(balance_end_df, ['Account','Amount','Type'])
    accruals_df = ensure_df_columns(accruals_df, ['Account','Amount','Affects','BalanceType'])
    depreciation_df = ensure_df_columns(depreciation_df, ['Asset','Cost','Salvage','LifeYears','Depreciation Expense'])

    assets = balance_end_df.loc[balance_end_df['Type']=='Asset',['Account','Amount']].copy()
    liabilities = balance_end_df.loc[balance_end_df['Type']=='Liability',['Account','Amount']].copy()
    equity = balance_end_df.loc[balance_end_df['Type']=='Equity',['Account','Amount']].copy()

    if accruals_df is not None and not accruals_df.empty:
        for _, r in accruals_df.iterrows():
            if r.get('Affects') == 'Balance':
                acct = r.get('Account'); amt = safe_float(r.get('Amount',0.0)); btype = r.get('BalanceType','Asset')
                if btype == 'Asset':
                    if acct in assets['Account'].values:
                        assets.loc[assets['Account']==acct,'Amount'] += amt
                    else:
                        assets.loc[len(assets)] = [acct, amt]
                elif btype == 'Liability':
                    if acct in liabilities['Account'].values:
                        liabilities.loc[liabilities['Account']==acct,'Amount'] += amt
                    else:
                        liabilities.loc[len(liabilities)] = [acct, amt]
                elif btype == 'Equity':
                    if acct in equity['Account'].values:
                        equity.loc[equity['Account']==acct,'Amount'] += amt
                    else:
                        equity.loc[len(equity)] = [acct, amt]

    accumulated = depreciation_df['Depreciation Expense'].apply(safe_float).sum() if not depreciation_df.empty else 0.0
    if accumulated != 0.0:
        assets.loc[len(assets)] = ['Accumulated Depreciation', -accumulated]

    # simple classification heuristics for top-down presentation
    def is_current_asset(name):
        n = (name or '').lower()
        return any(k in n for k in ['cash','receivable','inventory','prepaid','short-term','short term'])
    def is_noncurrent_asset(name):
        n = (name or '').lower()
        return any(k in n for k in ['property','plant','equipment','ppe','building','machinery','long-term','intangible','goodwill'])
    def is_current_liability(name):
        n = (name or '').lower()
        return any(k in n for k in ['payable','accrued','current portion','tax payable','short-term','short term'])
    def is_noncurrent_liability(name):
        n = (name or '').lower()
        return any(k in n for k in ['loan','bond','mortgage','long-term','long term'])

    assets['Class'] = assets['Account'].apply(lambda a: 'Current Asset' if is_current_asset(a) else ('Non-current Asset' if is_noncurrent_asset(a) else 'Other Asset'))
    liabilities['Class'] = liabilities['Account'].apply(lambda a: 'Current Liability' if is_current_liability(a) else ('Non-current Liability' if is_noncurrent_liability(a) else 'Other Liability'))

    current_assets = assets[assets['Class']=='Current Asset'][['Account','Amount']].copy()
    noncurrent_assets = assets[assets['Class']=='Non-current Asset'][['Account','Amount']].copy()
    other_assets = assets[assets['Class']=='Other Asset'][['Account','Amount']].copy()

    current_liabilities = liabilities[liabilities['Class']=='Current Liability'][['Account','Amount']].copy()
    noncurrent_liabilities = liabilities[liabilities['Class']=='Non-current Liability'][['Account','Amount']].copy()
    other_liabilities = liabilities[liabilities['Class']=='Other Liability'][['Account','Amount']].copy()

    total_assets = assets['Amount'].sum() if not assets.empty else 0.0
    total_liabilities = liabilities['Amount'].sum() if not liabilities.empty else 0.0

    ending_retained = retained_begin + net_income
    if 'Retained Earnings' in equity['Account'].values:
        equity.loc[equity['Account']=='Retained Earnings','Amount'] = ending_retained
    else:
        equity.loc[len(equity)] = ['Retained Earnings', ending_retained]

    total_equity = equity['Amount'].sum() if not equity.empty else 0.0

    return {
        'assets': assets.reset_index(drop=True),
        'current_assets': current_assets.reset_index(drop=True),
        'noncurrent_assets': noncurrent_assets.reset_index(drop=True),
        'other_assets': other_assets.reset_index(drop=True),
        'liabilities': liabilities.reset_index(drop=True),
        'current_liabilities': current_liabilities.reset_index(drop=True),
        'noncurrent_liabilities': noncurrent_liabilities.reset_index(drop=True),
        'other_liabilities': other_liabilities.reset_index(drop=True),
        'equity': equity.reset_index(drop=True),
        'total_assets': total_assets,
        'total_liabilities': total_liabilities,
        'total_equity': total_equity,
        'accumulated_depreciation': accumulated,
        'ending_retained': ending_retained
    }

def generate_depreciation_journal(depr_df, start_year=None):
    depr_df = ensure_df_columns(depr_df, ['Asset','Cost','Salvage','LifeYears','Depreciation Expense'])
    js = []
    if depr_df.empty:
        return js
    base = start_year if start_year is not None else datetime.now().year
    for _, r in depr_df.iterrows():
        asset = r.get('Asset') or 'Asset'
        depr = safe_float(r.get('Depreciation Expense', 0.0))
        life = int(max(1, safe_float(r.get('LifeYears',1))))
        for i in range(life):
            js.append({
                'Period': base + i,
                'Debit Account': 'Depreciation Expense',
                'Debit Amount': depr,
                'Credit Account': 'Accumulated Depreciation',
                'Credit Amount': depr,
                'Narration': f"Straight-line depreciation for {asset} - year {base + i}"
            })
    return js

def cash_flow_statement_indirect(net_income, depreciation_total, bal_begin_df, bal_end_df, investing_df, financing_df):
    bal_begin_df = ensure_df_columns(bal_begin_df, ['Account','Amount','Type'])
    bal_end_df = ensure_df_columns(bal_end_df, ['Account','Amount','Type'])
    investing_df = ensure_df_columns(investing_df, ['Account','Amount'])
    financing_df = ensure_df_columns(financing_df, ['Account','Amount'])

    ops = net_income + depreciation_total
    working = []

    beg = bal_begin_df.set_index('Account')['Amount'] if not bal_begin_df.empty else pd.Series(dtype='float64')
    end = bal_end_df.set_index('Account')['Amount'] if not bal_end_df.empty else pd.Series(dtype='float64')
    all_accounts = sorted(set(beg.index.tolist() + end.index.tolist()))
    for acct in all_accounts:
        b = safe_float(beg.get(acct,0.0))
        e = safe_float(end.get(acct,0.0))
        ch = e - b
        low = acct.lower() if isinstance(acct, str) else ''
        if 'receivable' in low or 'inventory' in low or 'prepaid' in low:
            ops -= ch
            working.append((acct, ch, 'Change in current asset'))
        elif 'payable' in low or 'accrued' in low or 'tax payable' in low:
            ops += ch
            working.append((acct, ch, 'Change in current liability'))

    investing_total = investing_df['Amount'].sum() if not investing_df.empty else 0.0
    financing_total = financing_df['Amount'].sum() if not financing_df.empty else 0.0

    # detect cash balances
    beg_cash = 0.0
    end_cash = 0.0
    if not bal_begin_df.empty:
        for _, r in bal_begin_df.iterrows():
            if 'cash' in (r.get('Account') or '').lower():
                beg_cash = safe_float(r.get('Amount',0.0)); break
    if not bal_end_df.empty:
        for _, r in bal_end_df.iterrows():
            if 'cash' in (r.get('Account') or '').lower():
                end_cash = safe_float(r.get('Amount',0.0)); break

    net_change = ops + investing_total + financing_total
    return {
        'cash_from_operations': ops,
        'working_capital': working,
        'cash_from_investing': investing_total,
        'cash_from_financing': financing_total,
        'net_change': net_change,
        'beginning_cash': beg_cash,
        'ending_cash': end_cash
    }

# ---------------- PDF builder (Income Statement detailed + separate Depreciation page) ----------------

def build_pdf(buffer, company, period, income_obj, bs_obj, cf_obj, depreciation_df, journals):
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=26,leftMargin=26, topMargin=26,bottomMargin=26)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('title', parent=styles['Title'], alignment=1, fontSize=16)
    hdr = ParagraphStyle('hdr', parent=styles['Heading2'], alignment=0, fontSize=12)
    normal = styles['Normal']

    Story = []
    # Cover header
    Story.append(Paragraph(company, title_style))
    Story.append(Paragraph(f"Income Statement - Period: {period}", normal))
    Story.append(Spacer(1,10))

    # --- Income Statement Page (detailed)
    Story.append(Paragraph("INCOME STATEMENT", hdr))
    rows = [['Line Item', 'Amount']]
    # Revenue lines (exact Accounts)
    rows.append(['REVENUE', ''])
    for acct, amt in income_obj['revenue_lines'].items():
        rows.append([f"  {acct}", f"{amt:,.2f}"])
    rows.append(['Total Revenue', f"{income_obj['totals']['total_revenue']:,.2f}"])
    rows.append(['', ''])

    # COGS
    rows.append(['COST OF GOODS SOLD', ''])
    for acct, amt in income_obj['cogs_lines'].items():
        rows.append([f"  {acct}", f"{amt:,.2f}"])
    rows.append(['Total COGS', f"{income_obj['totals']['total_cogs']:,.2f}"])
    rows.append(['', ''])
    # Gross Profit
    rows.append(['GROSS PROFIT', f"{income_obj['totals']['gross_profit']:,.2f}"])
    rows.append(['', ''])

    # Operating Expenses
    rows.append(['OPERATING EXPENSES', ''])
    # list operating expense accounts
    for acct, amt in income_obj['operating_lines'].items():
        rows.append([f"  {acct}", f"{amt:,.2f}"])
    rows.append(['Total Operating Expenses', f"{income_obj['totals']['total_operating']:,.2f}"])
    rows.append(['', ''])
    # Operating Income
    rows.append(['OPERATING INCOME', f"{income_obj['totals']['operating_income']:,.2f}"])
    rows.append(['', ''])

    # Other Income / Expenses
    rows.append(['OTHER INCOME / (EXPENSE)', ''])
    # other income
    for acct, amt in income_obj['other_income_lines'].items():
        rows.append([f"  {acct}", f"{amt:,.2f}"])
    for acct, amt in income_obj['other_expense_lines'].items():
        rows.append([f"  {acct}", f"{amt:,.2f}"])
    rows.append(['Net Other Income (Expense)', f"{income_obj['totals']['net_other_income']:,.2f}"])
    rows.append(['', ''])

    rows.append(['INCOME BEFORE TAX', f"{income_obj['totals']['income_before_tax']:,.2f}"])
    rows.append(['Income Tax Expense (manual)', f"{income_obj['totals']['income_tax']:,.2f}"])
    rows.append(['NET INCOME', f"{income_obj['totals']['net_income']:,.2f}"])

    table = Table(rows, colWidths=[380,120], hAlign='LEFT')
    table.setStyle(TableStyle([
        ('GRID',(0,0),(-1,-1),0.35,colors.grey),
        ('BACKGROUND',(0,0),(-1,0),colors.HexColor("#f0f0f0")),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
        ('ALIGN',(1,0),(-1,-1),'RIGHT'),
        ('LEFTPADDING',(0,0),(-1,-1),6),
        ('RIGHTPADDING',(0,0),(-1,-1),6)
    ]))
    Story.append(table)
    Story.append(PageBreak())

    # --- Balance Sheet Page
    Story.append(Paragraph("BALANCE SHEET (Top-down)", hdr))
    # Assets (top-down)
    a_rows = [['ASSETS','Amount']]
    if not bs_obj['current_assets'].empty:
        a_rows.append(['Current Assets',''])
        for _, r in bs_obj['current_assets'].iterrows():
            a_rows.append([f"  {r['Account']}", f"{safe_float(r['Amount']):,.2f}"])
        a_rows.append(['  Total Current Assets', f"{bs_obj['current_assets']['Amount'].sum():,.2f}"])
    if not bs_obj['noncurrent_assets'].empty:
        a_rows.append(['Non-current Assets',''])
        for _, r in bs_obj['noncurrent_assets'].iterrows():
            a_rows.append([f"  {r['Account']}", f"{safe_float(r['Amount']):,.2f}"])
        a_rows.append(['  Total Non-current Assets', f"{bs_obj['noncurrent_assets']['Amount'].sum():,.2f}"])
    if not bs_obj['other_assets'].empty:
        a_rows.append(['Other Assets',''])
        for _, r in bs_obj['other_assets'].iterrows():
            a_rows.append([f"  {r['Account']}", f"{safe_float(r['Amount']):,.2f}"])
    a_rows.append(['TOTAL ASSETS', f"{bs_obj['total_assets']:,.2f}"])
    at = Table(a_rows, colWidths=[380,120], hAlign='LEFT')
    at.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.35,colors.grey),('BACKGROUND',(0,0),(1,0),colors.HexColor("#f0f0f0")),('ALIGN',(1,0),(-1,-1),'RIGHT')]))
    Story.append(at)
    Story.append(Spacer(1,12))

    # Liabilities & Equity
    le_rows = [['LIABILITIES & EQUITY','Amount']]
    if not bs_obj['current_liabilities'].empty:
        le_rows.append(['Current Liabilities',''])
        for _, r in bs_obj['current_liabilities'].iterrows():
            le_rows.append([f"  {r['Account']}", f"{safe_float(r['Amount']):,.2f}"])
        le_rows.append(['  Total Current Liabilities', f"{bs_obj['current_liabilities']['Amount'].sum():,.2f}"])
    if not bs_obj['noncurrent_liabilities'].empty:
        le_rows.append(['Non-current Liabilities',''])
        for _, r in bs_obj['noncurrent_liabilities'].iterrows():
            le_rows.append([f"  {r['Account']}", f"{safe_float(r['Amount']):,.2f}"])
        le_rows.append(['  Total Non-current Liabilities', f"{bs_obj['noncurrent_liabilities']['Amount'].sum():,.2f}"])
    le_rows.append(['TOTAL LIABILITIES', f"{bs_obj['total_liabilities']:,.2f}"])
    le_rows.append(['EQUITY',''])
    for _, r in bs_obj['equity'].iterrows():
        le_rows.append([f"  {r['Account']}", f"{safe_float(r['Amount']):,.2f}"])
    le_rows.append(['TOTAL EQUITY', f"{bs_obj['total_equity']:,.2f}"])
    le_rows.append(['TOTAL LIABILITIES & EQUITY', f"{(bs_obj['total_liabilities'] + bs_obj['total_equity']):,.2f}"])
    lt = Table(le_rows, colWidths=[380,120], hAlign='LEFT')
    lt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.35,colors.grey),('BACKGROUND',(0,0),(1,0),colors.HexColor("#f0f0f0")),('ALIGN',(1,0),(-1,-1),'RIGHT')]))
    Story.append(lt)
    Story.append(PageBreak())

    # --- Cash Flow (Indirect) Page
    Story.append(Paragraph("CASH FLOW STATEMENT (INDIRECT)", hdr))
    cf_rows = [['Description','Amount']]
    cf_rows.append(['Net income', f"{income_obj['totals']['net_income']:,.2f}"])
    cf_rows.append(['Add: Depreciation', f"{income_obj['totals']['depreciation_total']:,.2f}"])
    if cf_obj['working_capital']:
        cf_rows.append(['Changes in working capital',''])
        for acct,ch,desc in cf_obj['working_capital']:
            cf_rows.append([f"  {desc}: {acct}", f"{ch:,.2f}"])
    cf_rows.append(['Net cash from operating activities', f"{cf_obj['cash_from_operations']:,.2f}"])
    cf_rows.append(['Net cash from investing activities', f"{cf_obj['cash_from_investing']:,.2f}"])
    cf_rows.append(['Net cash from financing activities', f"{cf_obj['cash_from_financing']:,.2f}"])
    cf_rows.append(['Net increase (decrease) in cash', f"{cf_obj['net_change']:,.2f}"])
    cf_rows.append(['Cash at beginning', f"{cf_obj['beginning_cash']:,.2f}"])
    cf_rows.append(['Cash at end', f"{cf_obj['ending_cash']:,.2f}"])
    cft = Table(cf_rows, colWidths=[380,120], hAlign='LEFT')
    cft.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.35,colors.grey),('BACKGROUND',(0,0),(1,0),colors.HexColor("#f0f0f0")),('ALIGN',(1,0),(-1,-1),'RIGHT')]))
    Story.append(cft)
    Story.append(PageBreak())

    # --- Depreciation Schedule & Journals (Page 4)
    Story.append(Paragraph("DEPRECIATION SCHEDULE & JOURNAL ENTRIES", hdr))
    drows = [['Asset','Cost','Salvage','Life (yrs)','Depreciation Exp (period)','Accumulated Depreciation']]
    # For accumulated we will approximate as (Depreciation Expense * life-to-date) — but here we only show period expense and cost/salvage/life
    for _, r in depreciation_df.iterrows():
        asset = r.get('Asset') or ''
        cost = safe_float(r.get('Cost', 0.0))
        salvage = safe_float(r.get('Salvage', 0.0))
        life = safe_float(r.get('LifeYears', 0.0))
        depr = safe_float(r.get('Depreciation Expense', 0.0))
        # accumulated (approx) = depr * life (but this is simplistic; show depr and cost/salvage)
        acc = depr * (life if life>0 else 1)
        drows.append([asset, f"{cost:,.2f}", f"{salvage:,.2f}", f"{life:.0f}", f"{depr:,.2f}", f"{acc:,.2f}"])
    dtable = Table(drows, colWidths=[150,70,70,70,90,90])
    dtable.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.35,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor("#f0f0f0")),('ALIGN',(1,1),(-1,-1),'RIGHT')]))
    Story.append(dtable)
    Story.append(Spacer(1,12))

    # Depreciation journal entries
    if journals:
        Story.append(Paragraph("Depreciation Journal Entries", normal))
        jrows = [['Period','Debit','Debit Amt','Credit','Credit Amt','Narration']]
        for j in journals:
            jrows.append([j['Period'], j['Debit Account'], f"{safe_float(j['Debit Amount']):,.2f}", j['Credit Account'], f"{safe_float(j['Credit Amount']):,.2f}", j['Narration']])
        jt = Table(jrows, colWidths=[50,120,80,120,80,100])
        jt.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.35,colors.grey),('BACKGROUND',(0,0),(-1,0),colors.HexColor("#f0f0f0")),('ALIGN',(2,1),(-1,-1),'RIGHT')]))
        Story.append(jt)

    doc.build(Story)

# ---------------- UI templates (Bootstrap) ----------------

HOME_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Financial Statements - Official Income</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-5">
  <div class="card shadow-sm">
    <div class="card-body">
      <h1 class="card-title">Financial Statements Generator</h1>
      <p class="card-text">Formal reports. Income Statement follows account names exactly and groups into Sales, COGS, Operating Expenses, etc.</p>
      <div class="mb-3">
        <a class="btn btn-primary me-2" href="{{ url_for('upload') }}">Upload CSVs / Generate</a>
        <a class="btn btn-outline-secondary me-2" href="{{ url_for('manual') }}">Manual Entry</a>
        <a class="btn btn-success" href="{{ url_for('generate_page') }}">Generate Statements</a>
        <a class="btn btn-info ms-2" href="{{ url_for('depr_page') }}">Depreciation Schedule</a>
      </div>
      <hr>
      <h6>Session manual data counts</h6>
      <p>Transactions: {{t}} | Begin Balances: {{bb}} | End Balances: {{be}} | Depreciation rows: {{depr}} | Accruals: {{ac}} | Investing: {{inv}} | Financing: {{fin}}</p>
      <p>Retained beginning: <strong>{{rb}}</strong> | Income Tax (manual): <strong>{{tax}}</strong></p>
    </div>
  </div>
</div>
</body></html>
"""

UPLOAD_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Upload CSVs</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4">
  <div class="card shadow-sm">
    <div class="card-body">
      <h3>Upload CSV files (these merge with manual entries)</h3>
      <form method="post" enctype="multipart/form-data">
        <div class="mb-2"><label class="form-label">Company</label><input class="form-control" name="company" placeholder="Company name"></div>
        <div class="mb-2"><label class="form-label">Period (year)</label><input class="form-control" name="period" placeholder="2025"></div>
        <div class="mb-2"><label>Transactions CSV</label><input class="form-control" type="file" name="transactions"></div>
        <div class="mb-2"><label>Balance Begin CSV</label><input class="form-control" type="file" name="balance_begin"></div>
        <div class="mb-2"><label>Balance End CSV</label><input class="form-control" type="file" name="balance_end"></div>
        <div class="mb-2"><label>Accruals CSV</label><input class="form-control" type="file" name="accruals"></div>
        <div class="mb-2"><label>Depreciation CSV</label><input class="form-control" type="file" name="depreciation"></div>
        <div class="mb-2"><label>Investing CSV</label><input class="form-control" type="file" name="investing"></div>
        <div class="mb-2"><label>Financing CSV</label><input class="form-control" type="file" name="financing"></div>
        <div class="mb-2">
          <label class="form-label">Output</label>
          <select class="form-select" name="output">
            <option value="PDF">PDF</option>
            <option value="Excel">Excel (.xlsx)</option>
          </select>
        </div>
        <div class="d-grid gap-2 d-md-flex">
          <button class="btn btn-primary" type="submit">Upload & Generate</button>
          <a class="btn btn-secondary" href="{{ url_for('index') }}">Home</a>
        </div>
      </form>
    </div>
  </div>
</div>
</body></html>
"""

MANUAL_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Manual Entry</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4">
  <div class="card shadow-sm">
    <div class="card-body">
      <h3>Manual Data Entry</h3>
      <form method="post">
        <div class="mb-2">
          <label class="form-label">Category</label>
          <select class="form-select" name="category">
            <option value="transactions">Transactions</option>
            <option value="balance_begin">Balance - Beginning</option>
            <option value="balance_end">Balance - Ending</option>
            <option value="accruals">Accruals</option>
            <option value="depreciation">Depreciation</option>
            <option value="investing">Investing</option>
            <option value="financing">Financing</option>
            <option value="retained">Retained Beginning</option>
            <option value="tax">Income Tax (manual amount)</option>
          </select>
        </div>

        <div class="mb-2"><label class="form-label">Date</label><input class="form-control" type="date" name="date"></div>
        <div class="mb-2"><label class="form-label">Account</label><input class="form-control" name="account"></div>
        <div class="mb-2"><label class="form-label">Transaction Category</label><input class="form-control" name="trans_category"></div>
        <div class="mb-2"><label class="form-label">Amount</label><input class="form-control" type="number" step="0.01" name="amount"></div>
        <div class="mb-2"><label class="form-label">Type (Revenue/Expense/Asset/Liability/Equity)</label><input class="form-control" name="type"></div>
        <div class="mb-2"><label class="form-label">Balance Type (Asset/Liability/Equity)</label><input class="form-control" name="bal_type"></div>
        <hr>
        <h6>Depreciation fields</h6>
        <div class="mb-2"><label class="form-label">Asset Name</label><input class="form-control" name="asset"></div>
        <div class="mb-2"><label class="form-label">Cost</label><input class="form-control" type="number" step="0.01" name="cost"></div>
        <div class="mb-2"><label class="form-label">Salvage</label><input class="form-control" type="number" step="0.01" name="salvage"></div>
        <div class="mb-2"><label class="form-label">Life (years)</label><input class="form-control" type="number" name="life"></div>
        <hr>
        <div class="mb-2"><label class="form-label">Retained Beginning</label><input class="form-control" type="number" step="0.01" name="retained"></div>
        <div class="mb-2"><label class="form-label">Income Tax (manual amount)</label><input class="form-control" type="number" step="0.01" name="tax"></div>

        <div class="d-grid gap-2 d-md-flex">
          <button class="btn btn-primary" type="submit">Add Manual Entry</button>
          <a class="btn btn-secondary" href="{{ url_for('index') }}">Home</a>
        </div>
      </form>
      <hr>
      <h6>Manual data counts</h6>
      <p>Transactions: {{t}} | Begin Balances: {{bb}} | End Balances: {{be}} | Depreciation rows: {{depr}} | Accruals: {{ac}} | Investing: {{inv}} | Financing: {{fin}}</p>
      <p>Retained beginning: {{rb}} | Income Tax (manual): {{tax}}</p>
    </div>
  </div>
</div>
</body></html>
"""

GENERATE_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Generate Statements</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4">
  <div class="card shadow-sm">
    <div class="card-body">
      <h3>Generate Financial Statements</h3>
      <form method="post">
        <div class="mb-2"><label class="form-label">Company</label><input class="form-control" name="company" placeholder="Company name"></div>
        <div class="mb-2"><label class="form-label">Period (year)</label><input class="form-control" name="period" placeholder="2025"></div>
        <div class="mb-2">
          <label class="form-label">Output</label>
          <select class="form-select" name="output">
            <option value="PDF">PDF (separate pages)</option>
            <option value="Excel">Excel (.xlsx)</option>
          </select>
        </div>
        <div class="d-grid gap-2 d-md-flex">
          <button class="btn btn-success" type="submit">Generate</button>
          <a class="btn btn-secondary" href="{{ url_for('index') }}">Cancel</a>
        </div>
      </form>
    </div>
  </div>
</div>
</body></html>
"""

DEPR_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Depreciation Schedule</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body class="bg-light">
<div class="container py-4">
  <div class="card shadow-sm">
    <div class="card-body">
      <h3>Depreciation Schedule (Tabular)</h3>
      {% if deps and deps|length > 0 %}
      <table class="table table-bordered table-striped">
        <thead><tr><th>Asset</th><th>Cost</th><th>Salvage</th><th>Life (yrs)</th><th>Depreciation (period)</th></tr></thead>
        <tbody>
          {% for d in deps %}
            <tr>
              <td>{{ d.Asset }}</td>
              <td class="text-end">{{ "{:,.2f}".format(d.Cost|float) }}</td>
              <td class="text-end">{{ "{:,.2f}".format(d.Salvage|float) }}</td>
              <td class="text-end">{{ d.LifeYears }}</td>
              <td class="text-end">{{ "{:,.2f}".format(d['Depreciation Expense']|float) }}</td>
            </tr>
          {% endfor %}
        </tbody>
      </table>
      {% else %}
        <p>No depreciation rows.</p>
      {% endif %}
      <a class="btn btn-secondary" href="{{ url_for('index') }}">Home</a>
    </div>
  </div>
</div>
</body></html>
"""

# ---------------- Routes ----------------

@app.route('/')
def index():
    md = manual_data
    return render_template_string(HOME_HTML,
                                  t=len(md['transactions']),
                                  bb=len(md['balance_begin']),
                                  be=len(md['balance_end']),
                                  depr=len(md['depreciation']),
                                  ac=len(md['accruals']),
                                  inv=len(md['investing']),
                                  fin=len(md['financing']),
                                  rb=md['retained_begin'],
                                  tax=md['income_tax'])

@app.route('/manual', methods=['GET','POST'])
def manual():
    global manual_data
    if request.method == 'POST':
        category = request.form.get('category')
        if category == 'transactions':
            row = {
                'Date': request.form.get('date') or str(datetime.now().date()),
                'Account': request.form.get('account') or 'Unnamed',
                'Category': request.form.get('trans_category') or '',
                'Amount': safe_float(request.form.get('amount') or 0.0),
                'Type': request.form.get('type') or 'Expense'
            }
            manual_data['transactions'] = pd.concat([manual_data['transactions'], pd.DataFrame([row])], ignore_index=True)
            flash('Transaction added.')
        elif category == 'balance_begin':
            row = {'Account': request.form.get('account') or 'Account', 'Amount': safe_float(request.form.get('amount') or 0.0), 'Type': request.form.get('bal_type') or 'Asset'}
            manual_data['balance_begin'] = pd.concat([manual_data['balance_begin'], pd.DataFrame([row])], ignore_index=True)
            flash('Beginning balance added.')
        elif category == 'balance_end':
            row = {'Account': request.form.get('account') or 'Account', 'Amount': safe_float(request.form.get('amount') or 0.0), 'Type': request.form.get('bal_type') or 'Asset'}
            manual_data['balance_end'] = pd.concat([manual_data['balance_end'], pd.DataFrame([row])], ignore_index=True)
            flash('Ending balance added.')
        elif category == 'accruals':
            row = {'Account': request.form.get('account') or 'Adj', 'Amount': safe_float(request.form.get('amount') or 0.0), 'Affects': request.form.get('affects') or 'Expense', 'BalanceType': request.form.get('bal_type') or 'Asset'}
            manual_data['accruals'] = pd.concat([manual_data['accruals'], pd.DataFrame([row])], ignore_index=True)
            flash('Accrual added.')
        elif category == 'depreciation':
            cost = safe_float(request.form.get('cost') or 0.0)
            salvage = safe_float(request.form.get('salvage') or 0.0)
            life = safe_float(request.form.get('life') or 1)
            depr = max(0.0, (cost - salvage) / (life if life>0 else 1))
            row = {'Asset': request.form.get('asset') or 'Asset', 'Cost': cost, 'Salvage': salvage, 'LifeYears': life, 'Depreciation Expense': depr}
            manual_data['depreciation'] = pd.concat([manual_data['depreciation'], pd.DataFrame([row])], ignore_index=True)
            flash('Depreciation row added.')
        elif category == 'investing':
            row = {'Account': request.form.get('account') or 'Invest', 'Amount': safe_float(request.form.get('amount') or 0.0)}
            manual_data['investing'] = pd.concat([manual_data['investing'], pd.DataFrame([row])], ignore_index=True)
            flash('Investing entry added.')
        elif category == 'financing':
            row = {'Account': request.form.get('account') or 'Finance', 'Amount': safe_float(request.form.get('amount') or 0.0)}
            manual_data['financing'] = pd.concat([manual_data['financing'], pd.DataFrame([row])], ignore_index=True)
            flash('Financing entry added.')
        elif category == 'retained':
            manual_data['retained_begin'] = safe_float(request.form.get('retained') or 0.0)
            flash('Retained beginning set.')
        elif category == 'tax':
            manual_data['income_tax'] = safe_float(request.form.get('tax') or 0.0)
            flash('Income tax (manual) set.')
        return redirect(url_for('manual'))

    md = manual_data
    return render_template_string(MANUAL_HTML,
                                  t=len(md['transactions']),
                                  bb=len(md['balance_begin']),
                                  be=len(md['balance_end']),
                                  depr=len(md['depreciation']),
                                  ac=len(md['accruals']),
                                  inv=len(md['investing']),
                                  fin=len(md['financing']),
                                  rb=md['retained_begin'],
                                  tax=md['income_tax'])

@app.route('/upload', methods=['GET','POST'])
def upload():
    global manual_data
    if request.method == 'POST':
        files = request.files
        file_map = {
            'transactions': ['Date','Account','Category','Amount','Type'],
            'balance_begin': ['Account','Amount','Type'],
            'balance_end': ['Account','Amount','Type'],
            'accruals': ['Account','Amount','Affects','BalanceType'],
            'depreciation': ['Asset','Cost','Salvage','LifeYears','Depreciation Expense'],
            'investing': ['Account','Amount'],
            'financing': ['Account','Amount']
        }
        uploaded = {}
        for key, cols in file_map.items():
            f = files.get(key)
            if f and f.filename:
                filename = secure_filename(f.filename)
                path = os.path.join(UPLOAD_FOLDER, filename)
                f.save(path)
                try:
                    df = pd.read_csv(path)
                except Exception:
                    df = pd.DataFrame(columns=cols)
                uploaded[key] = ensure_df_columns(df, cols)
            else:
                uploaded[key] = pd.DataFrame(columns=cols)

        # merge manual + uploaded
        merged = {}
        for key, cols in file_map.items():
            man = manual_data.get(key) if key in manual_data else pd.DataFrame(columns=cols)
            if man is None:
                man = pd.DataFrame(columns=cols)
            merged[key] = ensure_df_columns(pd.concat([uploaded.get(key, pd.DataFrame(columns=cols)), man], ignore_index=True, sort=False), cols)

        retained_begin = manual_data.get('retained_begin', 0.0)
        income_obj = compute_income_statement(merged['transactions'], merged['accruals'], merged['depreciation'], manual_data.get('income_tax', 0.0))
        bs_obj = compute_balance_sheet(merged['balance_end'], merged['accruals'], merged['depreciation'], retained_begin, income_obj['totals']['net_income'])
        journals = generate_depreciation_journal(merged['depreciation'], start_year=int(request.form.get('period')) if request.form.get('period') and request.form.get('period').isdigit() else None)
        cf_obj = cash_flow_statement_indirect(income_obj['totals']['income_before_tax'], income_obj['totals']['depreciation_total'], merged['balance_begin'], merged['balance_end'], merged['investing'], merged['financing'])

        output = request.form.get('output','PDF')
        company = request.form.get('company','My Company')
        period = request.form.get('period', str(datetime.now().year))

        if output == 'PDF':
            buffer = io.BytesIO()
            build_pdf(buffer, company, period, income_obj, bs_obj, cf_obj, merged['depreciation'], journals)
            buffer.seek(0)
            return send_file(buffer, as_attachment=True, download_name=f"{company.replace(' ','_')}_FS_{period}.pdf", mimetype='application/pdf')
        else:
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='openpyxl') as writer:
                merged['transactions'].to_excel(writer, sheet_name='Transactions', index=False)
                merged['balance_begin'].to_excel(writer, sheet_name='Balance_Begin', index=False)
                merged['balance_end'].to_excel(writer, sheet_name='Balance_End', index=False)
                merged['accruals'].to_excel(writer, sheet_name='Accruals', index=False)
                merged['depreciation'].to_excel(writer, sheet_name='Depreciation', index=False)
                merged['investing'].to_excel(writer, sheet_name='Investing', index=False)
                merged['financing'].to_excel(writer, sheet_name='Financing', index=False)

                # Income statement sheet (detailed)
                inc_rows = []
                inc_rows.append(['REVENUE',''])
                for acct, amt in income_obj['revenue_lines'].items():
                    inc_rows.append([acct, amt])
                inc_rows.append(['Total Revenue', income_obj['totals']['total_revenue']])
                inc_rows.append([])
                inc_rows.append(['COST OF GOODS SOLD',''])
                for acct, amt in income_obj['cogs_lines'].items():
                    inc_rows.append([acct, amt])
                inc_rows.append(['Total COGS', income_obj['totals']['total_cogs']])
                inc_rows.append([])
                inc_rows.append(['GROSS PROFIT', income_obj['totals']['gross_profit']])
                inc_rows.append([])
                inc_rows.append(['OPERATING EXPENSES',''])
                for acct, amt in income_obj['operating_lines'].items():
                    inc_rows.append([acct, amt])
                inc_rows.append(['Total Operating Expenses', income_obj['totals']['total_operating']])
                inc_rows.append([])
                inc_rows.append(['OPERATING INCOME', income_obj['totals']['operating_income']])
                inc_rows.append([])
                inc_rows.append(['OTHER INCOME/EXPENSE',''])
                for acct, amt in income_obj['other_income_lines'].items():
                    inc_rows.append([acct, amt])
                for acct, amt in income_obj['other_expense_lines'].items():
                    inc_rows.append([acct, amt])
                inc_rows.append(['Net Other Income', income_obj['totals']['net_other_income']])
                inc_rows.append([])
                inc_rows.append(['Income Before Tax', income_obj['totals']['income_before_tax']])
                inc_rows.append(['Income Tax (manual)', income_obj['totals']['income_tax']])
                inc_rows.append(['Net Income', income_obj['totals']['net_income']])
                pd.DataFrame(inc_rows, columns=['Line','Amount']).to_excel(writer, sheet_name='Income Statement', index=False)

                # Balance sheet top-down
                bs_rows = []
                bs_rows.append(['ASSETS',''])
                if not bs_obj['current_assets'].empty:
                    bs_rows.append(['Current Assets',''])
                    for _,r in bs_obj['current_assets'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                    bs_rows.append(['Total Current Assets', bs_obj['current_assets']['Amount'].sum()])
                if not bs_obj['noncurrent_assets'].empty:
                    bs_rows.append(['Non-current Assets',''])
                    for _,r in bs_obj['noncurrent_assets'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                    bs_rows.append(['Total Non-current Assets', bs_obj['noncurrent_assets']['Amount'].sum()])
                if not bs_obj['other_assets'].empty:
                    bs_rows.append(['Other Assets',''])
                    for _,r in bs_obj['other_assets'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                bs_rows.append(['Total Assets', bs_obj['total_assets']])
                bs_rows.append([])
                bs_rows.append(['LIABILITIES',''])
                if not bs_obj['current_liabilities'].empty:
                    bs_rows.append(['Current Liabilities',''])
                    for _,r in bs_obj['current_liabilities'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                    bs_rows.append(['Total Current Liabilities', bs_obj['current_liabilities']['Amount'].sum()])
                if not bs_obj['noncurrent_liabilities'].empty:
                    bs_rows.append(['Non-current Liabilities',''])
                    for _,r in bs_obj['noncurrent_liabilities'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                    bs_rows.append(['Total Non-current Liabilities', bs_obj['noncurrent_liabilities']['Amount'].sum()])
                bs_rows.append(['Total Liabilities', bs_obj['total_liabilities']])
                bs_rows.append(['EQUITY',''])
                for _,r in bs_obj['equity'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                bs_rows.append(['Total Equity', bs_obj['total_equity']])
                bs_rows.append(['Total Liabilities & Equity', bs_obj['total_liabilities'] + bs_obj['total_equity']])
                pd.DataFrame(bs_rows, columns=['Line','Amount']).to_excel(writer, sheet_name='Balance Sheet', index=False)

                # Cash Flow
                cf_rows = [
                    ['Net cash from operations', cf_obj['cash_from_operations']],
                    ['Net cash from investing', cf_obj['cash_from_investing']],
                    ['Net cash from financing', cf_obj['cash_from_financing']],
                    ['Net change', cf_obj['net_change']],
                    ['Beginning cash', cf_obj['beginning_cash']],
                    ['Ending cash', cf_obj['ending_cash']]
                ]
                pd.DataFrame(cf_rows, columns=['Description','Amount']).to_excel(writer, sheet_name='Cash Flow', index=False)

                # Depreciation & journals
                merged['depreciation'].to_excel(writer, sheet_name='Depreciation', index=False)
                pd.DataFrame(journals).to_excel(writer, sheet_name='Depreciation Journals', index=False)
            out.seek(0)
            return send_file(out, as_attachment=True, download_name=f"{company.replace(' ','_')}_FS_{period}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    return render_template_string(UPLOAD_HTML)

@app.route('/generate', methods=['GET','POST'])
def generate_page():
    # Use manual data only when generating here (no uploaded CSVs)
    if request.method == 'POST':
        merged = {}
        file_map = {
            'transactions': ['Date','Account','Category','Amount','Type'],
            'balance_begin': ['Account','Amount','Type'],
            'balance_end': ['Account','Amount','Type'],
            'accruals': ['Account','Amount','Affects','BalanceType'],
            'depreciation': ['Asset','Cost','Salvage','LifeYears','Depreciation Expense'],
            'investing': ['Account','Amount'],
            'financing': ['Account','Amount']
        }
        for key, cols in file_map.items():
            man = manual_data.get(key) if key in manual_data else pd.DataFrame(columns=cols)
            if man is None:
                man = pd.DataFrame(columns=cols)
            merged[key] = ensure_df_columns(man, cols)

        retained_begin = manual_data.get('retained_begin', 0.0)
        income_obj = compute_income_statement(merged['transactions'], merged['accruals'], merged['depreciation'], manual_data.get('income_tax', 0.0))
        bs_obj = compute_balance_sheet(merged['balance_end'], merged['accruals'], merged['depreciation'], retained_begin, income_obj['totals']['net_income'])
        journals = generate_depreciation_journal(merged['depreciation'], start_year=int(request.form.get('period')) if request.form.get('period') and request.form.get('period').isdigit() else None)
        cf_obj = cash_flow_statement_indirect(income_obj['totals']['income_before_tax'], income_obj['totals']['depreciation_total'], merged['balance_begin'], merged['balance_end'], merged['investing'], merged['financing'])

        output = request.form.get('output','PDF')
        company = request.form.get('company','My Company')
        period = request.form.get('period', str(datetime.now().year))

        if output == 'PDF':
            buf = io.BytesIO()
            build_pdf(buf, company, period, income_obj, bs_obj, cf_obj, merged['depreciation'], journals)
            buf.seek(0)
            return send_file(buf, as_attachment=True, download_name=f"{company.replace(' ','_')}_FS_{period}.pdf", mimetype='application/pdf')
        else:
            # Excel export similar to upload route but using manual data merged only
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine='openpyxl') as writer:
                merged['transactions'].to_excel(writer, sheet_name='Transactions', index=False)
                merged['balance_begin'].to_excel(writer, sheet_name='Balance_Begin', index=False)
                merged['balance_end'].to_excel(writer, sheet_name='Balance_End', index=False)
                merged['accruals'].to_excel(writer, sheet_name='Accruals', index=False)
                merged['depreciation'].to_excel(writer, sheet_name='Depreciation', index=False)
                merged['investing'].to_excel(writer, sheet_name='Investing', index=False)
                merged['financing'].to_excel(writer, sheet_name='Financing', index=False)

                # Income
                inc_rows = []
                inc_rows.append(['REVENUE',''])
                for acct, amt in income_obj['revenue_lines'].items(): inc_rows.append([acct, amt])
                inc_rows.append(['Total Revenue', income_obj['totals']['total_revenue']])
                inc_rows.append([])
                inc_rows.append(['COST OF GOODS SOLD',''])
                for acct, amt in income_obj['cogs_lines'].items(): inc_rows.append([acct, amt])
                inc_rows.append(['Total COGS', income_obj['totals']['total_cogs']])
                inc_rows.append([])
                inc_rows.append(['GROSS PROFIT', income_obj['totals']['gross_profit']])
                inc_rows.append([])
                inc_rows.append(['OPERATING EXPENSES',''])
                for acct, amt in income_obj['operating_lines'].items(): inc_rows.append([acct, amt])
                inc_rows.append(['Total Operating Expenses', income_obj['totals']['total_operating']])
                inc_rows.append([])
                inc_rows.append(['OPERATING INCOME', income_obj['totals']['operating_income']])
                inc_rows.append([])
                inc_rows.append(['OTHER INCOME/EXPENSE',''])
                for acct, amt in income_obj['other_income_lines'].items(): inc_rows.append([acct, amt])
                for acct, amt in income_obj['other_expense_lines'].items(): inc_rows.append([acct, amt])
                inc_rows.append(['Net Other Income', income_obj['totals']['net_other_income']])
                inc_rows.append([])
                inc_rows.append(['Income Before Tax', income_obj['totals']['income_before_tax']])
                inc_rows.append(['Income Tax (manual)', income_obj['totals']['income_tax']])
                inc_rows.append(['Net Income', income_obj['totals']['net_income']])
                pd.DataFrame(inc_rows, columns=['Line','Amount']).to_excel(writer, sheet_name='Income Statement', index=False)

                # Balance sheet
                bs_rows = []
                bs_rows.append(['ASSETS',''])
                if not bs_obj['current_assets'].empty:
                    bs_rows.append(['Current Assets',''])
                    for _,r in bs_obj['current_assets'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                    bs_rows.append(['Total Current Assets', bs_obj['current_assets']['Amount'].sum()])
                if not bs_obj['noncurrent_assets'].empty:
                    bs_rows.append(['Non-current Assets',''])
                    for _,r in bs_obj['noncurrent_assets'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                    bs_rows.append(['Total Non-current Assets', bs_obj['noncurrent_assets']['Amount'].sum()])
                if not bs_obj['other_assets'].empty:
                    bs_rows.append(['Other Assets',''])
                    for _,r in bs_obj['other_assets'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                bs_rows.append(['Total Assets', bs_obj['total_assets']])
                bs_rows.append([])
                bs_rows.append(['LIABILITIES',''])
                if not bs_obj['current_liabilities'].empty:
                    bs_rows.append(['Current Liabilities',''])
                    for _,r in bs_obj['current_liabilities'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                    bs_rows.append(['Total Current Liabilities', bs_obj['current_liabilities']['Amount'].sum()])
                if not bs_obj['noncurrent_liabilities'].empty:
                    bs_rows.append(['Non-current Liabilities',''])
                    for _,r in bs_obj['noncurrent_liabilities'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                    bs_rows.append(['Total Non-current Liabilities', bs_obj['noncurrent_liabilities']['Amount'].sum()])
                bs_rows.append(['Total Liabilities', bs_obj['total_liabilities']])
                bs_rows.append(['EQUITY',''])
                for _,r in bs_obj['equity'].iterrows(): bs_rows.append([r['Account'], r['Amount']])
                bs_rows.append(['Total Equity', bs_obj['total_equity']])
                bs_rows.append(['Total Liabilities & Equity', bs_obj['total_liabilities'] + bs_obj['total_equity']])
                pd.DataFrame(bs_rows, columns=['Line','Amount']).to_excel(writer, sheet_name='Balance Sheet', index=False)

                pd.DataFrame([['Net cash from operations', cf_obj['cash_from_operations']], ['Net cash from investing', cf_obj['cash_from_investing']], ['Net cash from financing', cf_obj['cash_from_financing']], ['Net change', cf_obj['net_change']], ['Beginning cash', cf_obj['beginning_cash']], ['Ending cash', cf_obj['ending_cash']]], columns=['Description','Amount']).to_excel(writer, sheet_name='Cash Flow', index=False)

                merged['depreciation'].to_excel(writer, sheet_name='Depreciation', index=False)
                pd.DataFrame(journals).to_excel(writer, sheet_name='Depreciation_Journals', index=False)
            out.seek(0)
            return send_file(out, as_attachment=True, download_name=f"{company.replace(' ','_')}_FS_{period}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    return render_template_string(GENERATE_HTML)

@app.route('/depreciation')
def depr_page():
    deps = manual_data.get('depreciation', pd.DataFrame()).to_dict('records')
    return render_template_string(DEPR_HTML, deps=deps)

if __name__ == '__main__':
    app.run(debug=True)
