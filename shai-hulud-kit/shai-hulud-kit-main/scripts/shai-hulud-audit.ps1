#Requires -Version 5.1
<#
.SYNOPSIS
    Shai-Hulud / TeamPCP supply chain audit — PowerShell, agent-friendly.

.DESCRIPTION
    Three modes: quick (default, current project, <30s), project (one path),
    deep (full machine). Designed for Claude Code integration via -Json flag.

    Primary IOC source: OSV.dev batch API (free, no key, includes Socket data).
    Cache TTL: 15 minutes by default for repeated quick scans.

.PARAMETER Mode
    quick | project | deep | status

.PARAMETER Json
    Emit final result as a JSON blob on stdout (for agent consumption).
    Progress and findings go to stderr; only JSON to stdout.

.PARAMETER FailOnLevel
    1 = exit non-zero on warnings+, 2 = exit non-zero only on alerts (default).

.EXAMPLE
    .\shai-hulud-audit.ps1                       # quick scan of cwd / git root
    .\shai-hulud-audit.ps1 -Mode deep            # full machine scan
    .\shai-hulud-audit.ps1 -Mode quick -Json     # JSON for agents
    .\shai-hulud-audit.ps1 -Mode status          # last scan summary
#>

[CmdletBinding()]
param(
    [ValidateSet("quick","project","deep","status")]
    [string]$Mode = "quick",
    [string]$ProjectPath = "",
    [int]$DaysBack = 30,
    [string[]]$DevRoots = @(
        "$env:USERPROFILE\Documents",
        "$env:USERPROFILE\Desktop",
        "$env:USERPROFILE\source",
        "C:\Projects","C:\Dev","C:\code"
    ),
    [string]$OutputDir = "",
    [string]$GitHubUser = "",
    [string]$GitHubToken = "",
    [switch]$Json,
    [switch]$Quiet,
    [switch]$SkipOsv,
    [switch]$NoCache,
    [int]$CacheTtlMin = 15,
    [ValidateSet(1,2)][int]$FailOnLevel = 2,
    [int]$TimeoutSec = 30
)

# TLS 1.2 enforcement (PS 5.1 default is TLS 1.0 on some Windows builds)
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch {}

$ScriptStart = Get-Date
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$AuditRoot = Join-Path $env:USERPROFILE "shai-hulud-audit"
$CacheDir = Join-Path $AuditRoot "cache"
$LastRunFile = Join-Path $AuditRoot "last_run.json"

if (-not $OutputDir) { $OutputDir = Join-Path $AuditRoot "audit_${Timestamp}_${Mode}" }
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
New-Item -ItemType Directory -Path $CacheDir -Force | Out-Null

$ReportFile = Join-Path $OutputDir "report.txt"
$CsvFile = Join-Path $OutputDir "packages.csv"
$OsvCsvFile = Join-Path $OutputDir "osv_findings.csv"
$IocFile = Join-Path $OutputDir "ioc_hits.txt"
$JsonFile = Join-Path $OutputDir "result.json"
$Cutoff = (Get-Date).AddDays(-$DaysBack)

"Shai-Hulud Audit | Mode: $Mode | $(Get-Date) | Days back: $DaysBack" | Set-Content $ReportFile

$AllFindings = [System.Collections.Generic.List[PSObject]]@()
$script:AlertCount = 0
$script:WarnCount = 0

function Add-Finding {
    param([string]$Section, [string]$Type, [string]$Level, [string]$Message, [hashtable]$Details = @{})
    $script:AllFindings.Add([PSCustomObject]@{
        Section=$Section; Type=$Type; Level=$Level; Message=$Message
        Details=$Details; Timestamp=(Get-Date).ToString("o")
    }) | Out-Null
    if ($Level -eq "ALERT") { $script:AlertCount++ }
    if ($Level -eq "WARN") { $script:WarnCount++ }
}

$Silent = $Json -or $Quiet

function Write-Section {
    param([string]$Title)
    if ($Silent) { return }
    $sep = "=" * 64
    $msg = "`n$sep`n  $Title`n$sep"
    [Console]::Error.WriteLine($msg)
    Add-Content -Path $ReportFile -Value $msg
}

