"""Milestone 4: build the Excel workbook, the Power BI data model and the business summary.

Needs the outputs of run_m1.py, run_m2.py and run_m3.py (results/). Run from the repo root:

    python scripts/run_m4.py                    # everything
    python scripts/run_m4.py --skip-workbook    # no Excel needed

The workbook step needs Excel for Windows, because PivotTables can only be created by Excel.
It stops if Excel is already open, so close it first.
"""

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from forecast_to_decision.business_summary import business_summary
from forecast_to_decision.datasets import build_reporting_tables
from forecast_to_decision.powerbi_export import guide_text, write_powerbi_data
from forecast_to_decision.workbook import build_workbook

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = ROOT / "reports" / "forecast_to_decision.xlsx"
POWERBI_DIR = ROOT / "powerbi"
SUMMARY_PATH = ROOT / "BUSINESS_SUMMARY.md"
README_PATH = ROOT / "README.md"
PIVOT_SCRIPT = ROOT / "scripts" / "add_pivots.ps1"

SUMMARY_START = "<!-- business-summary:start -->"
SUMMARY_END = "<!-- business-summary:end -->"


def write_workbook(tables) -> None:
    """Build the workbook with openpyxl, then let Excel add the PivotTables and calculate."""
    if sys.platform != "win32":
        raise RuntimeError("The workbook step needs Excel for Windows; use --skip-workbook")
    with tempfile.TemporaryDirectory() as folder:
        raw_path = Path(folder) / "workbook_without_pivots.xlsx"
        build_workbook(tables, raw_path)
        subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(PIVOT_SCRIPT),
                "-InputPath", str(raw_path),
                "-OutputPath", str(WORKBOOK_PATH),
            ],
            check=True,
        )  # fmt: skip


def update_readme_summary(summary: str) -> None:
    """Replace the generated block of the README with the current business summary."""
    text = README_PATH.read_text(encoding="utf-8")
    pattern = re.compile(f"{re.escape(SUMMARY_START)}.*?{re.escape(SUMMARY_END)}", re.DOTALL)
    if not pattern.search(text):
        raise RuntimeError(f"README.md has no {SUMMARY_START} ... {SUMMARY_END} block")
    # Demote the headings so the summary nests under the README's own section heading.
    body = summary.replace("# What this analysis means for the business\n\n", "")
    README_PATH.write_text(
        pattern.sub(lambda _: f"{SUMMARY_START}\n{body}{SUMMARY_END}", text), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--skip-workbook", action="store_true", help="do not build the workbook")
    arguments = parser.parse_args()

    tables = build_reporting_tables()

    names = write_powerbi_data(tables, POWERBI_DIR / "data")
    (POWERBI_DIR / "POWERBI_GUIDE.md").write_text(guide_text(tables), encoding="utf-8")
    print(f"Wrote {len(names)} Power BI tables and the guide to {POWERBI_DIR}")

    summary = business_summary(tables)
    SUMMARY_PATH.write_text(summary, encoding="utf-8")
    update_readme_summary(summary)
    print(f"Wrote {SUMMARY_PATH.name} ({len(summary.split())} words) and updated the README")

    if arguments.skip_workbook:
        print("Skipped the workbook")
    else:
        write_workbook(tables)
        print(f"Wrote {WORKBOOK_PATH}")


if __name__ == "__main__":
    main()
