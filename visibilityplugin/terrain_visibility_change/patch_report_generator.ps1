$reportFile = Join-Path $PSScriptRoot "core\report_generator.py"

if (-not (Test-Path $reportFile)) {
    throw "File not found: $reportFile"
}

$backupFile = "$reportFile.backup_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Copy-Item $reportFile $backupFile

$content = Get-Content $reportFile -Raw -Encoding UTF8

# Fix accidental markdown corruption, if present.
$content = $content.Replace(
    "from **future** import annotations",
    "from __future__ import annotations"
)

# Add chart threshold constant after BYTE_NODATA.
if ($content -notmatch "ANGLE_CHART_MIN_DEG") {
    $content = $content.Replace(
@"
BYTE_NODATA = 255
"@,
@"
BYTE_NODATA = 255

# PDF display threshold for vertical viewing-angle charts.
#
# Values below this threshold are excluded from PDF charts only.
# Raster outputs, profile CSV files and profile summary statistics
# remain unchanged.
ANGLE_CHART_MIN_DEG = -10.0
"@
    )
}

$largeProfileChartFunction = @'
def _draw_large_profile_chart(
    painter,
    rect,
    profile_rows,
    chart_type,
    title,
    y_axis_label,
):
    """
    Draws one large profile chart.

    For vertical viewing-angle charts, values below
    ANGLE_CHART_MIN_DEG are excluded from the PDF display only.

    Important:
    - Raster outputs remain unchanged.
    - Profile CSV files remain unchanged.
    - Profile summary statistics remain unchanged.
    - Values outside the display range create a line gap; they are not
      clipped onto the lower chart boundary.
    """

    _draw_rectangle(
        painter,
        rect,
        border_color=QColor("#A9B4BC"),
        fill_color=QColor("#FFFFFF"),
        line_width=0.8,
    )

    _draw_text(
        painter,
        QRectF(
            rect.left() + 12.0,
            rect.top() + 5.0,
            rect.width() - 24.0,
            22.0,
        ),
        title,
        11,
        True,
        QColor("#1F2933"),
        Qt.AlignLeft | Qt.AlignVCenter,
    )

    if chart_type == "elevation":
        series_definitions = (
            (
                "dom_2026_m",
                QColor("#2166AC"),
                "DOM 2026",
                Qt.SolidLine,
            ),
            (
                "dom_2230_m",
                QColor("#E6550D"),
                "DOM 2230",
                Qt.SolidLine,
            ),
        )
    else:
        series_definitions = (
            (
                "viewing_angle_2026_deg",
                QColor("#2166AC"),
                "Î² 2026",
                Qt.SolidLine,
            ),
            (
                "viewing_angle_2230_deg",
                QColor("#E6550D"),
                "Î² 2230",
                Qt.SolidLine,
            ),
            (
                "viewing_angle_difference_deg",
                QColor("#6A3D9A"),
                "Î”Î² = Î²2230 âˆ’ Î²2026",
                Qt.DashLine,
            ),
        )

    if not profile_rows:
        _draw_text(
            painter,
            rect.adjusted(
                20.0,
                40.0,
                -20.0,
                -20.0,
            ),
            "No valid profile values are available.",
            10,
            False,
            QColor("#B30000"),
            Qt.AlignCenter,
        )
        return

    chart_rows = [
        row
        for row in profile_rows
        if row.get("distance_m") is not None
    ]

    if not chart_rows:
        _draw_text(
            painter,
            rect.adjusted(
                20.0,
                40.0,
                -20.0,
                -20.0,
            ),
            "No valid distance values are available.",
            10,
            False,
            QColor("#B30000"),
            Qt.AlignCenter,
        )
        return

    distances = [
        row["distance_m"]
        for row in chart_rows
    ]

    plotted_values = []

    for value_key, _, _, _ in series_definitions:
        plotted_values.extend(
            [
                row[value_key]
                for row in chart_rows
                if _is_chart_value_valid(
                    chart_type,
                    row.get(value_key),
                )
            ]
        )

    if not plotted_values:
        threshold_note = ""

        if chart_type == "angle":
            threshold_note = (
                f" Values below {ANGLE_CHART_MIN_DEG:.1f}Â° "
                "are excluded from this PDF chart."
            )

        _draw_text(
            painter,
            rect.adjusted(
                20.0,
                40.0,
                -20.0,
                -20.0,
            ),
            "No displayable chart values are available."
            + threshold_note,
            10,
            False,
            QColor("#B30000"),
            Qt.AlignCenter | Qt.TextWordWrap,
        )
        return

    x_min = min(distances)
    x_max = max(distances)

    if abs(x_max - x_min) < 1e-9:
        x_max = x_min + 1.0

    y_min = min(plotted_values)
    y_max = max(plotted_values)

    if chart_type == "angle":
        # The vertical angle display must never be expanded below -10Â°.
        y_min = max(
            float(ANGLE_CHART_MIN_DEG),
            float(y_min),
        )

        # Include the zero-degree reference line where possible.
        y_min = min(y_min, 0.0)
        y_max = max(y_max, 0.0)

    y_min, y_max = _expand_axis_range(
        y_min,
        y_max,
        padding_fraction=0.07,
    )

    if chart_type == "angle":
        # Do not allow axis padding to extend below the selected threshold.
        y_min = max(
            float(ANGLE_CHART_MIN_DEG),
            float(y_min),
        )

        # Guarantee a usable range if values are very close together.
        if y_max - y_min < 0.5:
            y_max = y_min + 0.5

    plot_rect = QRectF(
        rect.left() + 67.0,
        rect.top() + 34.0,
        rect.width() - 91.0,
        rect.height() - 76.0,
    )

    _draw_large_chart_grid(
        painter,
        plot_rect,
        x_min,
        x_max,
        y_min,
        y_max,
        y_axis_label,
    )

    if chart_type == "angle" and y_min <= 0.0 <= y_max:
        zero_y = _map_value(
            0.0,
            y_min,
            y_max,
            plot_rect.bottom(),
            plot_rect.top(),
        )

        _draw_line(
            painter,
            plot_rect.left(),
            zero_y,
            plot_rect.right(),
            zero_y,
            QColor("#555555"),
            0.9,
            Qt.DashLine,
        )

    for value_key, color, _, style in series_definitions:
        _draw_chart_series(
            painter=painter,
            plot_rect=plot_rect,
            profile_rows=chart_rows,
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            value_key=value_key,
            color=color,
            style=style,
            width=1.45,
            chart_type=chart_type,
        )

    _draw_large_chart_legend(
        painter,
        QRectF(
            rect.left() + 14.0,
            rect.bottom() - 32.0,
            rect.width() - 28.0,
            20.0,
        ),
        series_definitions,
    )

    if chart_type == "angle":
        _draw_text(
            painter,
            QRectF(
                rect.right() - 340.0,
                rect.top() + 6.0,
                325.0,
                18.0,
            ),
            (
                f"PDF display filter: values < "
                f"{ANGLE_CHART_MIN_DEG:.1f}Â° excluded"
            ),
            7,
            False,
            QColor("#6B7280"),
            Qt.AlignRight | Qt.AlignVCenter,
        )