function Write-Out {
    param([string]$Msg, [string]$Level = "INFO")
    $line = "[$Level] $Msg"
    Add-Content -Path $ReportFile -Value $line
    if ($Silent) { return }
    $palette = @{ INFO="White"; WARN="Yellow"; ALERT="Red"; OK="Green" }
    $color = $palette[$Level]; if (-not $color) { $color = "White" }
    $oldColor = [Console]::ForegroundColor
    try {
        [Console]::ForegroundColor = $color
        [Console]::Error.WriteLine($line)
    } finally { [Console]::ForegroundColor = $oldColor }
}

function Write-Ioc {
    param([string]$Type, [string]$Detail, [hashtable]$Details = @{})
    Add-Content -Path $IocFile -Value "$Type | $Detail"
    Write-Out "$Type | $Detail" "ALERT"
    Add-Finding -Section "IOC" -Type $Type -Level "ALERT" -Message $Detail -Details $Details
}

function Test-CommandExists { param([string]$Name); return [bool](Get-Command -Name $Name -ErrorAction SilentlyContinue) }

# --- STATUS mode short-circuit ---
if ($Mode -eq "status") {
    if (Test-Path $LastRunFile) {
        $last = Get-Content $LastRunFile -Raw | ConvertFrom-Json
        if ($Json) { $last | ConvertTo-Json -Depth 8 }
        else {
            Write-Host "Last scan: $($last.timestamp)" -ForegroundColor Cyan
            Write-Host "Mode     : $($last.mode)" -ForegroundColor Cyan
            Write-Host "Duration : $($last.duration_seconds)s" -ForegroundColor Cyan
            Write-Host "Alerts   : $($last.summary.alert_count)" -ForegroundColor $(if ($last.summary.alert_count -gt 0) { "Red" } else { "Green" })
            Write-Host "Warnings : $($last.summary.warn_count)" -ForegroundColor $(if ($last.summary.warn_count -gt 0) { "Yellow" } else { "Green" })
            Write-Host "Exit code: $($last.summary.exit_code)"
        }
    } else {
        if ($Json) { '{"error":"no prior scan found"}' }
        else { Write-Host "No prior scan found." -ForegroundColor Yellow }
    }
    exit 0
}

# --- Scope resolution ---
function Find-GitRoot {
    param([string]$StartPath)
    $current = (Resolve-Path $StartPath -ErrorAction SilentlyContinue).Path
    if (-not $current) { return $null }
    while ($current -and (Test-Path $current)) {
        if (Test-Path (Join-Path $current ".git")) { return $current }
        $parent = Split-Path $current -Parent
        if ($parent -eq $current) { return $null }
        $current = $parent
    }
    return $null
}

$ScanScope = @()
switch ($Mode) {
    "quick" {
        $gitRoot = Find-GitRoot -StartPath (Get-Location).Path
        $ScanScope = @($(if ($gitRoot) { $gitRoot } else { (Get-Location).Path }))
    }
    "project" {
        if (-not $ProjectPath -or -not (Test-Path $ProjectPath)) {
            Write-Out "Mode 'project' requires valid -ProjectPath" "ALERT"; exit 3
        }
        $ScanScope = @((Resolve-Path $ProjectPath).Path)
    }
    "deep" {
        $ScanScope = $DevRoots | Where-Object { Test-Path $_ }
    }
}

Write-Section "SCAN CONFIG"
Write-Out "Mode: $Mode | Scope: $($ScanScope -join ', ') | DaysBack: $DaysBack" "INFO"

