"""Build the Excel workbook: data tables, lookups and a scenario sheet.

The PivotTables are added afterwards by scripts/add_pivots.ps1, because openpyxl
cannot create them. Only INDEX, MATCH, SUMIFS and SUMPRODUCT style functions are used,
so every formula works in any recent version of Excel.
"""

from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from forecast_to_decision.datasets import ReportingTables

HEADER_FONT = Font(bold=True)
TITLE_FONT = Font(bold=True, size=14)
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
NOTE_FONT = Font(italic=True, color="595959")

MONTHLY_COLUMNS = [
    "key", "month", "plan_year", "period", "season", "sector", "forecast_mmcf",
    "weather_adjusted_forecast_mmcf", "actual_mmcf", "budget_price", "actual_price",
    "forecast_revenue_musd", "actual_revenue_musd",
]  # fmt: skip
VARIANCE_COLUMNS = [
    "month", "month_label", "plan_year", "period", "season", "forecast_revenue_musd",
    "actual_revenue_musd", "weather_musd", "volume_musd", "mix_musd", "price_musd",
    "total_variance_musd", "check_musd",
]  # fmt: skip
COMMITMENT_COLUMNS = [
    "plan_year", "month_label", "month", "price_per_mcf", "forecast_mmcf", "actual_mmcf",
    "pipeline_capacity_mmcf", "rule_nomination_mmcf", "rule_peaking",
    "optimised_nomination_mmcf", "optimised_peaking",
]  # fmt: skip
PLAN_RESULT_COLUMNS = ["plan_year", "plan", "cost_musd", "served_percent", "shortfall_months",
                       "peaking_mmcf"]  # fmt: skip
SENSITIVITY_COLUMNS = ["forecast_error_percent", "plan", "cost_musd", "served_percent"]

GRID_STEP_POINTS = 5
GRID_MIN_POINTS = -15
GRID_MAX_POINTS = 15
PLAN_NAMES = ("Rule of thumb", "Optimised plan", "Perfect hindsight")


def _add_table(sheet: Worksheet, name: str, first_column: int, n_rows: int, n_columns: int) -> None:
    first = f"{get_column_letter(first_column)}1"
    last = f"{get_column_letter(first_column + n_columns - 1)}{n_rows + 1}"
    table = Table(displayName=name, ref=f"{first}:{last}")
    table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    sheet.add_table(table)


def _write_columns(
    sheet: Worksheet, frame: pd.DataFrame, columns: list[str], first_column: int
) -> None:
    """Write a header row and the values of `frame[columns]`; columns missing from it are left."""
    for offset, name in enumerate(columns):
        column = first_column + offset
        sheet.cell(row=1, column=column, value=name).font = HEADER_FONT
        if name in frame.columns:
            for row, value in enumerate(frame[name].tolist(), start=2):
                if isinstance(value, pd.Timestamp):
                    value = value.to_pydatetime()
                sheet.cell(row=row, column=column, value=value)


def _format_column(sheet: Worksheet, column: int, n_rows: int, number_format: str) -> None:
    for row in range(2, n_rows + 2):
        sheet.cell(row=row, column=column).number_format = number_format


def _widen(sheet: Worksheet, widths: dict[str, float]) -> None:
    for letter, width in widths.items():
        sheet.column_dimensions[letter].width = width


def _month_label(month: pd.Timestamp) -> str:
    return f"{month:%Y-%m}"


def _write_guide(sheet: Worksheet) -> None:
    sheet["A1"] = "Forecast to decision: Massachusetts natural gas"
    sheet["A1"].font = TITLE_FONT
    lines = [
        "",
        "What this workbook holds: the 36 month holdout from the project, by month and sector.",
        "Every number comes from the project's results files; nothing is typed in by hand.",
        "",
        "Sheets",
        "  Data: one row per month and sector. Revenue columns are formulas (volume x price / 1000).",
        "  Variance: the gap between forecast and actual revenue, split into four effects.",
        "  Pivots: PivotTables on the two tables above. Use Data > Refresh All after any change.",
        "  Lookup: pick a month and read its volumes, prices, variance effects and supply plan.",
        "  Scenario: change demand and prices, and test a forecast error against the supply plans.",
        "  PlanData: the supply plans and their results, from the optimisation milestone.",
        "",
        "Units: volumes in MMcf (million cubic feet), prices in dollars per Mcf, revenue in $M.",
        "Positive variance means actual is above forecast.",
        "Yellow cells on the Scenario sheet are inputs.",
    ]
    for row, text in enumerate(lines, start=2):
        sheet.cell(row=row, column=1, value=text)
    sheet["A6"].font = HEADER_FONT
    sheet.column_dimensions["A"].width = 110


