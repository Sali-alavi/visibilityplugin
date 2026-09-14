$source = "D:\Sali_IPRO\1.projects\3DVisualiyation\code\visibilityplugin\terrain_visibility_change\core\report_generator.py"

if (-not (Test-Path $source)) {
    throw "Source file not found: $source"
}

$backup = "$source.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item -Path $source -Destination $backup

$content = Get-Content -Path $source -Raw -Encoding UTF8

# ---------------------------------------------------------------------
# 1. Add angle-chart display threshold.
# ---------------------------------------------------------------------
if ($content -notmatch "ANGLE_CHART_MIN_DEG") {
    $content = $content.Replace(
        "BYTE_NODATA = 255",
@"
BYTE_NODATA = 255

# PDF display threshold for vertical viewing-angle charts.
# Values below this threshold are hidden in the PDF chart only.
# Raster data, CSV files and profile-summary statistics remain unchanged.
ANGLE_CHART_MIN_DEG = -10.0
"@
    )
}

# ---------------------------------------------------------------------
# 2. Filter angle values before calculating the PDF chart Y axis.
# ---------------------------------------------------------------------
$oldValuesBlock = @'
    if not distances or not values:
        _draw_text(
'@

$newValuesBlock = @'
    # Filter applies only to the PDF display of vertical viewing angles.
    # Raw profile data, CSV outputs and summary statistics are unchanged.
    if chart_type == "angle":
        values = [
            value
            for value in values
            if value >= ANGLE_CHART_MIN_DEG
        ]

    if not distances or not values:
        _draw_text(
'@

if (-not $content.Contains($oldValuesBlock)) {
    throw "Patch stopped: chart-values marker was not found."
}

$content = $content.Replace(
    $oldValuesBlock,
    $newValuesBlock
)

# ---------------------------------------------------------------------
# 3. Prevent Y-axis padding from extending below -10 degrees.
# ---------------------------------------------------------------------
$oldAxisBlock = @'
    y_min, y_max = _expand_axis_range(
        y_min,
        y_max,
        padding_fraction=0.07,
    )
    _draw_large_chart_grid(
'@

$newAxisBlock = @'
    y_min, y_max = _expand_axis_range(
        y_min,
        y_max,
        padding_fraction=0.07,
    )

    # The PDF viewing-angle chart must not show values below -10 degrees.
    if chart_type == "angle":
        y_min = max(y_min, ANGLE_CHART_MIN_DEG)

        # Avoid an unusably narrow vertical axis.
        if y_max - y_min < 0.5:
            y_max = y_min + 0.5

    _draw_large_chart_grid(
'@

if (-not $content.Contains($oldAxisBlock)) {
    throw "Patch stopped: Y-axis marker was not found."
}

$content = $content.Replace(
    $oldAxisBlock,
    $newAxisBlock
)

# ---------------------------------------------------------------------
# 4. Pass chart_type to the line-drawing function.
# ---------------------------------------------------------------------
$oldSeriesCall = @'
            style=style,
            width=1.45,
        )
'@

$newSeriesCall = @'
            style=style,
            width=1.45,
            chart_type=chart_type,
        )
'@

if (-not $content.Contains($oldSeriesCall)) {
    throw "Patch stopped: chart-series call marker was not found."
}

$content = $content.Replace(
    $oldSeriesCall,
    $newSeriesCall
)

# ---------------------------------------------------------------------
# 5. Add chart_type to _draw_chart_series and create gaps below -10°.
# ---------------------------------------------------------------------
$oldSignature = @'
    style,
    width=1.25,
):
    """Draws a line series, interrupted at NoData values."""
'@

$newSignature = @'
    style,
    width=1.25,
    chart_type="elevation",
):
    """
    Draws a line series, interrupted at NoData and filtered values.

    For vertical viewing-angle charts, values below -10 degrees are
    not drawn and produce a gap in the PDF line.
    """
'@

if (-not $content.Contains($oldSignature)) {
    throw "Patch stopped: _draw_chart_series signature marker was not found."
}

$content = $content.Replace(
    $oldSignature,
    $newSignature
)

$oldLineCondition = @'
        if distance is None or value is None:
            previous_point = None
            continue
'@

$newLineCondition = @'
        if distance is None or value is None:
            previous_point = None
            continue

        # Apply the filter only while rendering vertical angle charts.
        # Do not clamp the line to -10°; create a visible gap instead.
        if (
            chart_type == "angle"
            and float(value) < ANGLE_CHART_MIN_DEG
        ):
            previous_point = None
            continue
'@

if (-not $content.Contains($oldLineCondition)) {
    throw "Patch stopped: line-value marker was not found."
}

$content = $content.Replace(
    $oldLineCondition,
    $newLineCondition
)

# ---------------------------------------------------------------------
# 6. Give more height to the vertical viewing-angle chart.
# ---------------------------------------------------------------------
$content = $content.Replace(
@'
        content_rect.width(),
        255.0,
    )
    _draw_large_profile_chart(
        painter=painter,
        rect=elevation_rect,
'@,
@'
        content_rect.width(),
        210.0,
    )
    _draw_large_profile_chart(
        painter=painter,
        rect=elevation_rect,
'@
)

$content = $content.Replace(
@'
        elevation_rect.bottom() + 18.0,
        content_rect.width(),
        82.0,
    )
'@,
@'
        elevation_rect.bottom() + 14.0,
        content_rect.width(),
        70.0,
    )
'@
)

$content = $content.Replace(
@'
        ribbon_rect.bottom() + 18.0,
        content_rect.width(),
        255.0,
    )
    _draw_large_profile_chart(
        painter=painter,
        rect=angle_rect,
'@,
@'
        ribbon_rect.bottom() + 14.0,
        content_rect.width(),
        370.0,
    )
    _draw_large_profile_chart(
        painter=painter,
        rect=angle_rect,
'@
)

Set-Content -Path $source -Value $content -Encoding UTF8

Write-Host ""
Write-Host "Patch successfully applied." -ForegroundColor Green
Write-Host "Backup:" -ForegroundColor Yellow
Write-Host $backup
Write-Host ""
Write-Host "Angle chart: PDF values below -10° are hidden." -ForegroundColor Cyan
Write-Host "Angle chart height: 255 -> 370." -ForegroundColor Cyan