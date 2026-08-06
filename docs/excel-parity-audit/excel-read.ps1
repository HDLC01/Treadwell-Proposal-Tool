# Excel's own answers for the audit — the authority, since it is the application Troy opens.
#
# Opens each copied workbook read-only, forces a FULL rebuild (so nothing comes from a cached
# value), and reads the compare list. Whole sheets are pulled as one 2D array per sheet rather
# than one COM call per cell: ~1,700 cells x 6 workbooks would otherwise be 10,000 round trips.
#
# Touches only the copies in this folder. The Dropbox originals are never opened.

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$xl = New-Object -ComObject Excel.Application
$xl.Visible = $false
$xl.DisplayAlerts = $false
$xl.ScreenUpdating = $false

function Get-SheetGrid($ws) {
  # One COM call for the whole used range, plus its origin so addresses can be indexed.
  $ur = $ws.UsedRange
  return @{
    values = $ur.Value2
    row0   = $ur.Row
    col0   = $ur.Column
    rows   = $ur.Rows.Count
    cols   = $ur.Columns.Count
  }
}

function Convert-AddrToRC($addr) {
  if ($addr -notmatch '^([A-Z]{1,3})(\d+)$') { return $null }
  $letters = $Matches[1]; $row = [int]$Matches[2]
  $col = 0
  foreach ($ch in $letters.ToCharArray()) { $col = $col * 26 + ([int][char]$ch - 64) }
  return @{ row = $row; col = $col }
}

try {
  foreach ($json in Get-ChildItem $here -Filter "job*.json" | Where-Object { $_.Name -notmatch 'excel|hf|diff' }) {
    $stem = $json.BaseName
    $book = Join-Path $here "$stem.xlsx"
    if (-not (Test-Path $book)) { continue }

    $spec = Get-Content $json.FullName -Raw | ConvertFrom-Json
    $wb = $xl.Workbooks.Open($book, $false, $true)
    $xl.CalculateFullRebuild()

    $grids = @{}
    $out = @{}
    foreach ($c in $spec.compare) {
      if (-not $grids.ContainsKey($c.sheet)) {
        $ws = $null
        try { $ws = $wb.Worksheets.Item($c.sheet) } catch {}
        if ($ws -eq $null) { $grids[$c.sheet] = $null; continue }
        $grids[$c.sheet] = Get-SheetGrid $ws
      }
      $g = $grids[$c.sheet]
      if ($g -eq $null) { continue }
      $rc = Convert-AddrToRC $c.addr
      if ($rc -eq $null) { continue }
      $r = $rc.row - $g.row0 + 1
      $k = $rc.col - $g.col0 + 1
      $v = $null
      if ($r -ge 1 -and $k -ge 1 -and $r -le $g.rows -and $k -le $g.cols) {
        try { $v = $g.values[$r, $k] } catch { $v = $null }
      }
      $out["$($c.sheet)!$($c.addr)"] = $v
    }

    $wb.Close($false)
    $outPath = Join-Path $here "$stem.excel.json"
    $out | ConvertTo-Json -Depth 4 -Compress | Set-Content $outPath -Encoding utf8
    "{0}: read {1} cells -> {2}" -f $stem, $out.Count, (Split-Path -Leaf $outPath)
  }
} finally {
  $xl.Quit()
  [System.Runtime.Interopservices.Marshal]::ReleaseComObject($xl) | Out-Null
  [System.GC]::Collect()
}