'@

$chartSeriesFunction = @'
def _is_chart_value_valid(
    chart_type,
    value,
):
    """
    Returns True if a value is valid for drawing in the PDF chart.

    The angle filter applies only to the PDF visualization.
    """

    if value is None:
        return False

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return False

    if not math.isfinite(numeric_value):
        return False

    if chart_type == "angle":
        return numeric_value >= ANGLE_CHART_MIN_DEG

    return True


def _draw_chart_series(
    painter,
    plot_rect,
    profile_rows,
    x_min,
    x_max,
    y_min,
    y_max,
    value_key,
    color,
    style,
    width=1.25,
    chart_type="elevation",
):
    """
    Draws a line series and interrupts it at invalid values.

    In viewing-angle charts, values lower than ANGLE_CHART_MIN_DEG are
    deliberately treated as invalid. Therefore, no artificial line is drawn
    from an outlier below -10Â° into the valid chart range.
    """

    painter.save()
    painter.setClipRect(plot_rect)

    pen = QPen(color)
    pen.setWidthF(float(width))
    pen.setStyle(style)

    painter.setPen(pen)

    previous_point = None

    for row in profile_rows:
        distance = row.get("distance_m")
        value = row.get(value_key)

        if distance is None:
            previous_point = None
            continue

        if not _is_chart_value_valid(
            chart_type,
            value,
        ):
            previous_point = None
            continue

        point = QPointF(
            _map_value(
                float(distance),
                x_min,
                x_max,
                plot_rect.left(),
                plot_rect.right(),
            ),
            _map_value(
                float(value),
                y_min,
                y_max,
                plot_rect.bottom(),
                plot_rect.top(),
            ),
        )

        if previous_point is not None:
            painter.drawLine(
                previous_point,
                point,
            )

        previous_point = point

    painter.restore()
'@

function Replace-PythonFunctionBlock {
    param(
        [string]$Text,
        [string]$StartMarker,
        [string]$NextMarker,
        [string]$Replacement
    )

    $startIndex = $Text.IndexOf($StartMarker)

    if ($startIndex -lt 0) {
        throw "Start marker not found: $StartMarker"
    }

    $nextIndex = $Text.IndexOf(
        $NextMarker,
        $startIndex + $StartMarker.Length
    )

    if ($nextIndex -lt 0) {
        throw "Next marker not found: $NextMarker"
    }

    return (
        $Text.Substring(0, $startIndex) +
        $Replacement +
        "`r`n`r`n" +
        $Text.Substring($nextIndex)
    )
}

$content = Replace-PythonFunctionBlock `
    -Text $content `
    -StartMarker "def _draw_large_profile_chart(" `
    -NextMarker "def _draw_large_chart_grid(" `
    -Replacement $largeProfileChartFunction

$content = Replace-PythonFunctionBlock `
    -Text $content `
    -StartMarker "def _draw_chart_series(" `
    -NextMarker "def _draw_large_chart_legend(" `
    -Replacement $chartSeriesFunction

Set-Content `
    -Path $reportFile `
    -Value $content `
    -Encoding UTF8

Write-Host ""
Write-Host "Patch completed successfully." -ForegroundColor Green
Write-Host "Backup file:" -ForegroundColor Yellow
Write-Host $backupFile
Write-Host ""
Write-Host "Angle chart filter:" -ForegroundColor Cyan
Write-Host "Only values >= -10.0 degrees are displayed in PDF charts."
