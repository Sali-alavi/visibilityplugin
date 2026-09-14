# -*- coding: utf-8 -*-

"""
DOM surface-model viewing-angle and analysis-boundary operations.

Outputs:
- viewing_angle_2026.tif
- viewing_angle_2230.tif
- viewing_angle_difference_2230_minus_2026.tif
- not_visible_2026_mask.tif
- not_visible_2230_mask.tif

Viewing-angle formula:

    beta = atan((z_surface - z_eye) / horizontal_distance) * 180 / pi

The observer is positioned separately on each scenario surface model:

    z_eye_2026 = z_dom_2026_at_observer + eye_height
    z_eye_2230 = z_dom_2230_at_observer + eye_height

Thus, the observer moves vertically with the DOM in each scenario.
"""

from pathlib import Path

import numpy
from osgeo import gdal, ogr, osr


VIEWSHED_VISIBLE = 1
VIEWSHED_NOT_VISIBLE = 0

BYTE_NODATA = 255
FLOAT_NODATA = -9999.0


class SurfaceAnalysisError(RuntimeError):
    """
    Raised when DOM surface-analysis processing fails.
    """


def generate_surface_outputs(
    dom_2026_path,
    dom_2230_path,
    viewshed_2026_path,
    viewshed_2230_path,
    boundary_wkt,
    observer_x,
    observer_y,
    eye_height,
    output_folder,
):
    """
    Creates DOM viewing-angle outputs and Not-visible overlays.

    Processing steps:
    1. Creates an in-memory raster mask from the analysis boundary.
    2. Sets Viewshed pixels outside the polygon to NoData.
    3. Samples the DOM elevation at the observer location for each year.
    4. Calculates vertical viewing angles for all valid DOM pixels
       inside the analysis boundary.
    5. Calculates beta difference: 2230 minus 2026.
    6. Creates Not-visible mask overlays from the Viewshed outputs.

    Parameters
    ----------
    dom_2026_path : str | Path
        Existing/current DOM raster.
    dom_2230_path : str | Path
        Future DOM raster.
    viewshed_2026_path : str | Path
        Existing/current Viewshed output raster.
    viewshed_2230_path : str | Path
        Future Viewshed output raster.
    boundary_wkt : str
        Analysis-boundary polygon geometry in DOM CRS as WKT.
    observer_x : float
        Observer X coordinate in DOM CRS.
    observer_y : float
        Observer Y coordinate in DOM CRS.
    eye_height : float
        Eye height above the DOM surface in metres.
    output_folder : str | Path
        Target output folder.

    Returns
    -------
    dict
        Paths to generated outputs and observer eye elevations.
    """

    output_folder = Path(output_folder)
    output_folder.mkdir(
        parents=True,
        exist_ok=True,
    )

    outputs = {
        "angle_2026": (
            output_folder
            / "viewing_angle_2026.tif"
        ),
        "angle_2230": (
            output_folder
            / "viewing_angle_2230.tif"
        ),
        "angle_difference": (
            output_folder
            / "viewing_angle_difference_2230_minus_2026.tif"
        ),
        "not_visible_2026": (
            output_folder
            / "not_visible_2026_mask.tif"
        ),
        "not_visible_2230": (
            output_folder
            / "not_visible_2230_mask.tif"
        ),
    }

    dom_2026_path = Path(dom_2026_path)
    dom_2230_path = Path(dom_2230_path)
    viewshed_2026_path = Path(viewshed_2026_path)
    viewshed_2230_path = Path(viewshed_2230_path)

    for source_path in (
        dom_2026_path,
        dom_2230_path,
        viewshed_2026_path,
        viewshed_2230_path,
    ):
        if not source_path.is_file():
            raise SurfaceAnalysisError(
                "Required raster does not exist:\n"
                f"{source_path}"
            )

    gdal.UseExceptions()

    dom_2026 = None
    dom_2230 = None
    viewshed_2026 = None
    viewshed_2230 = None
    mask_dataset = None

    try:
        dom_2026 = gdal.Open(
            str(dom_2026_path),
            gdal.GA_ReadOnly,
        )

        dom_2230 = gdal.Open(
            str(dom_2230_path),
            gdal.GA_ReadOnly,
        )

        # Viewsheds are opened in update mode because pixels outside
        # the analysis boundary will be changed to NoData.
        viewshed_2026 = gdal.Open(
            str(viewshed_2026_path),
            gdal.GA_Update,
        )

        viewshed_2230 = gdal.Open(
            str(viewshed_2230_path),
            gdal.GA_Update,
        )

        if dom_2026 is None:
            raise SurfaceAnalysisError(
                "Could not open DOM 2026."
            )

        if dom_2230 is None:
            raise SurfaceAnalysisError(
                "Could not open DOM 2230."
            )

        if viewshed_2026 is None:
            raise SurfaceAnalysisError(
                "Could not open Viewshed 2026 for update."
            )

        if viewshed_2230 is None:
            raise SurfaceAnalysisError(
                "Could not open Viewshed 2230 for update."
            )

        _validate_alignment(
            dom_2026,
            dom_2230,
        )

        _validate_alignment(
            dom_2026,
            viewshed_2026,
        )

        _validate_alignment(
            dom_2026,
            viewshed_2230,
        )

        mask_dataset = _create_boundary_mask(
            reference_dataset=dom_2026,
            boundary_wkt=boundary_wkt,
        )

        _apply_boundary_mask_to_viewshed(
            viewshed_dataset=viewshed_2026,
            mask_dataset=mask_dataset,
        )

        _apply_boundary_mask_to_viewshed(
            viewshed_dataset=viewshed_2230,
            mask_dataset=mask_dataset,
        )

        observer_surface_2026 = _sample_raster_nearest(
            dataset=dom_2026,
            x_coordinate=float(observer_x),
            y_coordinate=float(observer_y),
        )

        observer_surface_2230 = _sample_raster_nearest(
            dataset=dom_2230,
            x_coordinate=float(observer_x),
            y_coordinate=float(observer_y),
        )

        eye_elevation_2026 = (
            observer_surface_2026
            + float(eye_height)
        )

        eye_elevation_2230 = (
            observer_surface_2230
            + float(eye_height)
        )

        _create_viewing_angle_outputs(
            dom_2026=dom_2026,
            dom_2230=dom_2230,
            viewshed_2026=viewshed_2026,
            viewshed_2230=viewshed_2230,
            mask_dataset=mask_dataset,
            observer_x=float(observer_x),
            observer_y=float(observer_y),
            eye_elevation_2026=eye_elevation_2026,
            eye_elevation_2230=eye_elevation_2230,
            outputs=outputs,
        )

        outputs["observer_surface_2026"] = (
            observer_surface_2026
        )

        outputs["observer_surface_2230"] = (
            observer_surface_2230
        )

        outputs["eye_elevation_2026"] = (
            eye_elevation_2026
        )

        outputs["eye_elevation_2230"] = (
            eye_elevation_2230
        )

        return outputs

    except SurfaceAnalysisError:
        raise

    except Exception as error:
        raise SurfaceAnalysisError(
            "Surface-model viewing-angle analysis failed:\n"
            f"{type(error).__name__}: {error}"
        ) from error

    finally:
        mask_dataset = None
        viewshed_2026 = None
        viewshed_2230 = None
        dom_2026 = None
        dom_2230 = None


