# GMCS Client Troubleshooting v2 - IT-reviewed source; execute explicitly or deploy via Intune.
# Downloading cannot and must not auto-execute this script.
# Saves the report locally first, then offers to submit it via a 10-minute one-use
# code created on the speed-test website. No bypass of PowerShell, SAC or TLS policies.
# Optional extra identifiers: -IncludeSensitive. Never run elevated just for diagnostics.
param(
    [switch]$IncludeSensitive,
    [string]$ServerUrl = 'https://10.250.31.192:18443',
    [string]$UploadCode = ''
)
$ErrorActionPreference = 'Continue'
Write-Host 'GMCS read-only troubleshooting. A JSON report will be saved on your Desktop.'
Write-Host 'Uploading is optional and needs a one-time code plus your explicit approval.'
function Capture([string]$Name, [scriptblock]$Block) {
    try {
        $value = (& $Block 2>&1 | Out-String)
        if ($value.Length -gt 2200) { $value = $value.Substring(0,2200) + "`n[truncated]" }
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
Write-Host 'The report may include the device hostname, IPs, DNS, adapters and network topology.'
Write-Host 'Open the JSON file to review it before choosing whether to upload.'
if ([string]::IsNullOrWhiteSpace($UploadCode)) {
    $UploadCode = Read-Host 'One-time upload code from completed GMCS speed test (press Enter to keep locally only)'
}
if (-not [string]::IsNullOrWhiteSpace($UploadCode)) {
    # Restrict report destinations; never post arbitrary URLs and never skip TLS verification.
    $uri = $null
    if (-not [Uri]::TryCreate($ServerUrl, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or
        ($uri.Host -ne '10.250.31.192' -and
         -not $uri.Host.EndsWith('.gmcs.k12.nm.us', [StringComparison]::OrdinalIgnoreCase))) {
        Write-Warning 'Invalid GMCS HTTPS server address. Report saved locally; upload not attempted.'
        exit 2
    }
    $consent = Read-Host 'Upload THIS REPORT to GMCS IT for troubleshooting? Type YES to submit'
    if ($consent -cne 'YES') {
        Write-Host 'Not submitted. The JSON report remains on your device.'
        exit 0
    }
    try {
        # Upload code is a short-lived, one-time secret, never printed in the report.
        $payload = [ordered]@{
            upload_code = $UploadCode.Trim()
            platform = $result.platform
            hostname = $result.hostname
            commands = $result.commands
        } | ConvertTo-Json -Depth 5 -Compress
        $endpoint = $ServerUrl.TrimEnd('/') + '/api/diagnostics/submit-pair'
        $response = Invoke-RestMethod -Uri $endpoint -Method Post -Body $payload -ContentType 'application/json' -TimeoutSec 20 -ErrorAction Stop
        if ($response.status -eq 'saved') {
            Write-Host ('GMCS IT received the diagnostic report for speed-test result #{0}.' -f $response.result_id)
        } else {
            Write-Warning 'Unexpected server response. Your original JSON report is preserved.'
        }
    } catch {
        Write-Warning 'Report could not be uploaded; it remains saved locally.'
        Write-Warning 'Check code expiry, same source network and that the server HTTPS certificate is trusted by Windows.'
        Write-Warning ('Details: {0}' -f $_.Exception.Message)
        exit 3
    }
} else {
    Write-Host 'No code entered. Report saved locally and NOT uploaded.'
}

Write-Host 'Optional cache reset: run ipconfig /flushdns yourself if authorized. It is NOT performed by this script.'
