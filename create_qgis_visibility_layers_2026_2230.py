from pathlib import Path
import math

from qgis.PyQt.QtCore import QVariant

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsRasterLayer,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsVectorFileWriter,
    QgsProject,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsSingleSymbolRenderer,
    QgsRuleBasedRenderer,
)

# =========================================================
# SETTINGS
# =========================================================

LINE_PATH = Path(
    r"D:\Sali_IPRO\1.projects\3DVisualiyation\vector\SOL.gpkg"
)

# Current terrain: 2026
DEM_2026_PATH = Path(
    r"D:\37_K+S_Nienburger_Mulde\260603_Landschaftsbild\dgm\32650-tiff-dgm2.tif"
)

# Future terrain: 2230
DEM_2230_PATH = Path(
    r"D:\Sali_IPRO\1.projects\3DVisualiyation\raster\DEM_2230.tif"
)

OUTPUT_DIR = Path(
    r"D:\Sali_IPRO\1.projects\3DVisualiyation\output\qgis_visibility_results_2026_2230"
)

GPKG_PATH = (
    OUTPUT_DIR
    / "visibility_results_2026_2230.gpkg"
)

STYLE_DIR = (
    OUTPUT_DIR
    / "styles"
)

# Sampling interval along each profile [m]
SAMPLE_INTERVAL = 2.0

# Observer height above terrain [m]
CAMERA_HEIGHT = 1.8

# Identifier field in SOL.gpkg
PNUMBER_FIELD = "PNumber"

# Numerical tolerance for visibility calculation
ANGLE_TOLERANCE = 1e-9


# =========================================================
# INITIALIZE QGIS
# =========================================================

qgs = QgsApplication([], False)
qgs.initQgis()

