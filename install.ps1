$ErrorActionPreference = "Stop"

$repo = "sanadayu3/memer-ai-media-mark-cleaner"
$skillAssetName = "MemeR-AI图文视频印记数据清理-Codex-Skill.zip"
$runtimeAssetName = "MemeR-AI图文视频印记数据清理-portable.zip"
$checksumsName = "SHA256SUMS.txt"
$skillName = "memer-ai-media-mark-cleaner"
$skillsRoot = Join-Path $HOME ".codex\skills"
$destination = Join-Path $skillsRoot $skillName
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("memer-ai-install-" + [Guid]::NewGuid().ToString("N"))

try {
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    $headers = @{ "User-Agent" = "MemeR-AI-Skill-Installer" }
    $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$repo/releases/latest"
    $skillAsset = $release.assets | Where-Object { $_.name -eq $skillAssetName } | Select-Object -First 1
    $runtimeAsset = $release.assets | Where-Object { $_.name -eq $runtimeAssetName } | Select-Object -First 1
    $checksums = $release.assets | Where-Object { $_.name -eq $checksumsName } | Select-Object -First 1

    if (-not $skillAsset) { throw "Release asset not found: $skillAssetName" }
    if (-not $runtimeAsset) { throw "Release asset not found: $runtimeAssetName" }
    if (-not $checksums) { throw "Release checksum file not found: $checksumsName" }

    $skillZipPath = Join-Path $tempRoot $skillAssetName
    $runtimeZipPath = Join-Path $tempRoot $runtimeAssetName
    $checksumsPath = Join-Path $tempRoot $checksumsName
    Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri $skillAsset.browser_download_url -OutFile $skillZipPath
    Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri $runtimeAsset.browser_download_url -OutFile $runtimeZipPath
    Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri $checksums.browser_download_url -OutFile $checksumsPath

    foreach ($download in @(
        @{ Name = $skillAssetName; Path = $skillZipPath },
        @{ Name = $runtimeAssetName; Path = $runtimeZipPath }
    )) {
        $expected = $null
        foreach ($line in Get-Content -LiteralPath $checksumsPath) {
            if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+)$' -and $Matches[2].Trim() -eq $download.Name) {
                $expected = $Matches[1].ToUpperInvariant()
                break
            }
        }
        if (-not $expected) { throw "Checksum entry not found for $($download.Name)" }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $download.Path).Hash.ToUpperInvariant()
        if ($actual -ne $expected) { throw "SHA-256 verification failed for $($download.Name)." }
    }

    $skillExtractRoot = Join-Path $tempRoot "skill"
    $runtimeExtractRoot = Join-Path $tempRoot "runtime"
    Expand-Archive -LiteralPath $skillZipPath -DestinationPath $skillExtractRoot -Force
    Expand-Archive -LiteralPath $runtimeZipPath -DestinationPath $runtimeExtractRoot -Force
    $source = Join-Path $skillExtractRoot $skillName
    if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md"))) {
        throw "Invalid Skill package: SKILL.md is missing."
    }
    $runtimeSource = Join-Path $runtimeExtractRoot "MemeR-AI图文视频印记数据清理"
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeSource "MemeR-AI图文视频印记数据清理.exe"))) {
        throw "Invalid runtime package: GUI executable is missing."
    }
    $assetsRoot = Join-Path $source "assets"
    New-Item -ItemType Directory -Force -Path $assetsRoot | Out-Null
    Copy-Item -LiteralPath $runtimeSource -Destination (Join-Path $assetsRoot "app") -Recurse

    New-Item -ItemType Directory -Force -Path $skillsRoot | Out-Null
    if (Test-Path -LiteralPath $destination) {
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backup = "$destination.backup-$timestamp"
        Move-Item -LiteralPath $destination -Destination $backup
        Write-Host "Previous version backed up to: $backup"
    }
    Copy-Item -LiteralPath $source -Destination $destination -Recurse

    Write-Host "Installed: $destination" -ForegroundColor Green
    Write-Host "Restart Codex, then invoke: `$memer-ai-media-mark-cleaner"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force
    }
}