def _create_boundary_mask(
    reference_dataset,
    boundary_wkt,
):
    """
    Creates an in-memory boundary mask aligned with the reference DOM.

    Mask values:
        1 = inside analysis boundary
        0 = outside analysis boundary

    RasterizeLayer is used because it is available in the GDAL Python
    bindings distributed with QGIS.
    """

    width = int(
        reference_dataset.RasterXSize
    )

    height = int(
        reference_dataset.RasterYSize
    )

    geotransform = reference_dataset.GetGeoTransform()
    projection = reference_dataset.GetProjection()

    if geotransform is None:
        raise SurfaceAnalysisError(
            "Reference DOM has no GeoTransform."
        )

    if not projection:
        raise SurfaceAnalysisError(
            "Reference DOM has no CRS projection."
        )

    boundary_geometry = ogr.CreateGeometryFromWkt(
        boundary_wkt
    )

    if boundary_geometry is None:
        raise SurfaceAnalysisError(
            "Could not create analysis-boundary geometry from WKT."
        )

    raster_memory_driver = gdal.GetDriverByName(
        "MEM"
    )

    if raster_memory_driver is None:
        raise SurfaceAnalysisError(
            "GDAL MEM raster driver is not available."
        )

    mask_dataset = raster_memory_driver.Create(
        "",
        width,
        height,
        1,
        gdal.GDT_Byte,
    )

    if mask_dataset is None:
        raise SurfaceAnalysisError(
            "Could not create in-memory boundary mask raster."
        )

    mask_dataset.SetGeoTransform(
        geotransform
    )

    mask_dataset.SetProjection(
        projection
    )

    mask_band = mask_dataset.GetRasterBand(1)

    if mask_band is None:
        raise SurfaceAnalysisError(
            "Could not access boundary mask raster band."
        )

    # Outside the polygon: 0
    # Inside the polygon: 1
    mask_band.Fill(0)
    mask_band.SetNoDataValue(0)

    spatial_reference = osr.SpatialReference()

    spatial_reference.ImportFromWkt(
        projection
    )

    vector_memory_driver = ogr.GetDriverByName(
        "Memory"
    )

    if vector_memory_driver is None:
        raise SurfaceAnalysisError(
            "OGR Memory vector driver is not available."
        )

    vector_dataset = vector_memory_driver.CreateDataSource(
        "analysis_boundary"
    )

    if vector_dataset is None:
        raise SurfaceAnalysisError(
            "Could not create in-memory boundary vector dataset."
        )

    # wkbUnknown allows Polygon, MultiPolygon and PolygonZ geometries.
    boundary_layer = vector_dataset.CreateLayer(
        "boundary",
        spatial_reference,
        ogr.wkbUnknown,
    )

    if boundary_layer is None:
        raise SurfaceAnalysisError(
            "Could not create in-memory boundary vector layer."
        )

    boundary_feature = ogr.Feature(
        boundary_layer.GetLayerDefn()
    )

    boundary_feature.SetGeometry(
        boundary_geometry
    )

    create_result = boundary_layer.CreateFeature(
        boundary_feature
    )

    if create_result != ogr.OGRERR_NONE:
        raise SurfaceAnalysisError(
            "Could not create analysis-boundary feature."
        )

    boundary_feature = None

    rasterize_result = gdal.RasterizeLayer(
        mask_dataset,
        [1],
        boundary_layer,
        burn_values=[1],
    )

    if rasterize_result != gdal.CE_None:
        raise SurfaceAnalysisError(
            "Could not rasterize analysis-boundary polygon."
        )

    mask_band.FlushCache()
    mask_dataset.FlushCache()

    # Rasterization has completed. The memory vector datasource is no
    # longer required; the resulting raster mask remains available.
    boundary_layer = None
    vector_dataset = None

    return mask_dataset


