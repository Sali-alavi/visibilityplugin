$reportFile = Join-Path `
    $PSScriptRoot `
    "core\report_generator.py"

if (-not (Test-Path $reportFile)) {
    throw "Active report_generator.py was not found: $reportFile"
}

$backupFile = (
    "$reportFile.backup_layout_" +
    (Get-Date -Format "yyyyMMdd_HHmmss")
)

Copy-Item `
    -Path $reportFile `
    -Destination $backupFile

$content = Get-Content `
    -Path $reportFile `
    -Raw `
    -Encoding UTF8

function Replace-RequiredRegex {
    param(
        [string]$InputText,
        [string]$Pattern,
        [string]$Replacement,
        [string]$Description
    )

    $matches = [regex]::Matches(
        $InputText,
        $Pattern,
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )

    if ($matches.Count -ne 1) {
        throw (
            "Patch stopped: expected exactly one match for " +
            "'$Description', but found $($matches.Count)."
        )
    }

    return [regex]::Replace(
        $InputText,
        $Pattern,
        $Replacement,
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )
}

# Reduce the elevation chart height to reserve space.
$content = Replace-RequiredRegex `
    -InputText $content `
    -Pattern 'elevation_rect = QRectF\(\s*content_rect\.left\(\),\s*summary_rect\.bottom\(\) \+ 19\.0,\s*content_rect\.width\(\),\s*\d+\.0,\s*\)' `
    -Replacement @'
elevation_rect = QRectF(
        content_rect.left(),
        summary_rect.bottom() + 19.0,
        content_rect.width(),
        170.0,
    )
'@ `
    -Description "elevation chart rectangle"

# Make the visibility ribbon more compact.
$content = Replace-RequiredRegex `
    -InputText $content `
    -Pattern 'ribbon_rect = QRectF\(\s*content_rect\.left\(\),\s*elevation_rect\.bottom\(\) \+ \d+\.0,\s*content_rect\.width\(\),\s*\d+\.0,\s*\)' `
    -Replacement @'
ribbon_rect = QRectF(
        content_rect.left(),
        elevation_rect.bottom() + 12.0,
        content_rect.width(),
        60.0,
    )
'@ `
    -Description "visibility ribbon rectangle"

# Enlarge the vertical viewing-angle chart substantially.
$content = Replace-RequiredRegex `
    -InputText $content `
    -Pattern 'angle_rect = QRectF\(\s*content_rect\.left\(\),\s*ribbon_rect\.bottom\(\) \+ \d+\.0,\s*content_rect\.width\(\),\s*\d+\.0,\s*\)' `
    -Replacement @'
angle_rect = QRectF(
        content_rect.left(),
        ribbon_rect.bottom() + 12.0,
        content_rect.width(),
        520.0,
    )
'@ `
    -Description "vertical viewing-angle chart rectangle"

# Move the legend slightly closer to the enlarged chart.
$content = $content.Replace(
@'
        angle_rect.bottom() + 15.0,
'@,
@'
        angle_rect.bottom() + 10.0,
'@
)

Set-Content `
    -Path $reportFile `
    -Value $content `
    -Encoding UTF8

Write-Host ""
Write-Host "Chart-layout patch completed successfully." -ForegroundColor Green
Write-Host "Backup file:" -ForegroundColor Yellow
Write-Host $backupFile
Write-Host ""
Write-Host "Vertical viewing-angle chart height is now 520.0." `
    -ForegroundColor Cyan