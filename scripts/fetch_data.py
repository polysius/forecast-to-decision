"""Download the raw inputs and save small CSV extracts under data/raw.

Sources (no API keys needed):
  * EIA bulk file NG.zip: Massachusetts monthly gas deliveries, prices, and
    annual customer counts.
  * NOAA NCEI daily summaries: daily max and min temperature at Boston Logan.

Run once; the extracts are committed so tests and analysis work offline.
"""

import io
import json
import zipfile
from pathlib import Path

import pandas as pd
import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"

EIA_BULK_URL = "https://www.eia.gov/opendata/bulk/NG.zip"
NCEI_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
BOSTON_LOGAN_STATION = "USW00014739"
FIRST_YEAR = 1989

MONTHLY_SERIES = {
    "NG.N3010MA2.M": "residential_mmcf",
    "NG.N3020MA2.M": "commercial_mmcf",
    "NG.N3010MA3.M": "residential_price",
    "NG.N3020MA3.M": "commercial_price",
    "NG.N3050MA3.M": "citygate_price",
}
ANNUAL_SERIES = {
    "NG.NA1501_SMA_8.A": "residential_customers",
    "NG.NA1531_SMA_8.A": "commercial_customers",
}


def read_eia_series(wanted_ids: set[str]) -> dict[str, dict]:
    """Return {series_id: record} for the wanted ids from the EIA bulk zip."""
    response = requests.get(EIA_BULK_URL, timeout=120)
    response.raise_for_status()
    found = {}
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    with archive, archive.open("NG.txt") as bulk_file:
        for line in bulk_file:
            record = json.loads(line)
            if record.get("series_id") in wanted_ids:
                found[record["series_id"]] = record
    missing = wanted_ids - found.keys()
    if missing:
        raise RuntimeError(f"Series missing from EIA bulk file: {sorted(missing)}")
    return found


def series_to_frame(records: dict[str, dict], names: dict[str, str]) -> pd.DataFrame:
    """Turn EIA [period, value] pairs into one column per series."""
    columns = {}
    for series_id, column_name in names.items():
        points = records[series_id]["data"]
        columns[column_name] = pd.Series(
            {period: value for period, value in points}, dtype="float64"
        )
    return pd.DataFrame(columns).sort_index()


def fetch_eia() -> None:
    wanted = set(MONTHLY_SERIES) | set(ANNUAL_SERIES)
    records = read_eia_series(wanted)

    monthly = series_to_frame(records, MONTHLY_SERIES)
    monthly.index = pd.PeriodIndex(monthly.index, freq="M").to_timestamp()
    monthly.index.name = "month"
    monthly = monthly[monthly.index >= f"{FIRST_YEAR}-01-01"]
    monthly.to_csv(RAW_DIR / "ma_gas_monthly.csv")

    annual = series_to_frame(records, ANNUAL_SERIES)
    annual.index = annual.index.astype(int)
    annual.index.name = "year"
    annual.to_csv(RAW_DIR / "ma_customers_annual.csv")


def fetch_temperatures() -> None:
    """Pull one calendar year per request to keep responses small."""
    last_year = pd.Timestamp.today().year
    yearly_frames = []
    for year in range(FIRST_YEAR, last_year + 1):
        params = {
            "dataset": "daily-summaries",
            "stations": BOSTON_LOGAN_STATION,
            "startDate": f"{year}-01-01",
            "endDate": f"{year}-12-31",
            "dataTypes": "TMAX,TMIN",
            "units": "standard",  # degrees Fahrenheit
            "format": "csv",
        }
        response = requests.get(NCEI_URL, params=params, timeout=120)
        response.raise_for_status()
        yearly_frames.append(pd.read_csv(io.StringIO(response.text)))

    daily = pd.concat(yearly_frames)
    daily = daily[["DATE", "TMAX", "TMIN"]].rename(
        columns={"DATE": "date", "TMAX": "tmax_f", "TMIN": "tmin_f"}
    )
    daily.to_csv(RAW_DIR / "boston_daily_temps.csv", index=False)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    fetch_eia()
    fetch_temperatures()
    print(f"Saved extracts to {RAW_DIR}")


if __name__ == "__main__":
    main()