def _write_data_sheet(sheet: Worksheet, tables: ReportingTables) -> int:
    data = tables.monthly_sector
    n_rows = len(data)
    _write_columns(sheet, data, MONTHLY_COLUMNS, 1)
    for row in range(2, n_rows + 2):
        sheet.cell(row=row, column=12, value=f"=G{row}*J{row}/1000")  # forecast revenue
        sheet.cell(row=row, column=13, value=f"=I{row}*K{row}/1000")  # actual revenue
        sheet.cell(row=row, column=2).number_format = "yyyy-mm"
    for column in (7, 8, 9):
        _format_column(sheet, column, n_rows, "#,##0")
    for column in (10, 11):
        _format_column(sheet, column, n_rows, "0.00")
    for column in (12, 13):
        _format_column(sheet, column, n_rows, "#,##0.0")
    _add_table(sheet, "tblMonthly", 1, n_rows, len(MONTHLY_COLUMNS))
    sheet.freeze_panes = "A2"
    _widen(sheet, {"A": 22, "B": 10, "C": 20, "D": 20, "E": 9, "F": 12, "G": 14, "H": 18,
                   "I": 12, "J": 12, "K": 12, "L": 18, "M": 18})  # fmt: skip
    return n_rows


def _write_variance_sheet(sheet: Worksheet, tables: ReportingTables, data_rows: int) -> int:
    variance = tables.monthly_variance.copy()
    variance["month_label"] = variance["month"].map(_month_label)
    n_rows = len(variance)
    _write_columns(sheet, variance, VARIANCE_COLUMNS, 1)
    last_data_row = data_rows + 1
    for row in range(2, n_rows + 2):
        month = f"Data!$B$2:$B${last_data_row}"
        for column, source in ((6, "L"), (7, "M")):
            sums = f"Data!${source}$2:${source}${last_data_row}"
            sheet.cell(row=row, column=column, value=f"=SUMIFS({sums},{month},A{row})")
        sheet.cell(row=row, column=12, value=f"=G{row}-F{row}")  # actual minus forecast
        sheet.cell(row=row, column=13, value=f"=L{row}-SUM(H{row}:K{row})")  # should be zero
        sheet.cell(row=row, column=1).number_format = "yyyy-mm"
    for column in range(6, 14):
        _format_column(sheet, column, n_rows, "#,##0.0;[Red]-#,##0.0")
    _add_table(sheet, "tblVariance", 1, n_rows, len(VARIANCE_COLUMNS))
    sheet.freeze_panes = "A2"
    _widen(sheet, {"A": 10, "B": 12, "C": 20, "D": 20, "E": 9, "F": 20, "G": 18, "H": 14,
                   "I": 14, "J": 12, "K": 12, "L": 20, "M": 12})  # fmt: skip
    return n_rows


def _write_plan_data_sheet(sheet: Worksheet, tables: ReportingTables) -> dict[str, int]:
    commitments = tables.commitments.copy()
    commitments["month_label"] = commitments["month"].map(_month_label)
    for column in ("rule_peaking", "optimised_peaking"):
        commitments[column] = commitments[column].map({True: "Yes", False: "No"})
    results = tables.plan_comparison
    sensitivity = tables.sensitivity

    _write_columns(sheet, commitments, COMMITMENT_COLUMNS, 1)
    _write_columns(sheet, results, PLAN_RESULT_COLUMNS, 14)
    _write_columns(sheet, sensitivity, SENSITIVITY_COLUMNS, 22)
    for row in range(2, len(commitments) + 2):
        sheet.cell(row=row, column=3).number_format = "yyyy-mm"
    _add_table(sheet, "tblCommitments", 1, len(commitments), len(COMMITMENT_COLUMNS))
    _add_table(sheet, "tblPlanResults", 14, len(results), len(PLAN_RESULT_COLUMNS))
    _add_table(sheet, "tblSensitivity", 22, len(sensitivity), len(SENSITIVITY_COLUMNS))
    _widen(sheet, {"A": 20, "B": 12, "N": 20, "O": 18, "V": 24, "W": 18})
    return {
        "commitments": len(commitments),
        "results": len(results),
        "sensitivity": len(sensitivity),
    }


