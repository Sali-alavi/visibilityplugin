# -*- coding: utf-8 -*-

"""
GDAL Viewshed and visibility-change raster operations.

Viewshed output values:
    1   = visible
    0   = not visible
    255 = NoData

Visibility-change output values:
    1   = not visible in both scenarios
    2   = visible in both scenarios
    3   = visibility loss:
          visible in 2026, not visible in 2230
    4   = visibility gain:
          not visible in 2026, visible in 2230
    255 = NoData / invalid pixel
"""

from pathlib import Path

from osgeo import gdal


class ViewshedEngineError(RuntimeError):
    """
    Raised when a GDAL operation fails.
    """


VISIBLE_VALUE = 1
INVISIBLE_VALUE = 0
NODATA_VALUE = 255

# Standard refraction coefficient used by GDAL Viewshed.
CURVATURE_COEFFICIENT = 0.85714


def create_viewshed(
    dem_path,
    output_path,
    observer_x,
    observer_y,
    observer_height,
    target_height=0.0,
):
    """
    Creates a binary Viewshed GeoTIFF from one DEM.

    Parameters
    ----------
    dem_path : str | Path
        Input DEM path.
    output_path : str | Path
        Output Viewshed GeoTIFF path.
    observer_x : float
        Observer X coordinate in the DEM CRS.
    observer_y : float
        Observer Y coordinate in the DEM CRS.
    observer_height : float
        Observer height above terrain in metres.
    target_height : float
        Target height above terrain in metres.
    """

    dem_path = Path(dem_path)
    output_path = Path(output_path)

    if not dem_path.is_file():

        raise ViewshedEngineError(
            f"DEM file does not exist:\n{dem_path}"
        )

    _remove_existing_output(output_path)

    gdal.UseExceptions()

    dem_dataset = None
    output_dataset = None

    try:

        dem_dataset = gdal.Open(
            str(dem_path),
            gdal.GA_ReadOnly
        )

        if dem_dataset is None:

            raise ViewshedEngineError(
                f"GDAL could not open DEM:\n{dem_path}"
            )

        dem_band = dem_dataset.GetRasterBand(
            1
        )

        if dem_band is None:

            raise ViewshedEngineError(
                "DEM does not contain raster band 1:\n"
                f"{dem_path}"
            )

        # Important:
        # GDAL options are passed as empty string sequences ([]),
        # not as None, for compatibility with the QGIS GDAL binding.
        output_dataset = gdal.ViewshedGenerate(
            dem_band,
            "GTiff",
            str(output_path),
            [],
            float(observer_x),
            float(observer_y),
            float(observer_height),
            float(target_height),
            VISIBLE_VALUE,
            INVISIBLE_VALUE,
            NODATA_VALUE,
            NODATA_VALUE,
            CURVATURE_COEFFICIENT,
            gdal.GVM_Edge,
            0.0,
            None,
            None,
            gdal.GVOT_NORMAL,
            [],
        )

        if output_dataset is None:

            raise ViewshedEngineError(
                "GDAL ViewshedGenerate failed without creating "
                "an output dataset."
            )

        output_band = output_dataset.GetRasterBand(
            1
        )

        if output_band is None:

            raise ViewshedEngineError(
                "Could not access Viewshed output raster band 1."
            )

        output_band.SetNoDataValue(
            NODATA_VALUE
        )

        output_band.FlushCache()
        output_dataset.FlushCache()

    except ViewshedEngineError:
        raise

    except Exception as error:

        raise ViewshedEngineError(
            "GDAL Viewshed operation failed:\n"
            f"{type(error).__name__}: {error}"
        ) from error

    finally:

        output_dataset = None
        dem_dataset = None