def _apply_boundary_mask_to_viewshed(
    viewshed_dataset,
    mask_dataset,
):
    """
    Changes Viewshed pixels outside the boundary polygon to NoData.
    """

    viewshed_band = viewshed_dataset.GetRasterBand(1)
    mask_band = mask_dataset.GetRasterBand(1)

    if viewshed_band is None:
        raise SurfaceAnalysisError(
            "Could not access Viewshed raster band."
        )

    if mask_band is None:
        raise SurfaceAnalysisError(
            "Could not access boundary-mask raster band."
        )

    width = int(
        viewshed_dataset.RasterXSize
    )

    height = int(
        viewshed_dataset.RasterYSize
    )

    block_height = 512

    for y_offset in range(
        0,
        height,
        block_height,
    ):
        current_height = min(
            block_height,
            height - y_offset,
        )

        viewshed_values = viewshed_band.ReadAsArray(
            0,
            y_offset,
            width,
            current_height,
        )

        mask_values = mask_band.ReadAsArray(
            0,
            y_offset,
            width,
            current_height,
        )

        if viewshed_values is None:
            raise SurfaceAnalysisError(
                "Could not read Viewshed values while applying boundary mask."
            )

        if mask_values is None:
            raise SurfaceAnalysisError(
                "Could not read boundary-mask values."
            )

        viewshed_values[
            mask_values != 1
        ] = BYTE_NODATA

        viewshed_band.WriteArray(
            viewshed_values,
            0,
            y_offset,
        )

    viewshed_band.SetNoDataValue(
        BYTE_NODATA
    )

    viewshed_band.FlushCache()
    viewshed_dataset.FlushCache()