# --- IOC lists ---
$KnownBadNpm = [System.Collections.Generic.HashSet[string]]@(
    "@antv/g2","@antv/g6","@antv/x6","@antv/l7","@antv/s2","@antv/f2","@antv/g",
    "@antv/g2plot","@antv/graphin","@antv/data-set","@antv/scale",
    "echarts-for-react","timeago.js","size-sensor","canvas-nest.js",
    "@tanstack/react-query","@tanstack/vue-query","@tanstack/query-core",
    "@tanstack/react-table","@tanstack/table-core","@tanstack/react-virtual",
    "@tanstack/virtual-core","@tanstack/react-router","@tanstack/router-core",
    "@tanstack/react-form","@tanstack/form-core","@tanstack/store",
    "@bitwarden/cli","@mistralai/mistralai","@squawk/squawk"
)
$KnownBadPypi = [System.Collections.Generic.HashSet[string]]@("durabletask","fast-agent-mcp")
$C2Domains = @("t.m-kosche.com","audit.checkmarx.cx","checkmarx.cx","npm.componentjs.com","registry.npmjs.cx","duluh-iahs.xyz","team-pcp.com")
$C2Ips = @("94.154.172.43")
# .claude/ and .vscode/ persistence indicators (TeamPCP, May 2026)
$PersistenceFiles = @(".claude\execution.js",".claude\setup.mjs",".vscode\setup.mjs")

# --- OSV query with cache ---
function Get-OsvCacheKey {
    param([string]$N, [string]$V, [string]$E)
    $raw = "$E|$N|$V"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($raw)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace("-","").ToLower() }
    finally { $sha.Dispose() }
}
function Get-OsvCached {
    param([string]$Key)
    if ($NoCache) { return $null }
    $path = Join-Path $CacheDir "$Key.json"
    if (-not (Test-Path $path)) { return $null }
    if (((Get-Date) - (Get-Item $path).LastWriteTime).TotalMinutes -gt $CacheTtlMin) { return $null }
    try { Get-Content $path -Raw | ConvertFrom-Json } catch { $null }
}
function Set-OsvCached {
    param([string]$Key, [object]$Value)
    if ($NoCache) { return }
    try { ($Value | ConvertTo-Json -Depth 10 -Compress) | Set-Content (Join-Path $CacheDir "$Key.json") -Encoding UTF8 } catch {}
}

