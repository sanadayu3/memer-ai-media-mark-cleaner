$ErrorActionPreference = "Stop"

$repo = "sanadayu3/memer-ai-media-mark-cleaner"
$assetName = "MemeR-AI图文视频印记数据清理-Codex-Skill.zip"
$checksumsName = "SHA256SUMS.txt"
$skillName = "memer-ai-media-mark-cleaner"
$skillsRoot = Join-Path $HOME ".codex\skills"
$destination = Join-Path $skillsRoot $skillName
$tempRoot = Join-Path ([IO.Path]::GetTempPath()) ("memer-ai-install-" + [Guid]::NewGuid().ToString("N"))

try {
    New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
    $headers = @{ "User-Agent" = "MemeR-AI-Skill-Installer" }
    $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$repo/releases/latest"
    $asset = $release.assets | Where-Object { $_.name -eq $assetName } | Select-Object -First 1
    $checksums = $release.assets | Where-Object { $_.name -eq $checksumsName } | Select-Object -First 1

    if (-not $asset) { throw "Release asset not found: $assetName" }
    if (-not $checksums) { throw "Release checksum file not found: $checksumsName" }

    $zipPath = Join-Path $tempRoot $assetName
    $checksumsPath = Join-Path $tempRoot $checksumsName
    Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri $asset.browser_download_url -OutFile $zipPath
    Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri $checksums.browser_download_url -OutFile $checksumsPath

    $expected = $null
    foreach ($line in Get-Content -LiteralPath $checksumsPath) {
        if ($line -match '^([0-9a-fA-F]{64})\s+\*?(.+)$' -and $Matches[2].Trim() -eq $assetName) {
            $expected = $Matches[1].ToUpperInvariant()
            break
        }
    }
    if (-not $expected) { throw "Checksum entry not found for $assetName" }

    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToUpperInvariant()
    if ($actual -ne $expected) { throw "SHA-256 verification failed." }

    $extractRoot = Join-Path $tempRoot "extracted"
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force
    $source = Join-Path $extractRoot $skillName
    if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md"))) {
        throw "Invalid Skill package: SKILL.md is missing."
    }

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