def _create_viewing_angle_outputs(
    dom_2026,
    dom_2230,
    viewshed_2026,
    viewshed_2230,
    mask_dataset,
    observer_x,
    observer_y,
    eye_elevation_2026,
    eye_elevation_2230,
    outputs,
):
    """
    Creates all viewing-angle and Not-visible output rasters.
    """

    for output_path in outputs.values():
        if (
            isinstance(output_path, Path)
            and output_path.exists()
        ):
            try:
                output_path.unlink()

            except OSError as error:
                raise SurfaceAnalysisError(
                    "Could not overwrite existing output:\n"
                    f"{output_path}\n\n{error}"
                ) from error

    width = int(
        dom_2026.RasterXSize
    )

    height = int(
        dom_2026.RasterYSize
    )

    geotransform = dom_2026.GetGeoTransform()
    projection = dom_2026.GetProjection()

    if geotransform is None or not projection:
        raise SurfaceAnalysisError(
            "DOM 2026 has no valid GeoTransform or CRS."
        )

    driver = gdal.GetDriverByName(
        "GTiff"
    )

    if driver is None:
        raise SurfaceAnalysisError(
            "GDAL GeoTIFF driver is not available."
        )

    creation_options = [
        "COMPRESS=LZW",
        "TILED=YES",
        "BIGTIFF=IF_SAFER",
    ]

    angle_2026_dataset = driver.Create(
        str(outputs["angle_2026"]),
        width,
        height,
        1,
        gdal.GDT_Float32,
        creation_options,
    )

    angle_2230_dataset = driver.Create(
        str(outputs["angle_2230"]),
        width,
        height,
        1,
        gdal.GDT_Float32,
        creation_options,
    )

    difference_dataset = driver.Create(
        str(outputs["angle_difference"]),
        width,
        height,
        1,
        gdal.GDT_Float32,
        creation_options,
    )

    not_visible_2026_dataset = driver.Create(
        str(outputs["not_visible_2026"]),
        width,
        height,
        1,
        gdal.GDT_Byte,
        creation_options,
    )

    not_visible_2230_dataset = driver.Create(
        str(outputs["not_visible_2230"]),
        width,
        height,
        1,
        gdal.GDT_Byte,
        creation_options,
    )

    output_datasets = [
        angle_2026_dataset,
        angle_2230_dataset,
        difference_dataset,
        not_visible_2026_dataset,
        not_visible_2230_dataset,
    ]

    for dataset in output_datasets:
        if dataset is None:
            raise SurfaceAnalysisError(
                "Could not create one or more output rasters."
            )

    try:
        for dataset in output_datasets:
            dataset.SetGeoTransform(
                geotransform
            )

            dataset.SetProjection(
                projection
            )

        angle_2026_band = angle_2026_dataset.GetRasterBand(1)
        angle_2230_band = angle_2230_dataset.GetRasterBand(1)
        difference_band = difference_dataset.GetRasterBand(1)

        not_visible_2026_band = (
            not_visible_2026_dataset.GetRasterBand(1)
        )

        not_visible_2230_band = (
            not_visible_2230_dataset.GetRasterBand(1)
        )

        for band in (
            angle_2026_band,
            angle_2230_band,
            difference_band,
        ):
            band.SetNoDataValue(
                FLOAT_NODATA
            )

        for band in (
            not_visible_2026_band,
            not_visible_2230_band,
        ):
            band.SetNoDataValue(
                BYTE_NODATA
            )

        dom_2026_band = dom_2026.GetRasterBand(1)
        dom_2230_band = dom_2230.GetRasterBand(1)

        viewshed_2026_band = viewshed_2026.GetRasterBand(1)
        viewshed_2230_band = viewshed_2230.GetRasterBand(1)

        mask_band = mask_dataset.GetRasterBand(1)

        if (
            dom_2026_band is None
            or dom_2230_band is None
            or viewshed_2026_band is None
            or viewshed_2230_band is None
            or mask_band is None
        ):
            raise SurfaceAnalysisError(
                "Could not access one or more required raster bands."
            )

        dom_2026_nodata = dom_2026_band.GetNoDataValue()
        dom_2230_nodata = dom_2230_band.GetNoDataValue()

        block_height = 256

        column_indices = numpy.arange(
            width,
            dtype=numpy.float64,
        )

        pixel_column_centres = (
            column_indices + 0.5
        )

        for y_offset in range(
            0,
            height,
            block_height,
        ):
            current_height = min(
                block_height,
                height - y_offset,
            )

            dom_values_2026 = dom_2026_band.ReadAsArray(
                0,
                y_offset,
                width,
                current_height,
            )

            dom_values_2230 = dom_2230_band.ReadAsArray(
                0,
                y_offset,
                width,
                current_height,
            )

            viewshed_values_2026 = (
                viewshed_2026_band.ReadAsArray(
                    0,
                    y_offset,
                    width,
                    current_height,
                )
            )

            viewshed_values_2230 = (
                viewshed_2230_band.ReadAsArray(
                    0,
                    y_offset,
                    width,
                    current_height,
                )
            )

            mask_values = mask_band.ReadAsArray(
                0,
                y_offset,
                width,
                current_height,
            )

            if (
                dom_values_2026 is None
                or dom_values_2230 is None
                or viewshed_values_2026 is None
                or viewshed_values_2230 is None
                or mask_values is None
            ):
                raise SurfaceAnalysisError(
                    "Could not read raster values during angle calculation."
                )

            dom_values_2026 = dom_values_2026.astype(
                numpy.float64
            )

            dom_values_2230 = dom_values_2230.astype(
                numpy.float64
            )

            row_indices = numpy.arange(
                y_offset,
                y_offset + current_height,
                dtype=numpy.float64,
            )

            pixel_row_centres = (
                row_indices + 0.5
            )

            # Supports normal north-up rasters and also rotated grids.
            pixel_x = (
                geotransform[0]
                + (
                    pixel_column_centres[numpy.newaxis, :]
                    * geotransform[1]
                )
                + (
                    pixel_row_centres[:, numpy.newaxis]
                    * geotransform[2]
                )
            )

            pixel_y = (
                geotransform[3]
                + (
                    pixel_column_centres[numpy.newaxis, :]
                    * geotransform[4]
                )
                + (
                    pixel_row_centres[:, numpy.newaxis]
                    * geotransform[5]
                )
            )

            horizontal_distance = numpy.sqrt(
                (pixel_x - observer_x) ** 2
                + (pixel_y - observer_y) ** 2
            )

            valid_2026 = (
                (mask_values == 1)
                & numpy.isfinite(dom_values_2026)
            )

            valid_2230 = (
                (mask_values == 1)
                & numpy.isfinite(dom_values_2230)
            )

            if dom_2026_nodata is not None:
                valid_2026 &= (
                    dom_values_2026
                    != dom_2026_nodata
                )

            if dom_2230_nodata is not None:
                valid_2230 &= (
                    dom_values_2230
                    != dom_2230_nodata
                )

            # The observer cell itself has distance zero. Its vertical
            # viewing angle is undefined and remains NoData.
            valid_distance = (
                horizontal_distance > 0.001
            )

            angle_valid_2026 = (
                valid_2026
                & valid_distance
            )

            angle_valid_2230 = (
                valid_2230
                & valid_distance
            )

            angle_values_2026 = numpy.full(
                (current_height, width),
                FLOAT_NODATA,
                dtype=numpy.float32,
            )

            angle_values_2230 = numpy.full(
                (current_height, width),
                FLOAT_NODATA,
                dtype=numpy.float32,
            )

            angle_values_2026[
                angle_valid_2026
            ] = numpy.degrees(
                numpy.arctan(
                    (
                        dom_values_2026[
                            angle_valid_2026
                        ]
                        - eye_elevation_2026
                    )
                    / horizontal_distance[
                        angle_valid_2026
                    ]
                )
            )

            angle_values_2230[
                angle_valid_2230
            ] = numpy.degrees(
                numpy.arctan(
                    (
                        dom_values_2230[
                            angle_valid_2230
                        ]
                        - eye_elevation_2230
                    )
                    / horizontal_distance[
                        angle_valid_2230
                    ]
                )
            )

            difference_values = numpy.full(
                (current_height, width),
                FLOAT_NODATA,
                dtype=numpy.float32,
            )

            difference_valid = (
                angle_valid_2026
                & angle_valid_2230
            )

            difference_values[
                difference_valid
            ] = (
                angle_values_2230[
                    difference_valid
                ]
                - angle_values_2026[
                    difference_valid
                ]
            )

            # Mask output convention:
            # 1   = Not visible
            # 255 = Visible, outside boundary or invalid / NoData
            not_visible_values_2026 = numpy.full(
                (current_height, width),
                BYTE_NODATA,
                dtype=numpy.uint8,
            )

            not_visible_values_2230 = numpy.full(
                (current_height, width),
                BYTE_NODATA,
                dtype=numpy.uint8,
            )

            not_visible_values_2026[
                valid_2026
                & (
                    viewshed_values_2026
                    == VIEWSHED_NOT_VISIBLE
                )
            ] = 1

            not_visible_values_2230[
                valid_2230
                & (
                    viewshed_values_2230
                    == VIEWSHED_NOT_VISIBLE
                )
            ] = 1

            angle_2026_band.WriteArray(
                angle_values_2026,
                0,
                y_offset,
            )

            angle_2230_band.WriteArray(
                angle_values_2230,
                0,
                y_offset,
            )

            difference_band.WriteArray(
                difference_values,
                0,
                y_offset,
            )

            not_visible_2026_band.WriteArray(
                not_visible_values_2026,
                0,
                y_offset,
            )

            not_visible_2230_band.WriteArray(
                not_visible_values_2230,
                0,
                y_offset,
            )

        for dataset in output_datasets:
            dataset.FlushCache()

    finally:
        angle_2026_dataset = None
        angle_2230_dataset = None
        difference_dataset = None
        not_visible_2026_dataset = None
        not_visible_2230_dataset = None


