# Run as Administrator — bypass flaky DNS for Supabase pooler (Tailscale etc.)
# Usage: powershell -ExecutionPolicy Bypass -File scripts/fix_supabase_hosts.ps1

$ErrorActionPreference = "Stop"
$hostsPath = "$env:SystemRoot\System32\drivers\etc\hosts"
$hostName = "aws-0-ca-central-1.pooler.supabase.com"

Write-Host "Resolving $hostName ..."
$ip = $null
try {
    $resolved = [System.Net.Dns]::GetHostAddresses($hostName) | Where-Object { $_.AddressFamily -eq 'InterNetwork' }
    if ($resolved) { $ip = $resolved[0].IPAddressToString }
} catch {
    Write-Host "DNS lookup failed, using known Supabase pooler IP fallback."
}
if (-not $ip) {
    $ip = "15.156.180.136"
}
Write-Host "Using IP: $ip"

$entry = "$ip `t$hostName"
$hosts = Get-Content $hostsPath -ErrorAction Stop
if ($hosts -match [regex]::Escape($hostName)) {
    Write-Host "Entry already exists in hosts file."
} else {
    Add-Content -Path $hostsPath -Value $entry
    Write-Host "Added to hosts: $entry"
}

ipconfig /flushdns | Out-Null
Write-Host "Done. Test with: python scripts/check_db_connection.py"
