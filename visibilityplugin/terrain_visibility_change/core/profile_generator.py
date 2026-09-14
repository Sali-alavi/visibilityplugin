# -*- coding: utf-8 -*-

"""
Directional DOM, viewing-angle and visibility profile generation.

Creates eight profiles from the observer point to the nearest intersection
with the analysis-boundary polygon:

    N, NE, E, SE, S, SW, W, NW

Generated files:

    profiles/profile_N.csv
    profiles/profile_NE.csv
    profiles/profile_E.csv
    profiles/profile_SE.csv
    profiles/profile_S.csv
    profiles/profile_SW.csv
    profiles/profile_W.csv
    profiles/profile_NW.csv
    profiles/profile_summary.csv
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy
from osgeo import gdal, ogr


VIEWSHED_VISIBLE = 1
VIEWSHED_NOT_VISIBLE = 0

BYTE_NODATA = 255
FLOAT_NODATA = -9999.0


DIRECTION_DEFINITIONS = (
    {
        "name": "N",
        "azimuth_deg": 0.0,
        "dx": 0.0,
        "dy": 1.0,
    },
    {
        "name": "NE",
        "azimuth_deg": 45.0,
        "dx": math.sqrt(0.5),
        "dy": math.sqrt(0.5),
    },
    {
        "name": "E",
        "azimuth_deg": 90.0,
        "dx": 1.0,
        "dy": 0.0,
    },
    {
        "name": "SE",
        "azimuth_deg": 135.0,
        "dx": math.sqrt(0.5),
        "dy": -math.sqrt(0.5),
    },
    {
        "name": "S",
        "azimuth_deg": 180.0,
        "dx": 0.0,
        "dy": -1.0,
    },
    {
        "name": "SW",
        "azimuth_deg": 225.0,
        "dx": -math.sqrt(0.5),
        "dy": -math.sqrt(0.5),
    },
    {
        "name": "W",
        "azimuth_deg": 270.0,
        "dx": -1.0,
        "dy": 0.0,
    },
    {
        "name": "NW",
        "azimuth_deg": 315.0,
        "dx": -math.sqrt(0.5),
        "dy": math.sqrt(0.5),
    },
)


class ProfileGenerationError(RuntimeError):
    """
    Raised when directional profile generation fails.
    """


def generate_directional_profiles(
    dom_2026_path,
    dom_2230_path,
    viewshed_2026_path,
    viewshed_2230_path,
    viewing_angle_2026_path,
    viewing_angle_2230_path,
    viewing_angle_difference_path,
    boundary_wkt,
    observer_x,
    observer_y,
    output_folder,
    sampling_interval_m=1.0,
):
    """
    Generates eight directional profile CSV files and one summary CSV.

    Parameters
    ----------
    dom_2026_path : str | Path
        DOM raster for scenario 2026.
    dom_2230_path : str | Path
        DOM raster for scenario 2230.
    viewshed_2026_path : str | Path
        Masked Viewshed raster for 2026.
    viewshed_2230_path : str | Path
        Masked Viewshed raster for 2230.
    viewing_angle_2026_path : str | Path
        Viewing angle raster for 2026.
    viewing_angle_2230_path : str | Path
        Viewing angle raster for 2230.
    viewing_angle_difference_path : str | Path
        Viewing-angle difference raster, 2230 minus 2026.
    boundary_wkt : str
        Analysis boundary in DOM CRS as WKT.
    observer_x : float
        Observer X coordinate in DOM CRS.
    observer_y : float
        Observer Y coordinate in DOM CRS.
    output_folder : str | Path
        Main output folder. A "profiles" subfolder is created.
    sampling_interval_m : float
        Sampling interval along profile rays in metres.

    Returns
    -------
    dict
        Profile output paths, summaries and profile folder.
    """

    sampling_interval_m = float(sampling_interval_m)

    if sampling_interval_m <= 0:
        raise ProfileGenerationError(
            "Profile sampling interval must be greater than zero."
        )

    output_folder = Path(output_folder)
    profile_folder = output_folder / "profiles"

    profile_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    input_paths = {
        "DOM 2026": Path(dom_2026_path),
        "DOM 2230": Path(dom_2230_path),
        "Viewshed 2026": Path(viewshed_2026_path),
        "Viewshed 2230": Path(viewshed_2230_path),
        "Viewing angle 2026": Path(viewing_angle_2026_path),
        "Viewing angle 2230": Path(viewing_angle_2230_path),
        "Viewing angle difference": Path(
            viewing_angle_difference_path
        ),
    }

    for source_name, source_path in input_paths.items():
        if not source_path.is_file():
            raise ProfileGenerationError(
                f"{source_name} raster does not exist:\n"
                f"{source_path}"
            )

    boundary_geometry = ogr.CreateGeometryFromWkt(
        str(boundary_wkt)
    )

    if boundary_geometry is None:
        raise ProfileGenerationError(
            "Could not create analysis-boundary geometry from WKT."
        )

    if boundary_geometry.IsEmpty():
        raise ProfileGenerationError(
            "Analysis-boundary geometry is empty."
        )

    observer_point = ogr.Geometry(ogr.wkbPoint)
    observer_point.AddPoint(
        float(observer_x),
        float(observer_y),
    )

    if not boundary_geometry.Contains(observer_point):
        raise ProfileGenerationError(
            "Observer point must be inside the analysis-boundary polygon."
        )

    gdal.UseExceptions()

    datasets = {}

    try:
        for key, source_path in input_paths.items():
            dataset = gdal.Open(
                str(source_path),
                gdal.GA_ReadOnly,
            )

            if dataset is None:
                raise ProfileGenerationError(
                    f"Could not open {key} raster:\n"
                    f"{source_path}"
                )

            datasets[key] = dataset

        reference_dataset = datasets["DOM 2026"]

        for key, dataset in datasets.items():
            if key != "DOM 2026":
                _validate_profile_raster_alignment(
                    reference_dataset,
                    dataset,
                )

        profile_paths = {}
        profile_summaries = []

        for direction in DIRECTION_DEFINITIONS:
            direction_name = direction["name"]

            profile_length_m = _calculate_profile_length(
                boundary_geometry=boundary_geometry,
                observer_x=float(observer_x),
                observer_y=float(observer_y),
                direction_x=float(direction["dx"]),
                direction_y=float(direction["dy"]),
            )

            sample_distances = _create_sample_distances(
                profile_length_m=profile_length_m,
                sampling_interval_m=sampling_interval_m,
            )

            profile_rows = _create_profile_rows(
                direction=direction,
                sample_distances=sample_distances,
                observer_x=float(observer_x),
                observer_y=float(observer_y),
                datasets=datasets,
            )

            profile_path = (
                profile_folder
                / f"profile_{direction_name}.csv"
            )

            _write_profile_csv(
                profile_path=profile_path,
                rows=profile_rows,
            )

            profile_summary = _calculate_profile_summary(
                direction=direction,
                profile_length_m=profile_length_m,
                sampling_interval_m=sampling_interval_m,
                profile_rows=profile_rows,
            )

            profile_paths[direction_name] = profile_path
            profile_summaries.append(profile_summary)

        summary_path = (
            profile_folder
            / "profile_summary.csv"
        )

        _write_profile_summary_csv(
            summary_path=summary_path,
            profile_summaries=profile_summaries,
        )

        return {
            "profile_folder": profile_folder,
            "profile_paths": profile_paths,
            "summary_path": summary_path,
            "summaries": profile_summaries,
            "sampling_interval_m": sampling_interval_m,
        }

    except ProfileGenerationError:
        raise

    except Exception as error:
        raise ProfileGenerationError(
            "Directional profile generation failed:\n"
            f"{type(error).__name__}: {error}"
        ) from error

    finally:
        datasets.clear()
        boundary_geometry = None
        observer_point = None


def _calculate_profile_length(
    boundary_geometry,
    observer_x,
    observer_y,
    direction_x,
    direction_y,
):
    """
    Finds the nearest positive intersection of a directional observer ray
    with the analysis-boundary polygon border.
    """

    min_x, max_x, min_y, max_y = boundary_geometry.GetEnvelope()

    maximum_distance = max(
        math.hypot(min_x - observer_x, min_y - observer_y),
        math.hypot(min_x - observer_x, max_y - observer_y),
        math.hypot(max_x - observer_x, min_y - observer_y),
        math.hypot(max_x - observer_x, max_y - observer_y),
    )

    ray_length = maximum_distance + 100.0

    ray = ogr.Geometry(ogr.wkbLineString)

    ray.AddPoint(
        float(observer_x),
        float(observer_y),
    )

    ray.AddPoint(
        float(observer_x + direction_x * ray_length),
        float(observer_y + direction_y * ray_length),
    )

    boundary_line = boundary_geometry.Boundary()

    if boundary_line is None or boundary_line.IsEmpty():
        raise ProfileGenerationError(
            "Could not derive a boundary line from the analysis polygon."
        )

    intersection = ray.Intersection(boundary_line)

    if intersection is None or intersection.IsEmpty():
        raise ProfileGenerationError(
            "Directional profile ray does not intersect "
            "the analysis-boundary polygon."
        )

    intersection_points = []

    _collect_geometry_points(
        geometry=intersection,
        output_points=intersection_points,
    )

    positive_distances = []

    for point_x, point_y in intersection_points:
        vector_x = point_x - observer_x
        vector_y = point_y - observer_y

        forward_distance = (
            vector_x * direction_x
            + vector_y * direction_y
        )

        perpendicular_distance = abs(
            vector_x * direction_y
            - vector_y * direction_x
        )

        if (
            forward_distance > 0.001
            and perpendicular_distance < 0.01
        ):
            positive_distances.append(
                float(forward_distance)
            )

    if not positive_distances:
        raise ProfileGenerationError(
            "Could not determine a valid forward distance "
            "from observer to polygon boundary."
        )

    ray = None
    boundary_line = None
    intersection = None

    return min(positive_distances)


def _collect_geometry_points(
    geometry,
    output_points,
):
    """
    Recursively extracts coordinates from an OGR geometry.

    This implementation intentionally uses GetGeometryName() and does not
    use ogr.wkbFlatten(), because some GDAL/OGR Python bindings provided
    with QGIS do not expose ogr.wkbFlatten.

    Supported intersection geometries include:
    - POINT
    - MULTIPOINT
    - LINESTRING
    - MULTILINESTRING
    - GEOMETRYCOLLECTION
    """

    if geometry is None or geometry.IsEmpty():
        return

    geometry_name = geometry.GetGeometryName().upper()

    if geometry_name == "POINT":
        output_points.append(
            (
                float(geometry.GetX()),
                float(geometry.GetY()),
            )
        )
        return

    if geometry_name in (
        "LINESTRING",
        "LINEARRING",
    ):
        point_count = geometry.GetPointCount()

        for index in range(point_count):
            point = geometry.GetPoint(index)

            output_points.append(
                (
                    float(point[0]),
                    float(point[1]),
                )
            )

        return

    geometry_count = geometry.GetGeometryCount()

    for index in range(geometry_count):
        child_geometry = geometry.GetGeometryRef(index)

        _collect_geometry_points(
            geometry=child_geometry,
            output_points=output_points,
        )


def _create_sample_distances(
    profile_length_m,
    sampling_interval_m,
):
    """
    Creates distances from observer to boundary.

    The endpoint is placed slightly before the exact polygon border to
    avoid possible edge NoData values caused by rasterized masks.
    """

    profile_length_m = float(profile_length_m)
    sampling_interval_m = float(sampling_interval_m)

    if profile_length_m <= 0:
        raise ProfileGenerationError(
            "Profile length must be greater than zero."
        )

    effective_length = max(
        0.0,
        profile_length_m - 0.01,
    )

    distances = list(
        numpy.arange(
            0.0,
            effective_length,
            sampling_interval_m,
        )
    )

    if not distances:
        distances = [0.0]

    if (
        effective_length - distances[-1]
        > 0.001
    ):
        distances.append(effective_length)

    return [
        float(distance)
        for distance in distances
    ]


def _create_profile_rows(
    direction,
    sample_distances,
    observer_x,
    observer_y,
    datasets,
):
    """
    Samples all input rasters for one directional profile.
    """

    direction_x = float(direction["dx"])
    direction_y = float(direction["dy"])

    rows = []

    for distance_m in sample_distances:
        x_coordinate = (
            observer_x
            + distance_m * direction_x
        )

        y_coordinate = (
            observer_y
            + distance_m * direction_y
        )

        dom_2026_value = _sample_dataset_value(
            datasets["DOM 2026"],
            x_coordinate,
            y_coordinate,
        )

        dom_2230_value = _sample_dataset_value(
            datasets["DOM 2230"],
            x_coordinate,
            y_coordinate,
        )

        viewshed_2026_value = _sample_dataset_value(
            datasets["Viewshed 2026"],
            x_coordinate,
            y_coordinate,
        )

        viewshed_2230_value = _sample_dataset_value(
            datasets["Viewshed 2230"],
            x_coordinate,
            y_coordinate,
        )

        angle_2026_value = _sample_dataset_value(
            datasets["Viewing angle 2026"],
            x_coordinate,
            y_coordinate,
        )

        angle_2230_value = _sample_dataset_value(
            datasets["Viewing angle 2230"],
            x_coordinate,
            y_coordinate,
        )

        angle_difference_value = _sample_dataset_value(
            datasets["Viewing angle difference"],
            x_coordinate,
            y_coordinate,
        )

        visible_2026 = _viewshed_value_to_visible(
            viewshed_2026_value
        )

        visible_2230 = _viewshed_value_to_visible(
            viewshed_2230_value
        )

        rows.append(
            {
                "direction": direction["name"],
                "azimuth_deg": float(direction["azimuth_deg"]),
                "distance_m": float(distance_m),
                "x": float(x_coordinate),
                "y": float(y_coordinate),
                "dom_2026_m": dom_2026_value,
                "dom_2230_m": dom_2230_value,
                "surface_change_m": _subtract_values(
                    dom_2230_value,
                    dom_2026_value,
                ),
                "viewing_angle_2026_deg": angle_2026_value,
                "viewing_angle_2230_deg": angle_2230_value,
                "viewing_angle_difference_deg": (
                    angle_difference_value
                ),
                "visible_2026": visible_2026,
                "visible_2230": visible_2230,
                "visibility_change_class": (
                    _calculate_visibility_change_class(
                        visible_2026,
                        visible_2230,
                    )
                ),
            }
        )

    return rows


def _sample_dataset_value(
    dataset,
    x_coordinate,
    y_coordinate,
):
    """
    Samples one raster cell using nearest-neighbour sampling.

    The supplied DOM grid is north-up. Rotated grids are intentionally not
    supported in this profile implementation.
    """

    geotransform = dataset.GetGeoTransform()

    if geotransform is None:
        raise ProfileGenerationError(
            "Raster has no GeoTransform."
        )

    if (
        abs(geotransform[2]) > 1e-12
        or abs(geotransform[4]) > 1e-12
    ):
        raise ProfileGenerationError(
            "Rotated raster grids are not supported for profiles."
        )

    pixel_width = float(geotransform[1])
    pixel_height = float(geotransform[5])

    if pixel_width == 0 or pixel_height == 0:
        raise ProfileGenerationError(
            "Raster has invalid pixel size."
        )

    pixel_column = int(
        math.floor(
            (x_coordinate - geotransform[0])
            / pixel_width
        )
    )

    pixel_row = int(
        math.floor(
            (y_coordinate - geotransform[3])
            / pixel_height
        )
    )

    if (
        pixel_column < 0
        or pixel_row < 0
        or pixel_column >= dataset.RasterXSize
        or pixel_row >= dataset.RasterYSize
    ):
        return None

    raster_band = dataset.GetRasterBand(1)

    if raster_band is None:
        raise ProfileGenerationError(
            "Could not access raster band 1."
        )

    values = raster_band.ReadAsArray(
        pixel_column,
        pixel_row,
        1,
        1,
    )

    if values is None:
        return None

    value = float(values[0, 0])
    nodata_value = raster_band.GetNoDataValue()

    if not numpy.isfinite(value):
        return None

    if (
        nodata_value is not None
        and value == float(nodata_value)
    ):
        return None

    return value


def _viewshed_value_to_visible(
    value,
):
    """
    Converts Viewshed values to:

        1    = visible
        0    = not visible
        None = NoData / invalid
    """

    if value is None:
        return None

    integer_value = int(round(value))

    if integer_value == VIEWSHED_VISIBLE:
        return 1

    if integer_value == VIEWSHED_NOT_VISIBLE:
        return 0

    return None


def _calculate_visibility_change_class(
    visible_2026,
    visible_2230,
):
    """
    Visibility change classes:

        1   = Not visible in both scenarios
        2   = Visible in both scenarios
        3   = Visibility loss
        4   = Visibility gain
        255 = NoData / invalid
    """

    if visible_2026 is None or visible_2230 is None:
        return BYTE_NODATA

    if visible_2026 == 0 and visible_2230 == 0:
        return 1

    if visible_2026 == 1 and visible_2230 == 1:
        return 2

    if visible_2026 == 1 and visible_2230 == 0:
        return 3

    if visible_2026 == 0 and visible_2230 == 1:
        return 4

    return BYTE_NODATA


def _subtract_values(
    value_a,
    value_b,
):
    """
    Returns value_a minus value_b if both values are valid.
    """

    if value_a is None or value_b is None:
        return None

    return float(value_a - value_b)


def _write_profile_csv(
    profile_path,
    rows,
):
    """
    Writes a directional profile CSV in UTF-8 with BOM.
    """

    headers = [
        "direction",
        "azimuth_deg",
        "distance_m",
        "x",
        "y",
        "dom_2026_m",
        "dom_2230_m",
        "surface_change_m",
        "viewing_angle_2026_deg",
        "viewing_angle_2230_deg",
        "viewing_angle_difference_deg",
        "visible_2026",
        "visible_2230",
        "visibility_change_class",
    ]

    try:
        with open(
            profile_path,
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=headers,
            )

            writer.writeheader()

            for row in rows:
                writer.writerow(
                    {
                        "direction": row["direction"],
                        "azimuth_deg": _format_value(
                            row["azimuth_deg"],
                            2,
                        ),
                        "distance_m": _format_value(
                            row["distance_m"],
                            2,
                        ),
                        "x": _format_value(row["x"], 3),
                        "y": _format_value(row["y"], 3),
                        "dom_2026_m": _format_value(
                            row["dom_2026_m"],
                            3,
                        ),
                        "dom_2230_m": _format_value(
                            row["dom_2230_m"],
                            3,
                        ),
                        "surface_change_m": _format_value(
                            row["surface_change_m"],
                            3,
                        ),
                        "viewing_angle_2026_deg": _format_value(
                            row["viewing_angle_2026_deg"],
                            5,
                        ),
                        "viewing_angle_2230_deg": _format_value(
                            row["viewing_angle_2230_deg"],
                            5,
                        ),
                        "viewing_angle_difference_deg": _format_value(
                            row["viewing_angle_difference_deg"],
                            5,
                        ),
                        "visible_2026": _format_integer_or_blank(
                            row["visible_2026"]
                        ),
                        "visible_2230": _format_integer_or_blank(
                            row["visible_2230"]
                        ),
                        "visibility_change_class": (
                            _format_integer_or_blank(
                                row["visibility_change_class"]
                            )
                        ),
                    }
                )

    except OSError as error:
        raise ProfileGenerationError(
            "Could not write profile CSV:\n"
            f"{profile_path}\n\n"
            f"{error}"
        ) from error


def _calculate_profile_summary(
    direction,
    profile_length_m,
    sampling_interval_m,
    profile_rows,
):
    """
    Calculates one profile summary.

    Length values are sample-based approximations. With a 1 m sampling
    interval, values represent approximate profile lengths in metres.
    """

    valid_rows = [
        row
        for row in profile_rows
        if row["visibility_change_class"] != BYTE_NODATA
    ]

    visible_2026_count = sum(
        1
        for row in valid_rows
        if row["visible_2026"] == 1
    )

    visible_2230_count = sum(
        1
        for row in valid_rows
        if row["visible_2230"] == 1
    )

    visibility_loss_count = sum(
        1
        for row in valid_rows
        if row["visibility_change_class"] == 3
    )

    visibility_gain_count = sum(
        1
        for row in valid_rows
        if row["visibility_change_class"] == 4
    )

    return {
        "direction": direction["name"],
        "azimuth_deg": float(direction["azimuth_deg"]),
        "profile_length_m": float(profile_length_m),
        "sample_count": int(len(profile_rows)),
        "valid_sample_count": int(len(valid_rows)),
        "sampling_interval_m": float(sampling_interval_m),
        "visible_length_2026_m": (
            visible_2026_count * sampling_interval_m
        ),
        "visible_length_2230_m": (
            visible_2230_count * sampling_interval_m
        ),
        "visibility_loss_length_m": (
            visibility_loss_count * sampling_interval_m
        ),
        "visibility_gain_length_m": (
            visibility_gain_count * sampling_interval_m
        ),
        "mean_surface_change_m": _mean_or_none(
            _valid_values(profile_rows, "surface_change_m")
        ),
        "mean_angle_2026_deg": _mean_or_none(
            _valid_values(
                profile_rows,
                "viewing_angle_2026_deg",
            )
        ),
        "mean_angle_2230_deg": _mean_or_none(
            _valid_values(
                profile_rows,
                "viewing_angle_2230_deg",
            )
        ),
        "mean_angle_difference_deg": _mean_or_none(
            _valid_values(
                profile_rows,
                "viewing_angle_difference_deg",
            )
        ),
        "min_angle_difference_deg": _min_or_none(
            _valid_values(
                profile_rows,
                "viewing_angle_difference_deg",
            )
        ),
        "max_angle_difference_deg": _max_or_none(
            _valid_values(
                profile_rows,
                "viewing_angle_difference_deg",
            )
        ),
    }


def _write_profile_summary_csv(
    summary_path,
    profile_summaries,
):
    """
    Writes profile_summary.csv in UTF-8 with BOM.
    """

    headers = [
        "direction",
        "azimuth_deg",
        "profile_length_m",
        "sample_count",
        "valid_sample_count",
        "sampling_interval_m",
        "visible_length_2026_m",
        "visible_length_2230_m",
        "visibility_loss_length_m",
        "visibility_gain_length_m",
        "mean_surface_change_m",
        "mean_angle_2026_deg",
        "mean_angle_2230_deg",
        "mean_angle_difference_deg",
        "min_angle_difference_deg",
        "max_angle_difference_deg",
    ]

    try:
        with open(
            summary_path,
            "w",
            newline="",
            encoding="utf-8-sig",
        ) as csv_file:
            writer = csv.DictWriter(
                csv_file,
                fieldnames=headers,
            )

            writer.writeheader()

            for summary in profile_summaries:
                writer.writerow(
                    {
                        "direction": summary["direction"],
                        "azimuth_deg": _format_value(
                            summary["azimuth_deg"],
                            2,
                        ),
                        "profile_length_m": _format_value(
                            summary["profile_length_m"],
                            2,
                        ),
                        "sample_count": summary["sample_count"],
                        "valid_sample_count": (
                            summary["valid_sample_count"]
                        ),
                        "sampling_interval_m": _format_value(
                            summary["sampling_interval_m"],
                            2,
                        ),
                        "visible_length_2026_m": _format_value(
                            summary["visible_length_2026_m"],
                            2,
                        ),
                        "visible_length_2230_m": _format_value(
                            summary["visible_length_2230_m"],
                            2,
                        ),
                        "visibility_loss_length_m": _format_value(
                            summary["visibility_loss_length_m"],
                            2,
                        ),
                        "visibility_gain_length_m": _format_value(
                            summary["visibility_gain_length_m"],
                            2,
                        ),
                        "mean_surface_change_m": _format_value(
                            summary["mean_surface_change_m"],
                            4,
                        ),
                        "mean_angle_2026_deg": _format_value(
                            summary["mean_angle_2026_deg"],
                            5,
                        ),
                        "mean_angle_2230_deg": _format_value(
                            summary["mean_angle_2230_deg"],
                            5,
                        ),
                        "mean_angle_difference_deg": _format_value(
                            summary["mean_angle_difference_deg"],
                            5,
                        ),
                        "min_angle_difference_deg": _format_value(
                            summary["min_angle_difference_deg"],
                            5,
                        ),
                        "max_angle_difference_deg": _format_value(
                            summary["max_angle_difference_deg"],
                            5,
                        ),
                    }
                )

    except OSError as error:
        raise ProfileGenerationError(
            "Could not write profile summary CSV:\n"
            f"{summary_path}\n\n"
            f"{error}"
        ) from error


def _valid_values(
    rows,
    key,
):
    """
    Returns finite numeric values from a profile-row column.
    """

    values = []

    for row in rows:
        value = row.get(key)

        if value is not None and numpy.isfinite(value):
            values.append(float(value))

    return values


def _mean_or_none(values):
    if not values:
        return None

    return float(numpy.mean(values))


def _min_or_none(values):
    if not values:
        return None

    return float(numpy.min(values))


def _max_or_none(values):
    if not values:
        return None

    return float(numpy.max(values))


def _format_value(
    value,
    decimals,
):
    """
    Formats float values for CSV; blank for invalid values.
    """

    if value is None:
        return ""

    return f"{float(value):.{int(decimals)}f}"


def _format_integer_or_blank(value):
    """
    Formats integer values for CSV; blank for None.
    """

    if value is None:
        return ""

    return str(int(value))


def _validate_profile_raster_alignment(
    reference_dataset,
    comparison_dataset,
):
    """
    Checks strict grid alignment of profile input rasters.
    """

    if (
        reference_dataset.RasterXSize
        != comparison_dataset.RasterXSize
        or reference_dataset.RasterYSize
        != comparison_dataset.RasterYSize
    ):
        raise ProfileGenerationError(
            "Profile input rasters are not grid-aligned: "
            "different raster dimensions."
        )

    if (
        reference_dataset.GetProjection()
        != comparison_dataset.GetProjection()
    ):
        raise ProfileGenerationError(
            "Profile input rasters are not grid-aligned: "
            "different CRS definitions."
        )

    reference_transform = reference_dataset.GetGeoTransform()
    comparison_transform = comparison_dataset.GetGeoTransform()

    if (
        reference_transform is None
        or comparison_transform is None
    ):
        raise ProfileGenerationError(
            "Profile input raster has no GeoTransform."
        )

    tolerance = 1e-9

    for reference_value, comparison_value in zip(
        reference_transform,
        comparison_transform,
    ):
        if abs(reference_value - comparison_value) > tolerance:
            raise ProfileGenerationError(
                "Profile input rasters are not grid-aligned: "
                "GeoTransform values differ."
            )