def create_visibility_change(
    viewshed_2026_path,
    viewshed_2230_path,
    output_path,
):
    """
    Creates the classified visibility-change raster.

    Source rasters must have:
    - equal pixel dimensions;
    - equal CRS;
    - equal GeoTransform;
    - exact grid alignment.
    """

    viewshed_2026_path = Path(
        viewshed_2026_path
    )

    viewshed_2230_path = Path(
        viewshed_2230_path
    )

    output_path = Path(
        output_path
    )

    if not viewshed_2026_path.is_file():

        raise ViewshedEngineError(
            "Viewshed 2026 file does not exist:\n"
            f"{viewshed_2026_path}"
        )

    if not viewshed_2230_path.is_file():

        raise ViewshedEngineError(
            "Viewshed 2230 file does not exist:\n"
            f"{viewshed_2230_path}"
        )

    _remove_existing_output(output_path)

    gdal.UseExceptions()

    dataset_2026 = None
    dataset_2230 = None
    output_dataset = None

    try:

        dataset_2026 = gdal.Open(
            str(viewshed_2026_path),
            gdal.GA_ReadOnly
        )

        dataset_2230 = gdal.Open(
            str(viewshed_2230_path),
            gdal.GA_ReadOnly
        )

        if dataset_2026 is None:

            raise ViewshedEngineError(
                "GDAL could not open Viewshed 2026:\n"
                f"{viewshed_2026_path}"
            )

        if dataset_2230 is None:

            raise ViewshedEngineError(
                "GDAL could not open Viewshed 2230:\n"
                f"{viewshed_2230_path}"
            )

        _validate_raster_alignment(
            dataset_2026,
            dataset_2230
        )

        band_2026 = dataset_2026.GetRasterBand(
            1
        )

        band_2230 = dataset_2230.GetRasterBand(
            1
        )

        if band_2026 is None:

            raise ViewshedEngineError(
                "Viewshed 2026 has no raster band 1."
            )

        if band_2230 is None:

            raise ViewshedEngineError(
                "Viewshed 2230 has no raster band 1."
            )

        driver = gdal.GetDriverByName(
            "GTiff"
        )

        if driver is None:

            raise ViewshedEngineError(
                "GDAL GeoTIFF driver is not available."
            )

        output_dataset = driver.Create(
            str(output_path),
            int(dataset_2026.RasterXSize),
            int(dataset_2026.RasterYSize),
            1,
            gdal.GDT_Byte,
        )

        if output_dataset is None:

            raise ViewshedEngineError(
                "Could not create visibility-change raster:\n"
                f"{output_path}"
            )

        geotransform = dataset_2026.GetGeoTransform()

        if geotransform is None:

            raise ViewshedEngineError(
                "Viewshed 2026 has no GeoTransform."
            )

        projection = dataset_2026.GetProjection()

        if not projection:

            raise ViewshedEngineError(
                "Viewshed 2026 has no CRS projection."
            )

        output_dataset.SetGeoTransform(
            geotransform
        )

        output_dataset.SetProjection(
            projection
        )

        output_band = output_dataset.GetRasterBand(
            1
        )

        if output_band is None:

            raise ViewshedEngineError(
                "Could not access output raster band 1."
            )

        output_band.SetNoDataValue(
            NODATA_VALUE
        )

        raster_width = dataset_2026.RasterXSize
        raster_height = dataset_2026.RasterYSize
        block_height = 512

        for y_offset in range(
            0,
            raster_height,
            block_height
        ):

            current_height = min(
                block_height,
                raster_height - y_offset
            )

            values_2026 = band_2026.ReadAsArray(
                0,
                y_offset,
                raster_width,
                current_height,
            )

            values_2230 = band_2230.ReadAsArray(
                0,
                y_offset,
                raster_width,
                current_height,
            )

            if values_2026 is None:

                raise ViewshedEngineError(
                    "Could not read Viewshed 2026 raster values."
                )

            if values_2230 is None:

                raise ViewshedEngineError(
                    "Could not read Viewshed 2230 raster values."
                )

            change_values = _classify_visibility_change(
                values_2026,
                values_2230
            )

            output_band.WriteArray(
                change_values,
                0,
                y_offset
            )

        output_band.FlushCache()
        output_dataset.FlushCache()

    except ViewshedEngineError:
        raise

    except Exception as error:

        raise ViewshedEngineError(
            "Visibility-change raster operation failed:\n"
            f"{type(error).__name__}: {error}"
        ) from error

    finally:

        output_dataset = None
        dataset_2026 = None
        dataset_2230 = None


def _remove_existing_output(output_path):
    """
    Removes an existing output raster before writing a new result.
    """

    if not output_path.exists():
        return

    try:

        output_path.unlink()

    except OSError as error:

        raise ViewshedEngineError(
            "Existing output cannot be overwritten:\n"
            f"{output_path}\n\n"
            f"{error}"
        ) from error


def _validate_raster_alignment(
    dataset_2026,
    dataset_2230,
):
    """
    Verifies pixel-perfect alignment of both Viewshed rasters.
    """

    if (
        dataset_2026.RasterXSize
        != dataset_2230.RasterXSize
        or dataset_2026.RasterYSize
        != dataset_2230.RasterYSize
    ):

        raise ViewshedEngineError(
            "Viewshed rasters are not aligned: "
            "different raster dimensions."
        )

    projection_2026 = dataset_2026.GetProjection()
    projection_2230 = dataset_2230.GetProjection()

    if projection_2026 != projection_2230:

        raise ViewshedEngineError(
            "Viewshed rasters are not aligned: "
            "different CRS definitions."
        )

    geotransform_2026 = dataset_2026.GetGeoTransform()
    geotransform_2230 = dataset_2230.GetGeoTransform()

    if geotransform_2026 is None:

        raise ViewshedEngineError(
            "Viewshed 2026 has no GeoTransform."
        )

    if geotransform_2230 is None:

        raise ViewshedEngineError(
            "Viewshed 2230 has no GeoTransform."
        )

    tolerance = 1e-9

    for value_2026, value_2230 in zip(
        geotransform_2026,
        geotransform_2230
    ):

        if abs(value_2026 - value_2230) > tolerance:

            raise ViewshedEngineError(
                "Viewshed rasters are not aligned: "
                "GeoTransform values differ."
            )


def _classify_visibility_change(
    values_2026,
    values_2230,
):
    """
    Returns the classified visibility-change NumPy array.
    """

    import numpy

    result = numpy.full(
        values_2026.shape,
        NODATA_VALUE,
        dtype=numpy.uint8
    )

    valid_2026 = (
        (values_2026 == INVISIBLE_VALUE)
        | (values_2026 == VISIBLE_VALUE)
    )

    valid_2230 = (
        (values_2230 == INVISIBLE_VALUE)
        | (values_2230 == VISIBLE_VALUE)
    )

    valid_values = (
        valid_2026
        & valid_2230
    )

    # Class 1: hidden in both scenarios.
    result[
        valid_values
        & (values_2026 == INVISIBLE_VALUE)
        & (values_2230 == INVISIBLE_VALUE)
    ] = 1

    # Class 2: visible in both scenarios.
    result[
        valid_values
        & (values_2026 == VISIBLE_VALUE)
        & (values_2230 == VISIBLE_VALUE)
    ] = 2

    # Class 3: visibility loss.
    result[
        valid_values
        & (values_2026 == VISIBLE_VALUE)
        & (values_2230 == INVISIBLE_VALUE)
    ] = 3

    # Class 4: visibility gain.
    result[
        valid_values
        & (values_2026 == INVISIBLE_VALUE)
        & (values_2230 == VISIBLE_VALUE)
    ] = 4

    return result