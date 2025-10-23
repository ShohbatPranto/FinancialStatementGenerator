# 💼 Financial Statement Generator

A **Flask-based Financial Statement Generator** that helps businesses and individuals generate official-style **Income Statements**, **Balance Sheets**, **Cash Flow Statements**, and **Depreciation Reports** automatically from CSV data or manual inputs.

---

## 🚀 Features

- 📂 **CSV Upload** — Automatically processes financial transactions.
- ✍️ **Manual Entry Option** — Add records directly through the web interface.
- 📊 **Detailed Income Statement** — Categorizes Revenue, Expenses, COGS, and more.
- 🧾 **Professional Balance Sheet** — Top-down format similar to official reports.
- 💸 **Cash Flow Statement** — Tracks operating, investing, and financing activities.
- 🏗️ **Depreciation Report** — Separate, clear view of all asset depreciation.
- 🧮 **Automated Calculations** — Totals and net income computed instantly.
- 🖥️ **Modern UI** — Clean, responsive, and intuitive layout.

---

## 🧰 Tech Stack

- **Backend:** Python (Flask)
- **Frontend:** HTML, CSS (Bootstrap)
- **Database:** SQLite (via SQLAlchemy)
- **Data Handling:** Pandas

---

## ⚙️ Installation & Setup

### 1. Clone the Repository
```bash```
git clone https://github.com/ShohbatPranto/FinancialStatementGenerator.git
cd FinancialStatementGenerator

2. Create a Virtual Environment
```bash```
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

3. Install Dependencies
```bash```
pip install -r requirements.txt

4. Run the Application
```bash```
python financial_statements_flask_app.py
Then visit http://127.0.0.1:5000/ in your browser.


📁 CSV File Format

Your CSV should include at least the following columns:

Date, Description, Account, Debit, Credit, Balance

Example:

2025-10-01, Product Sales, Sales, 50000, , 50000
2025-10-03, Rent Payment, Rent, , 10000, 40000
2025-10-05, Salary Expense, Salaries, , 15000, 25000

🧾 Example Output

Income Statement — Sales, COGS, Operating Expenses, Income Tax, Net Income

Balance Sheet — Assets, Liabilities, Equity

Cash Flow Statement — Operating, Investing, Financing activities

Depreciation Report — Asset-wise depreciation summary

All formatted professionally, similar to official financial statements.

🧠 Future Improvements

🔹 User Authentication

🔹 AI-based Financial Analysis and Comments

🔹 Organization and Account Management

🤝 Contributing

Contributions are welcome!
Please open an issue or submit a pull request for suggestions or bug fixes.

🧾 License

This project is open-source under the MIT License.

👤 Author

Shohbat Pranto
📧 shohbatahsanpranto@gmail.com
💼 Computer Science Graduate with interest in Accounting and Financial Systems
