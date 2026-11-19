"""Checks on the files M4 produces: Power BI model, business summary and the Excel workbook.

The workbook is checked by reading the committed file, so these tests need neither Excel nor
Power BI.
"""

import re
import zipfile
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from forecast_to_decision.business_summary import (
    business_summary,
    check_findings,
    compute_findings,
)
from forecast_to_decision.datasets import build_reporting_tables
from forecast_to_decision.powerbi_export import guide_text, powerbi_tables

ROOT = Path(__file__).resolve().parents[1]
DAX_PATH = ROOT / "powerbi" / "measures.dax"
POWERBI_DATA = ROOT / "powerbi" / "data"
WORKBOOK = ROOT / "reports" / "forecast_to_decision.xlsx"
SUMMARY = ROOT / "BUSINESS_SUMMARY.md"
README = ROOT / "README.md"

JARGON = ("MAPE", "RMSE", "MIP", "HAC", "regression", "heteroskedastic", "autocorrelat", "OLS")
SUMMARY_MAX_WORDS = 480


@pytest.fixture(scope="module")
def tables():
    return build_reporting_tables()


def dax_text() -> str:
    return DAX_PATH.read_text(encoding="utf-8")


def defined_measures(text: str) -> list[str]:
    """Measure names: a line that starts at the left margin with `Name =`."""
    return re.findall(r"^([A-Za-z][^=\n]*?) =\s*$", text, flags=re.MULTILINE)


# ---- Power BI model --------------------------------------------------------------------


def test_every_table_and_column_in_the_measures_exists_in_the_data_files(tables):
    model = {name: set(frame.columns) for name, frame in powerbi_tables(tables).items()}
    references = re.findall(r"\b(Fact\w+|Dim\w+)\[(\w+)\]", dax_text())

    assert references
    for table, column in references:
        assert table in model, f"{table} is not a table in the model"
        assert column in model[table], f"{table}[{column}] is not a column"


def test_every_measure_used_inside_another_is_defined():
    text = dax_text()
    defined = set(defined_measures(text))
    # A bare [Name] with no table in front of it is a reference to another measure.
    used = set(re.findall(r"(?<![\w\]])\[([^\]]+)\]", text))

    assert defined
    assert used <= defined, f"undefined measures: {sorted(used - defined)}"


def test_measure_names_are_unique():
    names = defined_measures(dax_text())

    assert len(names) == len(set(names))


def test_the_committed_data_files_match_the_model(tables):
    for name, frame in powerbi_tables(tables).items():
        committed = pd.read_csv(POWERBI_DATA / f"{name}.csv", nrows=0)
        assert list(committed.columns) == list(frame.columns), name


def test_the_guide_lists_every_data_file_and_the_committed_guide_is_current(tables):
    guide = guide_text(tables)

    for name in powerbi_tables(tables):
        assert f"`{name}.csv`" in guide
    assert (ROOT / "powerbi" / "POWERBI_GUIDE.md").read_text(encoding="utf-8") == guide


def test_the_guide_gives_a_check_value_for_every_measure(tables):
    guide = guide_text(tables)

    for name in defined_measures(dax_text()):
        assert f"| {name} |" in guide, f"no check value for {name}"


def test_every_relationship_in_the_guide_uses_real_columns_and_the_one_side_is_unique(tables):
    model = powerbi_tables(tables)
    guide = guide_text(tables)
    pairs = re.findall(r"\| `(\w+)\[(\w+)\]` \| `(\w+)\[(\w+)\]` \|", guide)

    assert pairs
    for one_table, one_column, many_table, many_column in pairs:
        assert one_column in model[one_table].columns
        assert many_column in model[many_table].columns
        assert model[one_table][one_column].is_unique, f"{one_table}[{one_column}] is not unique"
        values = set(model[one_table][one_column])
        assert set(model[many_table][many_column]) <= values, f"{many_table}[{many_column}] has orphans"


def test_no_table_can_be_filtered_by_two_different_paths(tables):
    guide = guide_text(tables)
    pairs = re.findall(r"\| `(\w+)\[\w+\]` \| `(\w+)\[\w+\]` \|", guide)
    edges = {(one, many) for one, many in pairs}

    # Find any pair of tables joined both directly and through a third table.
    for one, many in edges:
        for middle in {m for o, m in edges if o == one}:
            assert (middle, many) not in edges, f"{one} reaches {many} directly and through {middle}"


