<#
.SYNOPSIS
  Adds two PivotTables to the workbook, recalculates every formula, and saves the result.

.DESCRIPTION
  openpyxl cannot create PivotTables, so this uses Excel itself through COM. It needs
  Excel for Windows. It refuses to run if Excel is already open, because it quits the
  Excel it starts and must never close a copy that you are using.

.EXAMPLE
  powershell -File scripts\add_pivots.ps1 -InputPath build\raw.xlsx -OutputPath reports\forecast_to_decision.xlsx
#>
param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = "Stop"

# Excel constants
$xlDatabase = 1
$xlRowField = 1
$xlColumnField = 2
$xlSum = -4157
$xlOpenXmlWorkbook = 51

if (Get-Process EXCEL -ErrorAction SilentlyContinue) {
    throw "Excel is already running. Close it and run this script again."
}

$inputFull = (Resolve-Path $InputPath).Path
$outputFull = [IO.Path]::GetFullPath($OutputPath)
New-Item -ItemType Directory -Force (Split-Path $outputFull) | Out-Null

function Add-SumField($pivot, [string]$field, [string]$caption, [string]$format) {
    $dataField = $pivot.AddDataField($pivot.PivotFields($field), $caption, $xlSum)
    $dataField.NumberFormat = $format
}

function Release-ComObject($object) {
    if ($null -ne $object) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($object) }
}

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$workbook = $null; $sheet = $null
$revenueCache = $null; $revenue = $null; $varianceCache = $null; $variance = $null
try {
    $workbook = $excel.Workbooks.Open($inputFull)
    $sheet = $workbook.Worksheets.Item("Pivots")

    # Revenue by plan year (rows) and sector (columns), forecast and actual side by side.
    $revenueCache = $workbook.PivotCaches().Create($xlDatabase, "tblMonthly")
    $revenue = $revenueCache.CreatePivotTable($sheet.Range("A4"), "ptRevenue")
    $revenue.PivotFields("plan_year").Orientation = $xlRowField
    $revenue.PivotFields("sector").Orientation = $xlColumnField
    Add-SumField $revenue "forecast_revenue_musd" "Forecast revenue (`$M)" "#,##0.0"
    Add-SumField $revenue "actual_revenue_musd" "Actual revenue (`$M)" "#,##0.0"

    # Variance effects by three month period.
    $varianceCache = $workbook.PivotCaches().Create($xlDatabase, "tblVariance")
    $variance = $varianceCache.CreatePivotTable($sheet.Range("A18"), "ptVariance")
    $variance.PivotFields("period").Orientation = $xlRowField
    Add-SumField $variance "weather_musd" "Weather (`$M)" "#,##0.0;-#,##0.0"
    Add-SumField $variance "volume_musd" "Volume (`$M)" "#,##0.0;-#,##0.0"
    Add-SumField $variance "mix_musd" "Mix (`$M)" "#,##0.0;-#,##0.0"
    Add-SumField $variance "price_musd" "Price (`$M)" "#,##0.0;-#,##0.0"
    Add-SumField $variance "total_variance_musd" "Total variance (`$M)" "#,##0.0;-#,##0.0"

    # Formulas written by openpyxl have no stored values until Excel calculates them.
    $excel.CalculateFull()
    $revenue.RefreshTable() | Out-Null
    $variance.RefreshTable() | Out-Null
    $sheet.Columns("A:H").AutoFit() | Out-Null

    $workbook.SaveAs($outputFull, $xlOpenXmlWorkbook)
    $workbook.Close($false)
    Write-Output "Saved $outputFull"
}
finally {
    if ($null -ne $workbook) { try { $workbook.Close($false) } catch { } }
    $excel.Quit()
    foreach ($object in @($variance, $varianceCache, $revenue, $revenueCache, $sheet, $workbook, $excel)) {
        Release-ComObject $object
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