def _lookup_formula(source_sheet: str, column: str, last_row: int, key_range: str, key: str) -> str:
    values = f"{source_sheet}!${column}$2:${column}${last_row}"
    keys = f"{source_sheet}!${key_range}$2:${key_range}${last_row}"
    return f"=INDEX({values},MATCH({key},{keys},0))"


def _write_lookup_sheet(
    sheet: Worksheet, months: list[str], data_rows: int, variance_rows: int, plan_rows: int
) -> None:
    sheet["A1"] = "Look up a month"
    sheet["A1"].font = TITLE_FONT
    sheet["A3"] = "Month (pick from the list)"
    sheet["A3"].font = HEADER_FONT
    default_month = "2025-01"  # a winter month shows the largest effects
    sheet["B3"] = default_month if default_month in months else months[len(months) // 2]
    sheet["B3"].fill = INPUT_FILL
    for row, label in enumerate(months, start=3):
        sheet.cell(row=row, column=8, value=label)
    sheet["H2"] = "Months"
    sheet["H2"].font = HEADER_FONT
    validation = DataValidation(
        type="list", formula1=f"=$H$3:$H${len(months) + 2}", allow_blank=False
    )
    sheet.add_data_validation(validation)
    validation.add("B3")

    data_last = data_rows + 1
    for column, name in enumerate(["Measure", "Residential", "Commercial", "Total"], start=1):
        sheet.cell(row=5, column=column, value=name).font = HEADER_FONT

    volume_rows = [
        (6, "Forecast volume (MMcf)", "G", "#,##0"),
        (7, "Weather adjusted forecast (MMcf)", "H", "#,##0"),
        (8, "Actual volume (MMcf)", "I", "#,##0"),
    ]
    for row, label, column, number_format in volume_rows:
        sheet.cell(row=row, column=1, value=label)
        for target, sector in ((2, "residential"), (3, "commercial")):
            key = f'$B$3&"|{sector}"'
            cell = sheet.cell(
                row=row, column=target, value=_lookup_formula("Data", column, data_last, "A", key)
            )
            cell.number_format = number_format
        sheet.cell(row=row, column=4, value=f"=B{row}+C{row}").number_format = number_format
    sheet.cell(row=9, column=1, value="Volume variance, actual minus forecast (MMcf)")
    for column in "BCD":
        sheet[f"{column}9"] = f"={column}8-{column}6"
        sheet[f"{column}9"].number_format = "#,##0;[Red]-#,##0"

    price_rows = [(10, "Budget price ($/Mcf)", "J"), (11, "Actual price ($/Mcf)", "K")]
    for row, label, column in price_rows:
        sheet.cell(row=row, column=1, value=label)
        for target, sector in ((2, "residential"), (3, "commercial")):
            key = f'$B$3&"|{sector}"'
            cell = sheet.cell(
                row=row, column=target, value=_lookup_formula("Data", column, data_last, "A", key)
            )
            cell.number_format = "0.00"

    revenue_rows = [(12, "Forecast revenue ($M)", "L"), (13, "Actual revenue ($M)", "M")]
    for row, label, column in revenue_rows:
        sheet.cell(row=row, column=1, value=label)
        for target, sector in ((2, "residential"), (3, "commercial")):
            key = f'$B$3&"|{sector}"'
            cell = sheet.cell(
                row=row, column=target, value=_lookup_formula("Data", column, data_last, "A", key)
            )
            cell.number_format = "#,##0.0"
        sheet.cell(row=row, column=4, value=f"=B{row}+C{row}").number_format = "#,##0.0"
    sheet.cell(row=14, column=1, value="Revenue variance, actual minus forecast ($M)")
    for column in "BCD":
        sheet[f"{column}14"] = f"={column}13-{column}12"
        sheet[f"{column}14"].number_format = "#,##0.0;[Red]-#,##0.0"

    sheet["A16"] = "Revenue variance effects for the month ($M)"
    sheet["A16"].font = HEADER_FONT
    variance_last = variance_rows + 1
    effects = [
        (17, "Weather", "H"), (18, "Volume", "I"), (19, "Mix", "J"), (20, "Price", "K"),
        (21, "Total variance", "L"),
    ]  # fmt: skip
    for row, label, column in effects:
        sheet.cell(row=row, column=1, value=label)
        cell = sheet.cell(
            row=row,
            column=2,
            value=_lookup_formula("Variance", column, variance_last, "B", "$B$3"),
        )
        cell.number_format = "#,##0.0;[Red]-#,##0.0"

    sheet["A23"] = "Supply plan for the month"
    sheet["A23"].font = HEADER_FONT
    plan_last = plan_rows + 1
    plan_items = [
        (24, "Plan year", "A", "General"),
        (25, "Pipeline capacity (MMcf)", "G", "#,##0"),
        (26, "Rule of thumb buys (MMcf)", "H", "#,##0"),
        (27, "Optimised plan buys (MMcf)", "J", "#,##0"),
        (28, "Rule of thumb contracts peaking", "I", "General"),
        (29, "Optimised plan contracts peaking", "K", "General"),
        (30, "Pipeline price ($/Mcf)", "D", "0.00"),
    ]
    for row, label, column, number_format in plan_items:
        sheet.cell(row=row, column=1, value=label)
        cell = sheet.cell(
            row=row,
            column=2,
            value=_lookup_formula("PlanData", column, plan_last, "B", "$B$3"),
        )
        cell.number_format = number_format
        cell.alignment = Alignment(horizontal="right")
    _widen(sheet, {"A": 46, "B": 20, "C": 14, "D": 14, "H": 10})


def _write_scenario_sheet(
    sheet: Worksheet, plan_years: list[str], data_rows: int, sensitivity_rows: int
) -> None:
    last = data_rows + 1
    sensitivity_last = sensitivity_rows + 1
    revenue_forecast = f"Data!$L$2:$L${last}"
    revenue_actual = f"Data!$M$2:$M${last}"
    plan_year = f"Data!$C$2:$C${last}"
    sector = f"Data!$F$2:$F${last}"

    sheet["A1"] = "Scenario: what if demand or prices differ?"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = "Change the yellow cells. Percentages are changes from the forecast."
    sheet["A2"].font = NOTE_FONT

    inputs = [
        (4, "Demand change (all sectors)", 0.0, 0.30),
        (5, "Residential price change", 0.0, 0.30),
        (6, "Commercial price change", 0.0, 0.30),
    ]
    for row, label, default, limit in inputs:
        sheet.cell(row=row, column=1, value=label).font = HEADER_FONT
        cell = sheet.cell(row=row, column=2, value=default)
        cell.fill = INPUT_FILL
        cell.number_format = "0.0%"
        validation = DataValidation(
            type="decimal", operator="between", formula1=str(-limit), formula2=str(limit)
        )
        validation.error = f"Enter a change between {-limit:.0%} and {limit:.0%}"
        sheet.add_data_validation(validation)
        validation.add(cell)

    headers = ["Plan year", "Forecast revenue ($M)", "Scenario revenue ($M)",
               "Actual revenue ($M)", "Scenario minus actual ($M)"]  # fmt: skip
    for column, name in enumerate(headers, start=1):
        sheet.cell(row=9, column=column, value=name).font = HEADER_FONT
    for offset, label in enumerate(plan_years):
        row = 10 + offset
        sheet.cell(row=row, column=1, value=label)
        sheet.cell(
            row=row, column=2, value=f"=SUMIFS({revenue_forecast},{plan_year},$A{row})"
        )
        residential = f'SUMIFS({revenue_forecast},{plan_year},$A{row},{sector},"residential")'
        commercial = f'SUMIFS({revenue_forecast},{plan_year},$A{row},{sector},"commercial")'
        sheet.cell(
            row=row,
            column=3,
            value=f"=(1+$B$4)*((1+$B$5)*{residential}+(1+$B$6)*{commercial})",
        )
        sheet.cell(row=row, column=4, value=f"=SUMIFS({revenue_actual},{plan_year},$A{row})")
        sheet.cell(row=row, column=5, value=f"=C{row}-D{row}")
    total_row = 10 + len(plan_years)
    sheet.cell(row=total_row, column=1, value="Total").font = HEADER_FONT
    for column in "BCDE":
        sheet[f"{column}{total_row}"] = f"=SUM({column}10:{column}{total_row - 1})"
        sheet[f"{column}{total_row}"].font = HEADER_FONT
    for row in range(10, total_row + 1):
        for column in "BCDE":
            sheet[f"{column}{row}"].number_format = "#,##0.0;[Red]-#,##0.0"

    plan_start = total_row + 3
    sheet.cell(row=plan_start, column=1, value="Supply plans under a forecast error").font = (
        HEADER_FONT
    )
    error_row = plan_start + 1
    sheet.cell(row=error_row, column=1, value="Realised demand vs forecast")
    error_cell = sheet.cell(row=error_row, column=2, value=0.0)
    error_cell.fill = INPUT_FILL
    error_cell.number_format = "0.0%"
    limit = GRID_MAX_POINTS / 100
    validation = DataValidation(
        type="decimal", operator="between", formula1=str(-limit), formula2=str(limit)
    )
    validation.error = f"Enter an error between {-limit:.0%} and {limit:.0%}"
    sheet.add_data_validation(validation)
    validation.add(error_cell)

    points_row, low_row, high_row, weight_row = (error_row + k for k in (1, 2, 3, 4))
    sheet.cell(row=points_row, column=1, value="Error in percentage points")
    sheet.cell(row=points_row, column=2, value=f"=B{error_row}*100")
    sheet.cell(row=low_row, column=1, value="Grid point below")
    sheet.cell(
        row=low_row,
        column=2,
        value=(
            f"=MIN({GRID_MAX_POINTS - GRID_STEP_POINTS},"
            f"MAX({GRID_MIN_POINTS},{GRID_STEP_POINTS}*INT(B{points_row}/{GRID_STEP_POINTS})))"
        ),
    )
    sheet.cell(row=high_row, column=1, value="Grid point above")
    sheet.cell(row=high_row, column=2, value=f"=B{low_row}+{GRID_STEP_POINTS}")
    sheet.cell(row=weight_row, column=1, value="Weight on the upper point")
    sheet.cell(row=weight_row, column=2, value=f"=(B{points_row}-B{low_row})/{GRID_STEP_POINTS}")

    header_row = weight_row + 2
    for column, name in enumerate(
        ["Plan", "Cost per plan year ($M)", "Demand served (%)"], start=1
    ):
        sheet.cell(row=header_row, column=column, value=name).font = HEADER_FONT
    sensitivity_error = f"PlanData!$V$2:$V${sensitivity_last}"
    sensitivity_plan = f"PlanData!$W$2:$W${sensitivity_last}"
    for offset, plan in enumerate(PLAN_NAMES):
        row = header_row + 1 + offset
        sheet.cell(row=row, column=1, value=plan)
        for column, source in ((2, "X"), (3, "Y")):
            values = f"PlanData!${source}$2:${source}${sensitivity_last}"

            def at(grid_cell: str, values: str = values, row: int = row) -> str:
                return f"SUMIFS({values},{sensitivity_plan},$A{row},{sensitivity_error},{grid_cell})"

            formula = f"={at(f'$B${low_row}')}*(1-$B${weight_row})+{at(f'$B${high_row}')}*$B${weight_row}"
            cell = sheet.cell(row=row, column=column, value=formula)
            cell.number_format = "#,##0.0" if column == 2 else "0.00"
    note_row = header_row + len(PLAN_NAMES) + 2
    sheet.cell(
        row=note_row,
        column=1,
        value=(
            "These costs and service levels come from the optimisation runs on the holdout "
            "and are interpolated between grid points. This is not a new optimisation."
        ),
    ).font = NOTE_FONT
    _widen(sheet, {"A": 36, "B": 24, "C": 24, "D": 22, "E": 26})


def _write_pivot_sheet(sheet: Worksheet) -> None:
    sheet["A1"] = "PivotTables"
    sheet["A1"].font = TITLE_FONT
    sheet["A2"] = "Built on tblMonthly and tblVariance. Use Data > Refresh All after any change."
    sheet["A2"].font = NOTE_FONT


def build_workbook(tables: ReportingTables, path: Path) -> None:
    """Write the workbook without PivotTables to `path`."""
    workbook = Workbook()
    guide = workbook.active
    guide.title = "Guide"
    data = workbook.create_sheet("Data")
    variance = workbook.create_sheet("Variance")
    pivots = workbook.create_sheet("Pivots")
    lookup = workbook.create_sheet("Lookup")
    scenario = workbook.create_sheet("Scenario")
    plan_data = workbook.create_sheet("PlanData")

    _write_guide(guide)
    data_rows = _write_data_sheet(data, tables)
    variance_rows = _write_variance_sheet(variance, tables, data_rows)
    plan_counts = _write_plan_data_sheet(plan_data, tables)
    _write_pivot_sheet(pivots)

    months = [_month_label(month) for month in tables.monthly_variance["month"]]
    _write_lookup_sheet(lookup, months, data_rows, variance_rows, plan_counts["commitments"])
    plan_years = list(dict.fromkeys(tables.monthly_sector["plan_year"]))
    _write_scenario_sheet(scenario, plan_years, data_rows, plan_counts["sensitivity"])
    workbook.save(path)
