# GMCS Client Troubleshooting v1 - run locally, not from the website.
# Does NOT transmit anything. Review resulting JSON before uploading it manually.
# Example: powershell.exe -NoProfile -File .\gmcs-diagnostics-windows.ps1
# Optional extra device identifiers: -IncludeSensitive
param([switch]$IncludeSensitive)
$ErrorActionPreference = 'Continue'
Write-Host 'GMCS diagnostics run locally. A JSON report will be saved for your review.'
Write-Host 'No diagnostics are uploaded without a separate action on the speed-test page.'
function Capture([string]$Name, [scriptblock]$Block) {
    try {
        $value = (& $Block 2>&1 | Out-String)
        if ($value.Length -gt 3500) { $value = $value.Substring(0,3500) + "`n[truncated]" }
        $script:commands[$Name] = $value
    } catch { $script:commands[$Name] = "Diagnostic unavailable: $($_.Exception.GetType().Name)" }
}
$commands = [ordered]@{}
Capture hostname { hostname }
Capture ipconfig { ipconfig /all }
Capture gateway { route print -4 }
Capture dns_servers { Get-DnsClientServerAddress -AddressFamily IPv4 | Format-Table -AutoSize }
# Discover this device's configured DNS, rather than hardcoding GMCS private IPs.
$resolvers = @(Get-DnsClientServerAddress -AddressFamily IPv4 |
    ForEach-Object { $_.ServerAddresses } |
    Where-Object { $_ -match '^\d{1,3}(\.\d{1,3}){3}$' -and $_ -ne '127.0.0.1' } |
    Select-Object -Unique)
if ($resolvers.Count -gt 0) {
    $primaryDns = [string]$resolvers[0]
    Capture ping_internal { ping -n 3 -w 1000 $primaryDns }
    Capture nslookup_internal { nslookup google.com $primaryDns }
    Capture traceroute_internal { tracert -d -h 8 -w 750 $primaryDns }
}
if ($resolvers.Count -gt 1) {
    $backupDns = [string]$resolvers[1]
    Capture ping_internal_backup { ping -n 3 -w 1000 $backupDns }
}
Capture ping_external { ping -n 3 -w 1000 8.8.8.8 }
Capture nslookup_google { nslookup google.com 8.8.8.8 }
Capture traceroute_external { tracert -d -h 8 -w 750 8.8.8.8 }
if ($IncludeSensitive) {
    Capture getmac { getmac /v }
    Capture arp { arp -a }
    Capture netstat { netstat -an }
    Capture dns_cache { ipconfig /displaydns }
}
$result = [ordered]@{ platform = 'Windows'; hostname = $env:COMPUTERNAME; commands = $commands }
$folder = [Environment]::GetFolderPath('Desktop')
if (-not (Test-Path $folder)) { $folder = (Get-Location).Path }
$path = Join-Path $folder ("gmcs-client-diagnostics-{0}.json" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
$result | ConvertTo-Json -Depth 5 | Set-Content -Path $path -Encoding UTF8
Write-Host "Diagnostic report created: $path"
Write-Host 'Review it for IPs, adapter MACs, hostnames and any personal data before using the website Upload button.'
Write-Host 'Optional cache reset: run ipconfig /flushdns yourself if authorized. It is NOT performed by this script.'