function Invoke-OsvBatchQuery {
    param([object[]]$Packages, [int]$BatchSize = 500)
    $findings = [System.Collections.Generic.List[PSObject]]@()
    $needQuery = [System.Collections.Generic.List[PSObject]]@()
    foreach ($pkg in $Packages) {
        $key = Get-OsvCacheKey -N $pkg.Name -V $pkg.Version -E $pkg.Ecosystem
        $c = Get-OsvCached -Key $key
        if ($c -ne $null) {
            if ($c.vulns) {
                foreach ($v in $c.vulns) {
                    $findings.Add([PSCustomObject]@{
                        Ecosystem=$pkg.Ecosystem; Name=$pkg.Name; Version=$pkg.Version
                        AdvisoryId=$v.id; IsMalicious=($v.id -like "MAL-*")
                        Source=$pkg.Source; Location=$pkg.Location; FromCache=$true
                    }) | Out-Null
                }
            }
        } else {
            $pkg | Add-Member -NotePropertyName "_key" -NotePropertyValue $key -Force
            $needQuery.Add($pkg) | Out-Null
        }
    }
    Write-Out "OSV cache: $($Packages.Count - $needQuery.Count) hit, $($needQuery.Count) fetch" "INFO"
    if ($needQuery.Count -eq 0) { return $findings }
    $total = [Math]::Ceiling($needQuery.Count / $BatchSize)
    for ($i = 0; $i -lt $needQuery.Count; $i += $BatchSize) {
        $end = [Math]::Min($i + $BatchSize - 1, $needQuery.Count - 1)
        $batch = $needQuery[$i..$end]
        $queries = foreach ($p in $batch) { @{ package=@{name=$p.Name;ecosystem=$p.Ecosystem}; version=$p.Version } }
        $body = @{ queries = $queries } | ConvertTo-Json -Depth 6 -Compress
        $attempt = 0; $ok = $false
        while (-not $ok -and $attempt -lt 3) {
            $attempt++
            try {
                $resp = Invoke-RestMethod -Uri "https://api.osv.dev/v1/querybatch" -Method Post -Body $body `
                    -ContentType "application/json" -TimeoutSec $TimeoutSec -ErrorAction Stop
                for ($j = 0; $j -lt $batch.Count; $j++) {
                    $p = $batch[$j]; $r = $resp.results[$j]
                    Set-OsvCached -Key $p._key -Value $r
                    if ($r.vulns) {
                        foreach ($v in $r.vulns) {
                            $findings.Add([PSCustomObject]@{
                                Ecosystem=$p.Ecosystem; Name=$p.Name; Version=$p.Version
                                AdvisoryId=$v.id; IsMalicious=($v.id -like "MAL-*")
                                Source=$p.Source; Location=$p.Location; FromCache=$false
                            }) | Out-Null
                        }
                    }
                }
                $ok = $true
            } catch {
                if ($attempt -lt 3) { Start-Sleep -Seconds (2 * $attempt) }
                else { Write-Out "OSV batch failed: $($_.Exception.Message)" "WARN" }
            }
        }
        Start-Sleep -Milliseconds 200
    }
    return $findings
}

# --- Package inventory ---
$AllPackages = [System.Collections.Generic.List[PSObject]]@()

# npm: scoped namespace handling fixed (descends into @scope/)
Write-Section "NPM PACKAGES"
$npmCount = 0
foreach ($scope in $ScanScope) {
    $depth = if ($Mode -eq "deep") { 4 } else { 6 }
    $nmDirs = Get-ChildItem -Path $scope -Filter "node_modules" -Directory -Recurse -Depth $depth -ErrorAction SilentlyContinue |
              Where-Object { $_.FullName -notmatch "node_modules\\.*node_modules" }
    foreach ($nm in $nmDirs) {
        foreach ($entry in (Get-ChildItem $nm.FullName -Directory -ErrorAction SilentlyContinue)) {
            $items = @()
            if ($entry.Name -like "@*") {
                $items = Get-ChildItem $entry.FullName -Directory -ErrorAction SilentlyContinue |
                         ForEach-Object { @{ Path=$_.FullName; Name="$($entry.Name)/$($_.Name)"; LastWrite=$_.LastWriteTime } }
            } else {
                $items = @(@{ Path=$entry.FullName; Name=$entry.Name; LastWrite=$entry.LastWriteTime })
            }
            foreach ($it in $items) {
                if ($it.LastWrite -lt $Cutoff) { continue }
                $version = "0.0.0"; $hasInstall = $false
                $pkgJson = Join-Path $it.Path "package.json"
                if (Test-Path $pkgJson) {
                    try {
                        $pkg = Get-Content $pkgJson -Raw | ConvertFrom-Json
                        if ($pkg.version) { $version = "$($pkg.version)" }
                        if ($pkg.scripts -and ($pkg.scripts.PSObject.Properties.Name -match "^(pre|post)?install$")) { $hasInstall = $true }
                    } catch {}
                }
                $isBad = $KnownBadNpm.Contains($it.Name)
                $AllPackages.Add([PSCustomObject]@{
                    Ecosystem="npm"; Name=$it.Name; Version=$version
                    InstallDate=$it.LastWrite; HasInstallScript=$hasInstall
                    Source="npm-local"; Location=$nm.Parent.FullName; IsKnownBad=$isBad
                }) | Out-Null
                if ($isBad) { Write-Ioc "NPM_KNOWN_BAD" "$($it.Name)@$version in $($nm.Parent.FullName)" @{name=$it.Name;version=$version} }
                $npmCount++
            }
        }
    }
}
Write-Out "npm packages in window: $npmCount" "INFO"

# PyPI: METADATA reading for accurate names/versions
Write-Section "PYPI PACKAGES"
$SitePkgs = [System.Collections.Generic.HashSet[string]]@()
if ($Mode -eq "deep") {
    foreach ($py in @((Get-Command python -ErrorAction SilentlyContinue).Source,
                       (Get-Command python3 -ErrorAction SilentlyContinue).Source,
                       (Get-Command py -ErrorAction SilentlyContinue).Source) | Where-Object { $_ }) {
        try {
            $out = & $py -c "import site,json; print(json.dumps(site.getsitepackages()))" 2>$null
            if ($out) { ($out | ConvertFrom-Json) | ForEach-Object { if (Test-Path $_) { [void]$SitePkgs.Add($_) } } }
        } catch {}
    }
}
foreach ($scope in $ScanScope) {
    Get-ChildItem -Path $scope -Recurse -Filter "site-packages" -Directory -Depth 6 -ErrorAction SilentlyContinue |
        ForEach-Object { [void]$SitePkgs.Add($_.FullName) }
}
$pypiCount = 0
foreach ($sd in $SitePkgs) {
    Get-ChildItem $sd -Filter "*.dist-info" -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $Cutoff } |
        ForEach-Object {
            $name = $null; $ver = $null
            $mf = Join-Path $_.FullName "METADATA"
            if (Test-Path $mf) {
                foreach ($ml in (Get-Content $mf -TotalCount 10 -ErrorAction SilentlyContinue)) {
                    if ($ml -match "^Name:\s*(.+)$") { $name = $Matches[1].Trim().ToLower() }
                    if ($ml -match "^Version:\s*(.+)$") { $ver = $Matches[1].Trim() }
                }
            }
            if (-not $name -or -not $ver) {
                $base = $_.Name -replace "\.dist-info$",""; $parts = $base -split "-"
                $ver = $parts[-1]; $name = ($parts[0..($parts.Count-2)] -join "-").ToLower()
            }
            $isBad = $KnownBadPypi.Contains($name)
            $AllPackages.Add([PSCustomObject]@{
                Ecosystem="PyPI"; Name=$name; Version=$ver; InstallDate=$_.LastWriteTime
                HasInstallScript=$false; Source="pypi"; Location=$sd; IsKnownBad=$isBad
            }) | Out-Null
            if ($isBad) { Write-Ioc "PYPI_KNOWN_BAD" "$name==$ver in $sd" @{name=$name;version=$ver} }
            $pypiCount++
        }
}
Write-Out "PyPI packages in window: $pypiCount" "INFO"

# Surface install scripts
$AllPackages | Where-Object { $_.HasInstallScript -and -not $_.IsKnownBad } | ForEach-Object {
    Write-Out "Install script: $($_.Name)@$($_.Version) in $($_.Location)" "WARN"
    Add-Finding -Section "install_scripts" -Type "has_install_script" -Level "WARN" `
        -Message "$($_.Name)@$($_.Version)" -Details @{name=$_.Name;version=$_.Version;path=$_.Location}
}

# OSV live query
$OsvFindings = [System.Collections.Generic.List[PSObject]]@()
if (-not $SkipOsv -and $AllPackages.Count -gt 0) {
    Write-Section "OSV.DEV LIVE QUERY"
    $deduped = $AllPackages | Group-Object { "$($_.Ecosystem)|$($_.Name)|$($_.Version)" } | ForEach-Object { $_.Group[0] }
    Write-Out "Querying OSV for $($deduped.Count) unique packages..." "INFO"
    $OsvFindings = Invoke-OsvBatchQuery -Packages ($deduped | ForEach-Object {
        [PSCustomObject]@{ Ecosystem=$_.Ecosystem; Name=$_.Name; Version=$_.Version; Source=$_.Source; Location=$_.Location }
    })
    $mal = @($OsvFindings | Where-Object { $_.IsMalicious })
    $vul = @($OsvFindings | Where-Object { -not $_.IsMalicious })
    if ($mal.Count -gt 0) {
        Write-Out "MALICIOUS: $($mal.Count) hits" "ALERT"
        foreach ($m in $mal) {
            Write-Ioc "OSV_MALICIOUS" "$($m.Ecosystem)/$($m.Name)@$($m.Version) | $($m.AdvisoryId)" `
                @{name=$m.Name;version=$m.Version;ecosystem=$m.Ecosystem;advisory=$m.AdvisoryId;location=$m.Location}
        }
    } else { Write-Out "No malicious (MAL-*) findings." "OK" }
    if ($vul.Count -gt 0) {
        Write-Out "Vulnerable packages: $($vul.Count)" "WARN"
        $vul | Group-Object Name | Sort-Object Count -Descending | Select-Object -First 10 | ForEach-Object {
            $p = $_.Group[0]
            Write-Out "  $($p.Ecosystem)/$($p.Name)@$($p.Version): $($_.Count) advisories" "WARN"
            Add-Finding -Section "osv" -Type "vulnerable_package" -Level "WARN" `
                -Message "$($p.Name)@$($p.Version)" `
                -Details @{name=$p.Name;version=$p.Version;ecosystem=$p.Ecosystem;advisory_count=$_.Count}
        }
    }
}

# C2 check — deep only
if ($Mode -eq "deep") {
    Write-Section "C2 DOMAIN INDICATORS"
    $c2Found = $false
    try {
        $dns = Get-DnsClientCache -ErrorAction Stop
        foreach ($d in $C2Domains) {
            if ($dns | Where-Object { $_.Entry -match [regex]::Escape($d) }) {
                Write-Ioc "C2_DNS_CACHE" "Resolved: $d" @{domain=$d;source="dns_cache"}; $c2Found = $true
            }
        }
    } catch {}
    if (Test-Path "C:\Windows\System32\drivers\etc\hosts") {
        $hl = Get-Content "C:\Windows\System32\drivers\etc\hosts" -ErrorAction SilentlyContinue
        foreach ($d in $C2Domains) {
            if ($hl | Where-Object { $_ -match [regex]::Escape($d) }) {
                Write-Ioc "C2_HOSTS_FILE" "$d" @{domain=$d;source="hosts_file"}; $c2Found = $true
            }
        }
    }
    if (-not $c2Found) { Write-Out "No C2 domain indicators." "OK" }
}

# Workflow tampering
Write-Section "WORKFLOW TAMPER CHECK"
$wfCount = 0
foreach ($scope in $ScanScope) {
    Get-ChildItem -Path $scope -Recurse -Include "*.yml","*.yaml" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match [regex]::Escape("\.github\workflows\") -and $_.LastWriteTime -ge $Cutoff } |
        ForEach-Object {
            $wfCount++
            $content = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
            $reason = $null
            if ($content -match "curl\s+[^|\n]+\|(?:\s*[^|\n]+\|)*\s*(?:[\w/.+\-]+/)?(?:sudo(?:\s[^|\n]*?)?\s+)?(?:[\w/.+\-]+/)?(sh|bash|zsh|python[\d.]*)\b") { $reason = "pipe-to-shell" }
            elseif ($content -match "wget\s+[^|\n]+-O-?\s*\|") { $reason = "wget pipe-to-shell" }
            elseif ($content -match "base64\s+(-d|--decode)") { $reason = "base64 decode" }
            elseif ($content -match "eval\s+(\`\`|\$\(|`)") { $reason = "eval execution" }
            elseif ($content -match "ACTIONS_RUNTIME_TOKEN|ACTIONS_CACHE_URL") { $reason = "runner token exfil pattern" }
            if ($reason) { Write-Ioc "WORKFLOW_SUSPICIOUS" "$($_.FullName) | $reason" @{file=$_.FullName;reason=$reason} }
            else {
                Write-Out "Modified workflow: $($_.FullName)" "WARN"
                Add-Finding -Section "workflows" -Type "modified_workflow" -Level "WARN" `
                    -Message $_.FullName -Details @{file=$_.FullName}
            }
        }
}
if ($wfCount -eq 0) { Write-Out "No recently modified workflows." "OK" }

# Persistence file check (TeamPCP .claude/ + .vscode/ payloads)
Write-Section "PERSISTENCE FILE CHECK"
$persistCount = 0
foreach ($scope in $ScanScope) {
    foreach ($rel in $PersistenceFiles) {
        Get-ChildItem -Path $scope -Recurse -Filter (Split-Path $rel -Leaf) -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match [regex]::Escape($rel) } |
            ForEach-Object {
                Write-Ioc "PERSISTENCE_FILE" "$($_.FullName) (matches $rel)" `
                    @{file=$_.FullName;pattern=$rel}
                $persistCount++
            }
    }
}
if ($persistCount -eq 0) { Write-Out "No persistence files." "OK" }

# Git anomaly check
Write-Section "GIT 2099-DATE COMMITS"
$gitAnoms = 0
foreach ($scope in $ScanScope) {
    $depth = if ($Mode -eq "deep") { 5 } else { 2 }
    Get-ChildItem -Path $scope -Recurse -Filter ".git" -Directory -Depth $depth -ErrorAction SilentlyContinue |
        ForEach-Object {
            $repo = $_.Parent.FullName
            try {
                & git -C $repo log --format="%H %ai %s" --all 2>$null |
                    Where-Object { $_ -match "^[0-9a-f]{40} 209\d" } |
                    ForEach-Object { Write-Ioc "GIT_SPOOFED_DATE" "$repo | $_" @{repo=$repo;entry=$_}; $gitAnoms++ }
            } catch {}
        }
}
if ($gitAnoms -eq 0) { Write-Out "No spoofed-date commits." "OK" }

# Deep mode only: env, history, creds
if ($Mode -eq "deep") {
    Write-Section "ENVIRONMENT VARS"
    $patterns = @("^OP_","PASS","SECRET","TOKEN","API_KEY","^AWS_","^GITHUB_","^GH_","^NPM_TOKEN","ANTHROPIC","PRIVATE_KEY","CREDENTIAL","^BW_")
    $found = [System.Collections.Generic.List[string]]@()
    foreach ($s in @("User","Machine","Process")) {
        foreach ($k in [System.Environment]::GetEnvironmentVariables($s).Keys) {
            foreach ($p in $patterns) { if ($k -match $p) { $found.Add("[$s] $k") | Out-Null; break } }
        }
    }
    $found = $found | Sort-Object -Unique
    if ($found.Count -gt 0) {
        Write-Out "$($found.Count) sensitive env vars present" "WARN"
        Add-Finding -Section "env_vars" -Type "sensitive_env" -Level "WARN" `
            -Message "$($found.Count) sensitive env vars" -Details @{vars=$found}
    } else { Write-Out "No sensitive env vars." "OK" }

    Write-Section "CREDENTIAL FILES"
    $creds = [System.Collections.Generic.List[PSObject]]@()
    foreach ($loc in @($env:USERPROFILE,"$env:USERPROFILE\.ssh","$env:APPDATA\npm","$env:USERPROFILE\.aws")) {
        if (-not (Test-Path $loc)) { continue }
        foreach ($p in @("*.env","*.env.local","*.env.production",".npmrc",".pypirc",".netrc","credentials","*.pem","id_rsa","id_ed25519")) {
            Get-ChildItem -Path $loc -Filter $p -Force -ErrorAction SilentlyContinue |
                ForEach-Object { $creds.Add([PSCustomObject]@{File=$_.FullName;Modified=$_.LastWriteTime;Bytes=$_.Length}) | Out-Null }
        }
    }
    if ($creds.Count -gt 0) {
        Write-Out "Credential files present (rotate if compromised):" "WARN"
        $creds | ForEach-Object { Write-Out "  $($_.File)" "WARN" }
    } else { Write-Out "No credential files in scanned locations." "OK" }
}

# GitHub exfil check
if ($GitHubUser -or $GitHubToken) {
    Write-Section "GITHUB EXFIL REPO CHECK"
    try {
        $hdrs = @{ "User-Agent"="ShaiHulud-Audit/3.0"; "Accept"="application/vnd.github+json" }
        if ($GitHubToken) { $hdrs["Authorization"] = "Bearer $GitHubToken"; $url = "https://api.github.com/user/repos?per_page=100&type=all" }
        else { $url = "https://api.github.com/users/$GitHubUser/repos?per_page=100" }
        $repos = Invoke-RestMethod -Uri $url -Headers $hdrs -TimeoutSec 20 -ErrorAction Stop
        $sigs = @("niagA oG eW ereH :duluH-iahS","Shai-Hulud","duluH-iahS","TeamPCP","A Gift From TeamPCP","LongLiveTheResistanceAgainstMachines")
        $hits = 0
        foreach ($r in $repos) {
            $blob = "$($r.name) | $($r.description)"
            foreach ($s in $sigs) {
                if ($blob -like "*$s*") {
                    Write-Ioc "GITHUB_EXFIL_REPO" "$($r.full_name) | $($r.description) | $($r.html_url)" `
                        @{repo=$r.full_name;url=$r.html_url;description=$r.description}
                    $hits++; break
                }
            }
        }
        if ($hits -eq 0) { Write-Out "No exfil-indicator repos." "OK" }
    } catch { Write-Out "GitHub API check failed: $($_.Exception.Message)" "WARN" }
}