def test_the_date_table_is_daily_and_has_no_gaps(tables):
    dates = tables.calendar["date"]

    assert dates.is_unique
    assert (dates.diff().dropna() == pd.Timedelta(days=1)).all()


# ---- Business summary ------------------------------------------------------------------


def test_the_summary_fits_one_page_and_avoids_technical_terms(tables):
    text = business_summary(tables)

    assert len(text.split()) <= SUMMARY_MAX_WORDS
    for term in JARGON:
        assert term.lower() not in text.lower(), term


def test_the_committed_summary_is_current_and_copied_into_the_readme(tables):
    text = business_summary(tables)

    assert SUMMARY.read_text(encoding="utf-8") == text
    body = text.replace("# What this analysis means for the business\n\n", "")
    assert body in README.read_text(encoding="utf-8")


def test_every_number_in_the_summary_is_in_the_results(tables):
    findings = compute_findings(tables)
    text = business_summary(tables)

    for value in (
        findings.optimised_cost,
        findings.rule_cost,
        findings.forecast_revenue,
        abs(findings.saving),
        abs(findings.strict_saving),
        abs(findings.revenue_gap),
    ):
        assert f"{value:,.1f}" in text


def test_the_summary_refuses_to_publish_when_a_recommendation_is_no_longer_supported(tables):
    findings = compute_findings(tables)
    flipped_saving = replace(findings, strict_rule_cost=findings.strict_optimised_cost + 10)
    forecast_wins = replace(findings, normal_weather_miss=findings.last_year_miss - 1)
    price_not_largest = replace(findings, effects={**findings.effects, "weather": 99_999.0})
    plans_differ_in_past_winters = replace(
        findings, optimised_short_scenarios=findings.rule_short_scenarios + 3
    )
    saving_not_small = replace(findings, optimised_cost=findings.rule_cost * 0.9)
    price_pulls_revenue_down = replace(findings, effects={**findings.effects, "price": -742.5})
    no_case_met_in_full = replace(findings, last_full_service_error=float("nan"))

    for changed in (
        flipped_saving,
        forecast_wins,
        price_not_largest,
        price_pulls_revenue_down,
        no_case_met_in_full,
        plans_differ_in_past_winters,
        saving_not_small,
    ):
        with pytest.raises(ValueError, match="Rewrite the business summary"):
            check_findings(changed)
    check_findings(findings)


# ---- Excel workbook --------------------------------------------------------------------


@pytest.fixture(scope="module")
def workbook():
    return load_workbook(WORKBOOK, data_only=True)


def test_the_workbook_has_two_real_pivot_tables():
    with zipfile.ZipFile(WORKBOOK) as archive:
        pivots = [
            name
            for name in archive.namelist()
            if name.startswith("xl/pivotTables/pivotTable") and name.endswith(".xml")
        ]

    assert len(pivots) == 2


def test_the_workbook_has_no_error_values_and_every_formula_has_a_value(workbook):
    formulas = load_workbook(WORKBOOK)
    for sheet in formulas:
        for row in sheet.iter_rows():
            for cell in row:
                value = workbook[sheet.title][cell.coordinate].value
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    assert value is not None, f"{sheet.title}!{cell.coordinate} has no value"
                if isinstance(value, str):
                    assert not value.startswith("#"), f"{sheet.title}!{cell.coordinate}: {value}"


def test_revenue_formulas_in_the_data_sheet_match_python(workbook, tables):
    sheet = workbook["Data"]
    forecast = sum(sheet.cell(row=row, column=12).value for row in range(2, 74))
    actual = sum(sheet.cell(row=row, column=13).value for row in range(2, 74))

    assert forecast == pytest.approx(tables.monthly_sector["forecast_revenue_musd"].sum())
    assert actual == pytest.approx(tables.monthly_sector["actual_revenue_musd"].sum())


def test_the_variance_check_column_is_zero_in_every_month(workbook):
    sheet = workbook["Variance"]

    checks = [sheet.cell(row=row, column=13).value for row in range(2, 38)]

    assert all(abs(value) < 1e-9 for value in checks)