def _sample_raster_nearest(
    dataset,
    x_coordinate,
    y_coordinate,
):
    """
    Samples the DOM value at the observer location using nearest pixel.

    The DOM grid must not be rotated for this operation. This applies to
    the supplied EPSG:25832 DOM files, which use a normal north-up grid.
    """

    geotransform = dataset.GetGeoTransform()

    if geotransform is None:
        raise SurfaceAnalysisError(
            "DOM has no GeoTransform."
        )

    if (
        abs(geotransform[2]) > 1e-12
        or abs(geotransform[4]) > 1e-12
    ):
        raise SurfaceAnalysisError(
            "Rotated raster grids are not supported for observer sampling."
        )

    pixel_width = geotransform[1]
    pixel_height = geotransform[5]

    if pixel_width == 0 or pixel_height == 0:
        raise SurfaceAnalysisError(
            "DOM has an invalid pixel size."
        )

    pixel_column = int(
        (x_coordinate - geotransform[0])
        / pixel_width
    )

    pixel_row = int(
        (y_coordinate - geotransform[3])
        / pixel_height
    )

    if (
        pixel_column < 0
        or pixel_row < 0
        or pixel_column >= dataset.RasterXSize
        or pixel_row >= dataset.RasterYSize
    ):
        raise SurfaceAnalysisError(
            "Observer point is outside the DOM raster."
        )

    band = dataset.GetRasterBand(1)

    if band is None:
        raise SurfaceAnalysisError(
            "Could not access DOM raster band 1."
        )

    values = band.ReadAsArray(
        pixel_column,
        pixel_row,
        1,
        1,
    )

    if values is None:
        raise SurfaceAnalysisError(
            "Could not sample DOM elevation at observer location."
        )

    elevation = float(
        values[0, 0]
    )

    nodata = band.GetNoDataValue()

    if not numpy.isfinite(elevation):
        raise SurfaceAnalysisError(
            "Observer point is on an invalid DOM pixel."
        )

    if (
        nodata is not None
        and elevation == nodata
    ):
        raise SurfaceAnalysisError(
            "Observer point is on a NoData pixel in the DOM."
        )

    return elevation


def _validate_alignment(
    dataset_a,
    dataset_b,
):
    """
    Verifies strict pixel-grid alignment of two raster datasets.
    """

    if (
        dataset_a.RasterXSize
        != dataset_b.RasterXSize
        or dataset_a.RasterYSize
        != dataset_b.RasterYSize
    ):
        raise SurfaceAnalysisError(
            "Input rasters are not grid-aligned: "
            "different raster dimensions."
        )

    projection_a = dataset_a.GetProjection()
    projection_b = dataset_b.GetProjection()

    if projection_a != projection_b:
        raise SurfaceAnalysisError(
            "Input rasters are not grid-aligned: "
            "different CRS definitions."
        )

    transform_a = dataset_a.GetGeoTransform()
    transform_b = dataset_b.GetGeoTransform()

    if transform_a is None or transform_b is None:
        raise SurfaceAnalysisError(
            "Input rasters are missing GeoTransform values."
        )

    tolerance = 1e-9

    for value_a, value_b in zip(
        transform_a,
        transform_b,
    ):
        if abs(value_a - value_b) > tolerance:
            raise SurfaceAnalysisError(
                "Input rasters are not grid-aligned: "
                "GeoTransform values differ."
            )