try:

    # =====================================================
    # CREATE OUTPUT DIRECTORIES
    # =====================================================

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    STYLE_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # =====================================================
    # CHECK INPUT FILES
    # =====================================================

    input_files = [
        (LINE_PATH, "Profile line layer"),
        (DEM_2026_PATH, "DEM 2026"),
        (DEM_2230_PATH, "DEM 2230"),
    ]

    for input_path, description in input_files:

        if not input_path.exists():

            raise FileNotFoundError(
                f"{description} was not found:\n"
                f"{input_path}"
            )

    # =====================================================
    # REMOVE PREVIOUS OUTPUT GEOPACKAGE
    # =====================================================

    if GPKG_PATH.exists():

        try:

            GPKG_PATH.unlink()

        except PermissionError:

            raise RuntimeError(
                f"Could not overwrite:\n"
                f"{GPKG_PATH}\n\n"
                "Remove the GeoPackage layers from QGIS, "
                "close QGIS if necessary, and run the "
                "script again."
            )

    # =====================================================
    # LOAD INPUT DATA
    # =====================================================

    lines = QgsVectorLayer(
        str(LINE_PATH),
        "SOL",
        "ogr"
    )

    dem_2026 = QgsRasterLayer(
        str(DEM_2026_PATH),
        "DEM_2026"
    )

    dem_2230 = QgsRasterLayer(
        str(DEM_2230_PATH),
        "DEM_2230"
    )

    # =====================================================
    # VALIDATE INPUT LAYERS
    # =====================================================

    if not lines.isValid():

        raise RuntimeError(
            f"Could not load the profile line layer:\n"
            f"{LINE_PATH}"
        )

    if not dem_2026.isValid():

        raise RuntimeError(
            f"Could not load DEM 2026:\n"
            f"{DEM_2026_PATH}"
        )

    if not dem_2230.isValid():

        raise RuntimeError(
            f"Could not load DEM 2230:\n"
            f"{DEM_2230_PATH}"
        )

    print("Input layers loaded successfully.")

    print(
        "Line CRS:",
        lines.crs().authid()
    )

    print(
        "DEM 2026 CRS:",
        dem_2026.crs().authid()
    )

    print(
        "DEM 2230 CRS:",
        dem_2230.crs().authid()
    )

    # =====================================================
    # CRS CHECK
    # =====================================================

    if not lines.crs().isValid():

        raise RuntimeError(
            "The CRS of the profile line layer is invalid."
        )

    if not dem_2026.crs().isValid():

        raise RuntimeError(
            "The CRS of DEM 2026 is invalid."
        )

    if not dem_2230.crs().isValid():

        raise RuntimeError(
            "The CRS of DEM 2230 is invalid."
        )

    if not (
        lines.crs() == dem_2026.crs()
        and lines.crs() == dem_2230.crs()
    ):

        raise RuntimeError(
            "CRS mismatch.\n"
            "The line layer, DEM 2026 and DEM 2230 "
            "must use the same CRS."
        )

    # Do not evaluate mapUnits() as True/False.
    print(
        "Line layer map units:",
        lines.crs().mapUnits()
    )

    print(
        "CRS check completed successfully."
    )

    # =====================================================
    # FIELD CHECK
    # =====================================================

    available_fields = (
        lines.fields().names()
    )

    if PNUMBER_FIELD not in available_fields:

        raise RuntimeError(
            f"Field '{PNUMBER_FIELD}' was not found.\n"
            f"Available fields: {available_fields}"
        )

    crs_authid = (
        lines.crs().authid()
    )

    # =====================================================
    # HELPER FUNCTION: SAMPLE RASTER
    # =====================================================

    def sample_raster(raster, point):
        """
        Samples Band 1 at a point.

        Returns None for:
        - unsuccessful samples
        - NoData
        - nonnumeric values
        - NaN
        - infinite values
        """

        value, ok = (
            raster
            .dataProvider()
            .sample(
                point,
                1
            )
        )

        if not ok or value is None:
            return None

        try:

            value = float(value)

        except (TypeError, ValueError):

            return None

        if not math.isfinite(value):
            return None

        return value

    # =====================================================
    # HELPER FUNCTION: SAMPLE DISTANCES
    # =====================================================

    def create_distances(length):
        """
        Creates:

        0, 2, 4, 6, ...

        The exact endpoint is added if necessary.
        """

        distances = []
        distance = 0.0

        while distance <= length:

            distances.append(
                distance
            )

            distance += SAMPLE_INTERVAL

        if (
            not distances
            or abs(distances[-1] - length) > 1e-8
        ):

            distances.append(
                length
            )

        return distances

    # =====================================================
    # HELPER FUNCTION: VIEWING ANGLE
    # =====================================================

    def calculate_beta(
        terrain_elevation,
        eye_elevation,
        distance
    ):
        """
        Calculates the vertical viewing angle:

        beta = atan2(
            terrain elevation - eye elevation,
            horizontal distance
        )

        Positive beta:
            terrain is above the eye elevation.

        Negative beta:
            terrain is below the eye elevation.

        Beta is undefined at distance zero.
        """

        if terrain_elevation is None:
            return None

        if eye_elevation is None:
            return None

        if distance <= 0:
            return None

        return math.degrees(
            math.atan2(
                terrain_elevation - eye_elevation,
                distance
            )
        )

    # =====================================================
    # HELPER FUNCTION: VISIBILITY
    # =====================================================

    def calculate_visibility(
        rows,
        beta_key,
        visibility_key
    ):
        """
        One-dimensional terrain-horizon test.

        A point is visible if its viewing angle is greater
        than the maximum viewing angle of all preceding
        valid points.
        """

        maximum_previous_beta = -math.inf

        for row in rows:

            beta = row[beta_key]

            if beta is None:

                row[visibility_key] = None
                continue

            if maximum_previous_beta == -math.inf:

                visible = True

            else:

                visible = (
                    beta
                    > maximum_previous_beta
                    + ANGLE_TOLERANCE
                )

            row[visibility_key] = (
                "Visible"
                if visible
                else "Hidden"
            )

            if beta > maximum_previous_beta:

                maximum_previous_beta = beta

    # =====================================================
    # HELPER FUNCTIONS: STATISTICS
    # =====================================================

    def valid_values(values):

        return [
            value
            for value in values
            if value is not None
            and math.isfinite(value)
        ]

    def mean_or_none(values):

        values = valid_values(
            values
        )

        if not values:
            return None

        return (
            sum(values)
            / len(values)
        )

    def min_or_none(values):

        values = valid_values(
            values
        )

        if not values:
            return None

        return min(
            values
        )

    def max_or_none(values):

        values = valid_values(
            values
        )

        if not values:
            return None

        return max(
            values
        )

    # =====================================================
    # HELPER FUNCTION: ADD FEATURE
    # =====================================================

    def add_feature(
        layer,
        geometry,
        attributes
    ):
        """
        Adds one feature to a memory layer.
        """

        feature = QgsFeature(
            layer.fields()
        )

        feature.setGeometry(
            geometry
        )

        feature.setAttributes(
            attributes
        )

        success = (
            layer
            .dataProvider()
            .addFeature(
                feature
            )
        )

        if not success:

            raise RuntimeError(
                f"Could not add a feature to "
                f"'{layer.name()}'."
            )

    # =====================================================
    # HELPER FUNCTION: WRITE GEOPACKAGE LAYER
    # =====================================================

    def write_layer(
        memory_layer,
        layer_name,
        first_layer=False
    ):
        """
        Writes a memory layer to the output GeoPackage.
        """

        options = (
            QgsVectorFileWriter
            .SaveVectorOptions()
        )

        options.driverName = "GPKG"
        options.layerName = layer_name
        options.fileEncoding = "UTF-8"

        if first_layer:

            options.actionOnExistingFile = (
                QgsVectorFileWriter
                .CreateOrOverwriteFile
            )

        else:

            options.actionOnExistingFile = (
                QgsVectorFileWriter
                .CreateOrOverwriteLayer
            )

        result = (
            QgsVectorFileWriter
            .writeAsVectorFormatV3(
                memory_layer,
                str(GPKG_PATH),
                QgsProject.instance().transformContext(),
                options
            )
        )

        if result[0] != QgsVectorFileWriter.NoError:

            raise RuntimeError(
                f"Could not write layer '{layer_name}'.\n"
                f"Writer result: {result}"
            )

        print(
            f"GeoPackage layer created: {layer_name}"
        )

    # =====================================================
    # CREATE SAMPLE-POINT LAYER
    # =====================================================

    sample_layer = QgsVectorLayer(
        f"Point?crs={crs_authid}",
        "profile_samples",
        "memory"
    )

    sample_provider = (
        sample_layer.dataProvider()
    )

    sample_provider.addAttributes(
        [
            QgsField(
                "PNumber",
                QVariant.String
            ),

            QgsField(
                "distance_m",
                QVariant.Double
            ),

            QgsField(
                "z_2026",
                QVariant.Double
            ),

            QgsField(
                "z_2230",
                QVariant.Double
            ),

            # z_2230 - z_2026
            QgsField(
                "dz_m",
                QVariant.Double
            ),

            QgsField(
                "beta_2026",
                QVariant.Double
            ),

            QgsField(
                "beta_2230",
                QVariant.Double
            ),

            # beta_2230 - beta_2026
            QgsField(
                "delta_beta",
                QVariant.Double
            ),

            QgsField(
                "vis_2026",
                QVariant.String
            ),

            QgsField(
                "vis_2230",
                QVariant.String
            ),

            # Visibility 2026 -> Visibility 2230
            QgsField(
                "vis_change",
                QVariant.String
            ),
        ]
    )

    sample_layer.updateFields()

    # =====================================================
    # CREATE PROFILE-SEGMENT LAYER
    # =====================================================

    segment_layer = QgsVectorLayer(
        f"LineString?crs={crs_authid}",
        "profile_segments",
        "memory"
    )

    segment_provider = (
        segment_layer.dataProvider()
    )

    segment_provider.addAttributes(
        [
            QgsField(
                "PNumber",
                QVariant.String
            ),

            QgsField(
                "from_m",
                QVariant.Double
            ),

            QgsField(
                "to_m",
                QVariant.Double
            ),

            QgsField(
                "z_2026",
                QVariant.Double
            ),

            QgsField(
                "z_2230",
                QVariant.Double
            ),

            QgsField(
                "dz_m",
                QVariant.Double
            ),

            QgsField(
                "beta_2026",
                QVariant.Double
            ),

            QgsField(
                "beta_2230",
                QVariant.Double
            ),

            QgsField(
                "delta_beta",
                QVariant.Double
            ),

            QgsField(
                "vis_2026",
                QVariant.String
            ),

            QgsField(
                "vis_2230",
                QVariant.String
            ),

            QgsField(
                "vis_change",
                QVariant.String
            ),
        ]
    )

    segment_layer.updateFields()

    # =====================================================
    # CREATE CAMERA LAYER
    # =====================================================

    camera_layer = QgsVectorLayer(
        f"Point?crs={crs_authid}",
        "camera_locations",
        "memory"
    )

    camera_provider = (
        camera_layer.dataProvider()
    )

    camera_provider.addAttributes(
        [
            QgsField(
                "PNumber",
                QVariant.String
            ),

            QgsField(
                "line_len_m",
                QVariant.Double
            ),

            QgsField(
                "cam_h_m",
                QVariant.Double
            ),

            QgsField(
                "ground2026",
                QVariant.Double
            ),

            QgsField(
                "ground2230",
                QVariant.Double
            ),

            QgsField(
                "eye_2026",
                QVariant.Double
            ),

            QgsField(
                "eye_2230",
                QVariant.Double
            ),
        ]
    )

    camera_layer.updateFields()

    # =====================================================
    # CREATE PROFILE-SUMMARY LAYER
    # =====================================================

    summary_layer = QgsVectorLayer(
        f"MultiLineString?crs={crs_authid}",
        "profile_summary",
        "memory"
    )

    summary_provider = (
        summary_layer.dataProvider()
    )

    summary_provider.addAttributes(
        [
            QgsField(
                "PNumber",
                QVariant.String
            ),

            QgsField(
                "length_m",
                QVariant.Double
            ),

            QgsField(
                "samples",
                QVariant.Int
            ),

            QgsField(
                "vis2026_n",
                QVariant.Int
            ),

            QgsField(
                "hid2026_n",
                QVariant.Int
            ),

            QgsField(
                "vis2230_n",
                QVariant.Int
            ),

            QgsField(
                "hid2230_n",
                QVariant.Int
            ),

            QgsField(
                "vis2026_pc",
                QVariant.Double
            ),

            QgsField(
                "vis2230_pc",
                QVariant.Double
            ),

            # Visible 2026 -> Hidden 2230
            QgsField(
                "lost_n",
                QVariant.Int
            ),

            # Hidden 2026 -> Visible 2230
            QgsField(
                "gained_n",
                QVariant.Int
            ),

            # z_2230 - z_2026
            QgsField(
                "dz_mean",
                QVariant.Double
            ),

            QgsField(
                "dz_min",
                QVariant.Double
            ),

            QgsField(
                "dz_max",
                QVariant.Double
            ),

            # beta_2230 - beta_2026
            QgsField(
                "dbeta_mean",
                QVariant.Double
            ),

            QgsField(
                "dbeta_min",
                QVariant.Double
            ),

            QgsField(
                "dbeta_max",
                QVariant.Double
            ),
        ]
    )

    summary_layer.updateFields()

    # =====================================================
    # READ AND SORT PROFILE LINES
    # =====================================================

    features = list(
        lines.getFeatures()
    )

    features.sort(
        key=lambda feature: (
            feature[PNUMBER_FIELD] is None,
            str(feature[PNUMBER_FIELD])
        )
    )

    print(
        f"Number of input lines: {len(features)}"
    )

    processed_count = 0
    skipped_count = 0

    # =====================================================
    # PROCESS EACH PROFILE LINE
    # =====================================================

    for feature in features:

        pnumber_value = (
            feature[PNUMBER_FIELD]
        )

        if pnumber_value is None:

            print(
                "WARNING: A feature has no PNumber. "
                "Feature skipped."
            )

            skipped_count += 1
            continue

        pnumber = str(
            pnumber_value
        )

        geometry = (
            feature.geometry()
        )

        if (
            geometry is None
            or geometry.isEmpty()
        ):

            print(
                f"WARNING: PNumber={pnumber}: "
                "empty geometry."
            )

            skipped_count += 1
            continue

        length = (
            geometry.length()
        )

        if length <= 0:

            print(
                f"WARNING: PNumber={pnumber}: "
                "line length is zero."
            )

            skipped_count += 1
            continue

        print()
        print("=" * 60)

        print(
            f"Processing PNumber={pnumber} | "
            f"Length={length:.2f} m"
        )

        # =================================================
        # CAMERA LOCATION
        # =================================================

        camera_geometry = (
            geometry.interpolate(
                0.0
            )
        )

        if camera_geometry.isEmpty():

            print(
                f"WARNING: PNumber={pnumber}: "
                "camera location could not be calculated."
            )

            skipped_count += 1
            continue

        camera_point_xy = QgsPointXY(
            camera_geometry.asPoint()
        )

        # Current terrain at camera
        ground_2026 = sample_raster(
            dem_2026,
            camera_point_xy
        )

        # Future terrain at camera
        ground_2230 = sample_raster(
            dem_2230,
            camera_point_xy
        )

        if ground_2026 is None:

            print(
                f"WARNING: PNumber={pnumber}: "
                "DEM 2026 has no valid value at the "
                "camera location."
            )

            skipped_count += 1
            continue

        if ground_2230 is None:

            print(
                f"WARNING: PNumber={pnumber}: "
                "DEM 2230 has no valid value at the "
                "camera location."
            )

            skipped_count += 1
            continue

        # Observer is 1.8 m above terrain in each period.
        eye_2026 = (
            ground_2026
            + CAMERA_HEIGHT
        )

        eye_2230 = (
            ground_2230
            + CAMERA_HEIGHT
        )

        print(
            f"  DEM 2026 ground at camera: "
            f"{ground_2026:.3f} m"
        )

        print(
            f"  DEM 2026 eye elevation: "
            f"{eye_2026:.3f} m"
        )

        print(
            f"  DEM 2230 ground at camera: "
            f"{ground_2230:.3f} m"
        )

        print(
            f"  DEM 2230 eye elevation: "
            f"{eye_2230:.3f} m"
        )

        # Add camera feature
        add_feature(
            camera_layer,

            QgsGeometry.fromPointXY(
                camera_point_xy
            ),

            [
                pnumber,
                length,
                CAMERA_HEIGHT,
                ground_2026,
                ground_2230,
                eye_2026,
                eye_2230,
            ]
        )

        # =================================================
        # SAMPLE PROFILE
        # =================================================

        rows = []

        distances = create_distances(
            length
        )

        for distance in distances:

            point_geometry = (
                geometry.interpolate(
                    distance
                )
            )

            if point_geometry.isEmpty():

                print(
                    f"  WARNING: Could not create sample "
                    f"at distance {distance:.2f} m."
                )

                continue

            point_xy = QgsPointXY(
                point_geometry.asPoint()
            )

            # Current terrain
            z_2026 = sample_raster(
                dem_2026,
                point_xy
            )

            # Future terrain
            z_2230 = sample_raster(
                dem_2230,
                point_xy
            )

            # Future minus current
            delta_z = None

            if (
                z_2026 is not None
                and z_2230 is not None
            ):

                delta_z = (
                    z_2230
                    - z_2026
                )

            beta_2026 = calculate_beta(
                z_2026,
                eye_2026,
                distance
            )

            beta_2230 = calculate_beta(
                z_2230,
                eye_2230,
                distance
            )

            # Future minus current
            delta_beta = None

            if (
                beta_2026 is not None
                and beta_2230 is not None
            ):

                delta_beta = (
                    beta_2230
                    - beta_2026
                )

            rows.append(
                {
                    "distance_m": distance,
                    "point": point_xy,

                    "z_2026": z_2026,
                    "z_2230": z_2230,
                    "delta_z": delta_z,

                    "beta_2026": beta_2026,
                    "beta_2230": beta_2230,
                    "delta_beta": delta_beta,

                    "vis_2026": None,
                    "vis_2230": None,
                    "vis_change": None,
                }
            )

        if not rows:

            print(
                f"WARNING: PNumber={pnumber}: "
                "no sample points were created."
            )

            skipped_count += 1
            continue

        # =================================================
        # CALCULATE VISIBILITY
        # =================================================

        calculate_visibility(
            rows,
            "beta_2026",
            "vis_2026"
        )

        calculate_visibility(
            rows,
            "beta_2230",
            "vis_2230"
        )

        # Visibility change from current to future
        for row in rows:

            if (
                row["vis_2026"] is None
                or row["vis_2230"] is None
            ):

                row["vis_change"] = None

            else:

                row["vis_change"] = (
                    f"{row['vis_2026']} -> "
                    f"{row['vis_2230']}"
                )

        # =================================================
        # ADD SAMPLE POINTS
        # =================================================

        for row in rows:

            add_feature(
                sample_layer,

                QgsGeometry.fromPointXY(
                    row["point"]
                ),

                [
                    pnumber,
                    row["distance_m"],

                    row["z_2026"],
                    row["z_2230"],
                    row["delta_z"],

                    row["beta_2026"],
                    row["beta_2230"],
                    row["delta_beta"],

                    row["vis_2026"],
                    row["vis_2230"],
                    row["vis_change"],
                ]
            )

        # =================================================
        # CREATE PROFILE SEGMENTS
        #
        # Each segment receives the values of its endpoint.
        # =================================================

        for index in range(
            1,
            len(rows)
        ):

            previous_row = (
                rows[index - 1]
            )

            current_row = (
                rows[index]
            )

            segment_geometry = (
                QgsGeometry.fromPolylineXY(
                    [
                        previous_row["point"],
                        current_row["point"],
                    ]
                )
            )

            add_feature(
                segment_layer,

                segment_geometry,

                [
                    pnumber,

                    previous_row["distance_m"],
                    current_row["distance_m"],

                    current_row["z_2026"],
                    current_row["z_2230"],
                    current_row["delta_z"],

                    current_row["beta_2026"],
                    current_row["beta_2230"],
                    current_row["delta_beta"],

                    current_row["vis_2026"],
                    current_row["vis_2230"],
                    current_row["vis_change"],
                ]
            )

        # =================================================
        # PROFILE SUMMARY
        # =================================================

        # Distance zero is excluded because beta is undefined.
        analysis_rows = [
            row
            for row in rows
            if row["distance_m"] > 0
        ]

        valid_2026_rows = [
            row
            for row in analysis_rows
            if row["vis_2026"] is not None
        ]

        valid_2230_rows = [
            row
            for row in analysis_rows
            if row["vis_2230"] is not None
        ]

        visible_2026_count = sum(
            row["vis_2026"] == "Visible"
            for row in valid_2026_rows
        )

        hidden_2026_count = sum(
            row["vis_2026"] == "Hidden"
            for row in valid_2026_rows
        )

        visible_2230_count = sum(
            row["vis_2230"] == "Visible"
            for row in valid_2230_rows
        )

        hidden_2230_count = sum(
            row["vis_2230"] == "Hidden"
            for row in valid_2230_rows
        )

        # Visible in 2026 and hidden in 2230
        lost_count = sum(
            row["vis_change"] == "Visible -> Hidden"
            for row in analysis_rows
        )

        # Hidden in 2026 and visible in 2230
        gained_count = sum(
            row["vis_change"] == "Hidden -> Visible"
            for row in analysis_rows
        )

        if valid_2026_rows:

            visible_2026_percent = (
                visible_2026_count
                / len(valid_2026_rows)
                * 100.0
            )

        else:

            visible_2026_percent = None

        if valid_2230_rows:

            visible_2230_percent = (
                visible_2230_count
                / len(valid_2230_rows)
                * 100.0
            )

        else:

            visible_2230_percent = None

        delta_z_values = [
            row["delta_z"]
            for row in analysis_rows
        ]

        delta_beta_values = [
            row["delta_beta"]
            for row in analysis_rows
        ]

        # Convert the source line to multipart geometry
        # for the MultiLineString summary layer.
        summary_geometry = QgsGeometry(
            geometry
        )

        if not summary_geometry.isMultipart():

            conversion_success = (
                summary_geometry.convertToMultiType()
            )

            if not conversion_success:

                raise RuntimeError(
                    f"Could not convert summary geometry "
                    f"to multipart for PNumber={pnumber}."
                )

        add_feature(
            summary_layer,

            summary_geometry,

            [
                pnumber,
                length,
                len(analysis_rows),

                visible_2026_count,
                hidden_2026_count,

                visible_2230_count,
                hidden_2230_count,

                visible_2026_percent,
                visible_2230_percent,

                lost_count,
                gained_count,

                mean_or_none(delta_z_values),
                min_or_none(delta_z_values),
                max_or_none(delta_z_values),

                mean_or_none(delta_beta_values),
                min_or_none(delta_beta_values),
                max_or_none(delta_beta_values),
            ]
        )

        print(
            f"  Samples: {len(rows)}"
        )

        print(
            f"  DEM 2026: "
            f"{visible_2026_count} visible / "
            f"{hidden_2026_count} hidden"
        )

        print(
            f"  DEM 2230: "
            f"{visible_2230_count} visible / "
            f"{hidden_2230_count} hidden"
        )

        print(
            f"  Visibility lost "
            f"(Visible -> Hidden): {lost_count}"
        )

        print(
            f"  Visibility gained "
            f"(Hidden -> Visible): {gained_count}"
        )

        processed_count += 1

    # =====================================================
    # CHECK PROCESSING RESULT
    # =====================================================

    if processed_count == 0:

        raise RuntimeError(
            "No profile lines could be processed."
        )

    # =====================================================
    # UPDATE MEMORY-LAYER EXTENTS
    # =====================================================

    sample_layer.updateExtents()
    segment_layer.updateExtents()
    camera_layer.updateExtents()
    summary_layer.updateExtents()

    # =====================================================
    # WRITE GEOPACKAGE
    # =====================================================

    print()
    print("=" * 60)
    print("WRITING GEOPACKAGE")
    print("=" * 60)

    write_layer(
        sample_layer,
        "profile_samples",
        first_layer=True
    )

    write_layer(
        segment_layer,
        "profile_segments"
    )

    write_layer(
        camera_layer,
        "camera_locations"
    )

    write_layer(
        summary_layer,
        "profile_summary"
    )

    # =====================================================
    # REOPEN OUTPUT LAYERS FOR STYLE CREATION
    # =====================================================

    print()
    print("=" * 60)
    print("CREATING QGIS STYLES")
    print("=" * 60)

    segment_uri = (
        f"{GPKG_PATH}|layername=profile_segments"
    )

    segment_result_layer = QgsVectorLayer(
        segment_uri,
        "profile_segments",
        "ogr"
    )

    camera_uri = (
        f"{GPKG_PATH}|layername=camera_locations"
    )

    camera_result_layer = QgsVectorLayer(
        camera_uri,
        "camera_locations",
        "ogr"
    )

    if not segment_result_layer.isValid():

        raise RuntimeError(
            "Could not reopen profile_segments "
            "for style creation."
        )

    if not camera_result_layer.isValid():

        raise RuntimeError(
            "Could not reopen camera_locations "
            "for style creation."
        )

    # =====================================================
    # STYLE 1: DELTA BETA
    #
    # delta_beta = beta_2230 - beta_2026
    #
    # Blue:
    # viewing angle is lower in 2230.
    #
    # Red:
    # viewing angle is higher in 2230.
    # =====================================================

    delta_base_symbol = QgsLineSymbol.createSimple(
        {
            "line_color": "180,180,180",
            "line_width": "0.8",
        }
    )

    delta_renderer = QgsRuleBasedRenderer(
        delta_base_symbol
    )

    delta_root = (
        delta_renderer.rootRule()
    )

    # Remove automatically created rules.
    for child in list(
        delta_root.children()
    ):

        delta_root.removeChild(
            child
        )

    delta_rules = [
        (
            '"delta_beta" <= -0.5',
            "≤ -0.50°",
            "33,102,172"
        ),

        (
            '"delta_beta" > -0.5 '
            'AND "delta_beta" <= -0.1',
            "-0.50° to -0.10°",
            "103,169,207"
        ),

        (
            '"delta_beta" > -0.1 '
            'AND "delta_beta" < 0.1',
            "-0.10° to +0.10°",
            "220,220,220"
        ),

        (
            '"delta_beta" >= 0.1 '
            'AND "delta_beta" < 0.5',
            "+0.10° to +0.50°",
            "239,138,98"
        ),

        (
            '"delta_beta" >= 0.5',
            "≥ +0.50°",
            "178,24,43"
        ),
    ]

    for expression, label, color in delta_rules:

        symbol = QgsLineSymbol.createSimple(
            {
                "line_color": color,
                "line_width": "1.2",
                "capstyle": "round",
            }
        )

        rule = QgsRuleBasedRenderer.Rule(
            symbol
        )

        rule.setFilterExpression(
            expression
        )

        rule.setLabel(
            label
        )

        delta_root.appendChild(
            rule
        )

    # Fallback for NULL or unexpected values.
    delta_fallback_symbol = QgsLineSymbol.createSimple(
        {
            "line_color": "255,200,0",
            "line_width": "1.0",
            "line_style": "dash",
        }
    )

    delta_fallback_rule = QgsRuleBasedRenderer.Rule(
        delta_fallback_symbol
    )

    # Correct method for QGIS 3.44:
    delta_fallback_rule.setIsElse(
        True
    )

    delta_fallback_rule.setLabel(
        "Missing delta beta"
    )

    delta_root.appendChild(
        delta_fallback_rule
    )

    segment_result_layer.setRenderer(
        delta_renderer
    )

    segment_result_layer.triggerRepaint()

    delta_style_path = (
        STYLE_DIR
        / "delta_beta_2230_minus_2026.qml"
    )

    delta_style_result = (
        segment_result_layer.saveNamedStyle(
            str(delta_style_path)
        )
    )

    print(
        f"Style created: {delta_style_path.name}"
    )

    # =====================================================
    # STYLE 2: VISIBILITY CHANGE
    #
    # Direction:
    # Visibility 2026 -> Visibility 2230
    # =====================================================

    visibility_base_symbol = QgsLineSymbol.createSimple(
        {
            "line_color": "180,180,180",
            "line_width": "0.8",
            "capstyle": "round",
        }
    )

    visibility_renderer = QgsRuleBasedRenderer(
        visibility_base_symbol
    )

    visibility_root = (
        visibility_renderer.rootRule()
    )

    # Remove automatically created rules.
    for child in list(
        visibility_root.children()
    ):

        visibility_root.removeChild(
            child
        )

    visibility_rules = [
        {
            "expression": (
                'lower(trim("vis_change")) '
                "= 'visible -> visible'"
            ),
            "label": "Visible in 2026 and 2230",
            "color": "46,160,67",
            "width": "1.0",
        },

        {
            "expression": (
                'lower(trim("vis_change")) '
                "= 'hidden -> hidden'"
            ),
            "label": "Hidden in 2026 and 2230",
            "color": "160,160,160",
            "width": "0.8",
        },

        {
            "expression": (
                'lower(trim("vis_change")) '
                "= 'visible -> hidden'"
            ),
            "label": "Visibility lost by 2230",
            "color": "215,25,28",
            "width": "2.2",
        },

        {
            "expression": (
                'lower(trim("vis_change")) '
                "= 'hidden -> visible'"
            ),
            "label": "Visibility gained by 2230",
            "color": "0,170,200",
            "width": "2.2",
        },
    ]

    for definition in visibility_rules:

        symbol = QgsLineSymbol.createSimple(
            {
                "line_color": definition["color"],
                "line_width": definition["width"],
                "capstyle": "round",
            }
        )

        rule = QgsRuleBasedRenderer.Rule(
            symbol
        )

        rule.setFilterExpression(
            definition["expression"]
        )

        rule.setLabel(
            definition["label"]
        )

        visibility_root.appendChild(
            rule
        )

    # Fallback for missing or unexpected values.
    visibility_fallback_symbol = (
        QgsLineSymbol.createSimple(
            {
                "line_color": "255,200,0",
                "line_width": "1.8",
                "line_style": "dash",
                "capstyle": "round",
            }
        )
    )

    visibility_fallback_rule = (
        QgsRuleBasedRenderer.Rule(
            visibility_fallback_symbol
        )
    )

    # Correct method for QGIS 3.44:
    visibility_fallback_rule.setIsElse(
        True
    )

    visibility_fallback_rule.setLabel(
        "Other / missing visibility value"
    )

    visibility_root.appendChild(
        visibility_fallback_rule
    )

    segment_result_layer.setRenderer(
        visibility_renderer
    )

    segment_result_layer.triggerRepaint()

    visibility_style_path = (
        STYLE_DIR
        / "visibility_change_2026_to_2230.qml"
    )

    visibility_style_result = (
        segment_result_layer.saveNamedStyle(
            str(visibility_style_path)
        )
    )

    print(
        f"Style created: "
        f"{visibility_style_path.name}"
    )

    # =====================================================
    # STYLE 3: CAMERA LOCATIONS
    # =====================================================

    camera_symbol = QgsMarkerSymbol.createSimple(
        {
            "name": "triangle",
            "color": "255,215,0",
            "outline_color": "30,30,30",
            "outline_width": "0.5",
            "size": "5.0",
        }
    )

    camera_renderer = QgsSingleSymbolRenderer(
        camera_symbol
    )

    camera_result_layer.setRenderer(
        camera_renderer
    )

    camera_result_layer.triggerRepaint()

    camera_style_path = (
        STYLE_DIR
        / "camera_locations.qml"
    )

    camera_style_result = (
        camera_result_layer.saveNamedStyle(
            str(camera_style_path)
        )
    )

    print(
        f"Style created: "
        f"{camera_style_path.name}"
    )

    # =====================================================
    # FINISHED
    # =====================================================

    print()
    print("=" * 60)
    print("QGIS VISIBILITY OUTPUT COMPLETED")
    print("=" * 60)

    print(
        f"Processed lines: {processed_count}"
    )

    print(
        f"Skipped lines: {skipped_count}"
    )

    print()

    print(
        f"GeoPackage:\n{GPKG_PATH}"
    )

    print()

    print(
        f"Styles:\n{STYLE_DIR}"
    )

    print()

    print(
        "GeoPackage layers:"
    )

    print(
        "  - profile_samples"
    )

    print(
        "  - profile_segments"
    )

    print(
        "  - camera_locations"
    )

    print(
        "  - profile_summary"
    )

    print()

    print(
        "Definitions:"
    )

    print(
        "  dz_m = z_2230 - z_2026"
    )

    print(
        "  delta_beta = beta_2230 - beta_2026"
    )

    print(
        "  vis_change = visibility_2026 -> visibility_2230"
    )

    print()

    print(
        "Camera assumption:"
    )

    print(
        "  The observer remains 1.8 m above the terrain "
        "in each period."
    )

finally:

    qgs.exitQgis()