# Optional CLI integrations
if ($Mode -in @("deep","project")) {
    if (Test-CommandExists "pip-audit") {
        Write-Section "PIP-AUDIT"
        try {
            $raw = & pip-audit --format=json 2>$null
            if ($raw) {
                $data = $raw | ConvertFrom-Json
                $vp = @($data.dependencies | Where-Object { $_.vulns.Count -gt 0 })
                if ($vp.Count -gt 0) {
                    Write-Out "pip-audit: $($vp.Count) vulnerable package(s)" "WARN"
                    foreach ($v in $vp) { Write-Out "  $($v.name)==$($v.version)" "WARN" }
                } else { Write-Out "pip-audit: clean" "OK" }
            }
        } catch {}
    }
}

# Summary + output
Write-Section "SUMMARY"
$AllPackages | Export-Csv -Path $CsvFile -NoTypeInformation -Encoding UTF8
$OsvFindings | Export-Csv -Path $OsvCsvFile -NoTypeInformation -Encoding UTF8
$elapsed = [math]::Round(((Get-Date) - $ScriptStart).TotalSeconds, 1)

$exitCode = 0
if ($script:AlertCount -gt 0) { $exitCode = 2 }
elseif ($script:WarnCount -gt 0 -and $FailOnLevel -le 1) { $exitCode = 1 }

