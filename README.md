# Carpion

Carpion is a desktop portfolio analysis and portfolio-building application. It evaluates historical returns, volatility, portfolio risk, allocations, optimization strategies, and macro stress scenarios.

Built with Python, Tkinter, pandas, NumPy, matplotlib, and SciPy.

> **Disclaimer:** Carpion is an analytical tool, not investment advice. Validate all data, assumptions, constraints, and results before making investment decisions.

## Features

### Portfolio Analyzer

- Load historical return data from YCharts-style CSV files.
- Calculate portfolio return, annualized volatility, Value at Risk (VaR), maximum drawdown, and risk contributions.
- Edit portfolio weights manually, normalize them, or assign equal weights.
- Optimize allocations for minimum volatility, best gain-to-volatility, or maximum return at a target risk level.
- View historical cumulative returns, drawdown, allocation, and risk/return charts.
- Export results to Excel or CSV.

### Portfolio Builder

- Load model portfolio allocations from Excel workbooks.
- Load historical fund and benchmark data from VaR workbooks.
- Match funds across data sources using built-in aliases.
- Choose risk profiles, objectives, expected-return assumptions, allocation constraints, and benchmarks.
- Build a model-based or optimized allocation.
- Run editable macro stress tests by fund or asset-class bucket.
- Export client-ready analysis results to Excel or CSV.

## Requirements

- Python 3.13 recommended
- macOS or Windows
- Excel workbooks in `.xlsx` or `.xlsm` format

Dependencies are listed in [`requirements.txt`](requirements.txt):

```text
numpy
pandas
openpyxl
matplotlib
scipy
pyinstaller
```

## Installation

Clone the repository:

```bash
git clone https://github.com/Hobbs2k8/Carpion.git
cd Carpion
```

Create a virtual environment and install dependencies.

### macOS / Linux

```bash
python3.13 -m venv .venv313
source .venv313/bin/activate
pip install -r requirements.txt
```

### Windows

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run Carpion

```bash
python portfolio_analyzer.py
```

The application opens with two tabs:

- **Analyzer** — CSV-based portfolio analysis and optimization.
- **Portfolio Builder** — model portfolio, VaR workbook, allocation, and stress-test workflow.

## Input Files

### Historical Returns CSV

The Analyzer expects a YCharts-style CSV with a header row beginning with `Symbol`. Carpion reads symbols, names, and date-based return columns from that row onward.

### Model Portfolio Workbook

The Portfolio Builder reads `.xlsx` and `.xlsm` workbooks. For each portfolio sheet, it looks for:

- Fund names in column `C`
- Allocation weights in column `D`
- A portfolio label in cell `A4`
- A benchmark reference in cell `C8`

Valid fund weights are normalized automatically.

### VaR / Volatility Workbook

The Portfolio Builder expects a workbook containing a worksheet named `Equity VaR Mar 26`. It detects return-history blocks with dates in a column, series names in a header row, and return observations below. A fund needs at least four usable observations to be included.

## Typical Workflow

1. Start the app with `python portfolio_analyzer.py`.
2. In **Analyzer**, load a CSV, review weights, optionally optimize, run the analysis, and export results.
3. In **Portfolio Builder**, load the model and VaR workbooks, choose a risk profile, review the fund setup, build an allocation, run stress tests, and export results.

## Exports

Carpion exports `.xlsx` Excel workbooks or `.csv` files. Exports can include portfolio metrics, allocations, risk measures, optimization output, and stress-test results.

## Build a macOS App

With the virtual environment installed:

```bash
chmod +x build_app.sh
./build_app.sh
```

The build produces:

```text
dist/PortfolioAnalyzer.app
dist/PortfolioAnalyzer-macOS.zip
```

## Build a Windows Executable

GitHub Actions builds a Windows package when relevant files are pushed to `main` or when the **Build Windows Package** workflow is run manually.

1. Open the repository's **Actions** tab.
2. Select **Build Windows Package**.
3. Choose **Run workflow**.
4. Download the `PortfolioAnalyzer-windows` artifact when it completes.

## Project Structure

```text
Carpion/
├── portfolio_analyzer.py      # Main desktop application
├── requirements.txt           # Python dependencies
├── build_app.sh               # macOS application build script
├── PortfolioAnalyzer.spec     # PyInstaller configuration
├── .github/workflows/         # GitHub Actions Windows build workflow
└── README.md                  # Project documentation
```

## Development Notes

- Saved stress-test scenarios are stored locally in `portfolio_builder_scenarios.json`.
- Generated environments, caches, and build output are excluded from Git.
- Review spreadsheet and CSV data carefully before making the repository public, as they may contain portfolio-related information.

## License

Add a license before distributing or open-sourcing the project.
