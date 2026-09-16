param(
    [Parameter(Mandatory=$true)]
    [string]$FilePath
)

$absPath = [System.IO.Path]::GetFullPath($FilePath)
$dir = [System.IO.Path]::GetDirectoryName($absPath)
if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

if (Test-Path $absPath) {
    Remove-Item $absPath -Force
}

$catalog = New-Object -ComObject ADOX.Catalog
$connStr = "Provider=Microsoft.ACE.OLEDB.12.0;Data Source=$absPath"
$catalog.Create($connStr)
[System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($catalog) | Out-Null
[GC]::Collect()
[GC]::WaitForPendingFinalizers()

if (Test-Path $absPath) {
    Write-Output "SUCCESS: Created $absPath"
    [System.Environment]::Exit(0)
} else {
    Write-Error "FAILED to create $absPath"
    [System.Environment]::Exit(1)
}