$result = [PSCustomObject]@{
    version="3.0"; mode=$Mode; scope=$ScanScope; timestamp=$ScriptStart.ToString("o")
    duration_seconds=$elapsed; output_dir=$OutputDir; report_path=$ReportFile
    summary=[PSCustomObject]@{
        packages_scanned=$AllPackages.Count
        npm_packages=($AllPackages | Where-Object { $_.Ecosystem -eq "npm" }).Count
        pypi_packages=($AllPackages | Where-Object { $_.Ecosystem -eq "PyPI" }).Count
        osv_malicious=($OsvFindings | Where-Object { $_.IsMalicious }).Count
        osv_vulnerable=($OsvFindings | Where-Object { -not $_.IsMalicious }).Count
        install_scripts=($AllPackages | Where-Object { $_.HasInstallScript }).Count
        known_bad_offline=($AllPackages | Where-Object { $_.IsKnownBad }).Count
        alert_count=$script:AlertCount; warn_count=$script:WarnCount; exit_code=$exitCode
    }
    alerts=@($AllFindings | Where-Object { $_.Level -eq "ALERT" })
    warnings=@($AllFindings | Where-Object { $_.Level -eq "WARN" })
}

$nextActions = [System.Collections.Generic.List[string]]@()
if ($script:AlertCount -gt 0) {
    $nextActions.Add("CRITICAL: do not commit. Treat machine as potentially compromised.") | Out-Null
    $nextActions.Add("Rotate all credentials accessible from this machine.") | Out-Null
    foreach ($a in ($AllFindings | Where-Object { $_.Level -eq "ALERT" })) {
        $nextActions.Add("Review: $($a.Type) — $($a.Message)") | Out-Null
    }
} elseif ($script:WarnCount -gt 0) { $nextActions.Add("Warnings present — review before commit.") | Out-Null }
else { $nextActions.Add("Clean. Safe to proceed.") | Out-Null }
$result | Add-Member -NotePropertyName "next_actions" -NotePropertyValue $nextActions

$result | ConvertTo-Json -Depth 10 | Set-Content -Path $JsonFile -Encoding UTF8
$result | ConvertTo-Json -Depth 10 | Set-Content -Path $LastRunFile -Encoding UTF8

Write-Out "Duration: ${elapsed}s | Packages: $($AllPackages.Count) | Alerts: $script:AlertCount | Warns: $script:WarnCount | Exit: $exitCode" "INFO"

if ($Json) { $result | ConvertTo-Json -Depth 10 }
elseif (-not $Quiet) {
    Write-Host "`nReport: $OutputDir" -ForegroundColor Green
    if ($script:AlertCount -gt 0) {
        Write-Host "`n!! CRITICAL — do not commit." -ForegroundColor Red
        $nextActions | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    } elseif ($script:WarnCount -gt 0) {
        Write-Host "`nWarnings — review:" -ForegroundColor Yellow
        $nextActions | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
    } else { Write-Host "`nClean. Safe to proceed." -ForegroundColor Green }
}

exit $exitCode