def test_the_variance_pivot_totals_match_the_m3_results(workbook, tables):
    pivots = workbook["Pivots"]
    header_row = next(
        row for row in range(1, 60) if pivots.cell(row=row, column=2).value == "Weather ($M)"
    )
    total_row = next(
        row for row in range(header_row, 60) if pivots.cell(row=row, column=1).value == "Grand Total"
    )
    variance = tables.monthly_variance

    for column, name in enumerate(("weather", "volume", "mix", "price"), start=2):
        assert pivots.cell(row=total_row, column=column).value == pytest.approx(
            variance[f"{name}_musd"].sum()
        )


def test_the_scenario_sheet_with_no_changes_reproduces_the_forecast(workbook):
    sheet = workbook["Scenario"]

    assert sheet["B4"].value == sheet["B5"].value == sheet["B6"].value == 0
    for row in range(10, 14):
        assert sheet.cell(row=row, column=3).value == pytest.approx(sheet.cell(row=row, column=2).value)


def test_the_scenario_plan_costs_at_zero_error_match_the_optimisation_grid(workbook, tables):
    sheet = workbook["Scenario"]
    grid = tables.sensitivity[tables.sensitivity["forecast_error_percent"] == 0].set_index("plan")
    rows = {sheet.cell(row=row, column=1).value: row for row in range(20, 40)}

    for plan in ("Rule of thumb", "Optimised plan", "Perfect hindsight"):
        assert sheet.cell(row=rows[plan], column=2).value == pytest.approx(grid.loc[plan, "cost_musd"])


def test_the_lookup_sheet_returns_the_selected_months_values(workbook, tables):
    sheet = workbook["Lookup"]
    month = sheet["B3"].value
    monthly = tables.monthly_sector
    row = monthly[monthly["key"] == f"{month}|residential"].iloc[0]

    assert sheet["B6"].value == pytest.approx(row["forecast_mmcf"])
    assert sheet["B8"].value == pytest.approx(row["actual_mmcf"])
    assert sheet["B12"].value == pytest.approx(row["forecast_revenue_musd"])


def validated_cells(sheet) -> set[str]:
    cells = set()
    for validation in sheet.data_validations.dataValidation:
        for cell_range in validation.sqref.ranges:
            cells.update(f"{get_column_letter(column)}{row}" for row, column in cell_range.cells)
    return cells


def test_validation_rejects_bad_values_instead_of_only_existing():
    scenario = load_workbook(WORKBOOK)["Scenario"]

    for validation in scenario.data_validations.dataValidation:
        assert validation.showErrorMessage is True
        # "stop" is the file format's default, so Excel leaves the attribute out when it saves.
        assert validation.errorStyle in (None, "stop")


# There is no pytest check for the clamp on the scenario error input, because only Excel can
# evaluate the formulas. scripts/add_pivots.ps1 checks it by behaviour on every build: it writes
# +/-40% into the input and fails unless the plan costs equal those at +/-15%.


def test_the_lookup_month_cell_is_text_so_it_cannot_turn_into_a_date():
    lookup = load_workbook(WORKBOOK)["Lookup"]

    assert lookup["B3"].number_format == "@"


def test_the_workbook_holds_no_personal_name_or_local_path():
    with zipfile.ZipFile(WORKBOOK) as archive:
        parts = {name: archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist()}

    core = parts["docProps/core.xml"]
    assert "<cp:lastModifiedBy>forecast-to-decision</cp:lastModifiedBy>" in core
    assert "<dc:creator>forecast-to-decision</dc:creator>" in core
    for name, text in parts.items():
        assert "absPath" not in text, name
        assert "C:\\Users" not in text, name
        if name.startswith("xl/pivotCache/pivotCacheDefinition"):
            assert 'refreshedBy="forecast-to-decision"' in text


def test_every_input_cell_has_validation():
    sheets = load_workbook(WORKBOOK)
    scenario = sheets["Scenario"]
    error_input_row = next(
        row for row in range(10, 40) if scenario.cell(row=row, column=1).value == "Realised demand vs forecast"
    )

    assert {"B4", "B5", "B6", f"B{error_input_row}"} <= validated_cells(scenario)
    assert "B3" in validated_cells(sheets["Lookup"])
