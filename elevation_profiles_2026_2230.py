from pathlib import Path
import csv
import math

from qgis.core import (
    QgsApplication,
    QgsVectorLayer,
    QgsRasterLayer,
)

# =========================================================
# SETTINGS
# =========================================================

# Profile lines
LINE_PATH = Path(
    r"D:\Sali_IPRO\1.projects\3DVisualiyation\vector\SOL.gpkg"
)

# Current terrain model: year 2026
DEM_2026_PATH = Path(
    r"D:\37_K+S_Nienburger_Mulde\260603_Landschaftsbild\dgm\32650-tiff-dgm2.tif"
)

# Future terrain model: year 2230
DEM_2230_PATH = Path(
    r"D:\Sali_IPRO\1.projects\3DVisualiyation\raster\DEM_2230.tif"
)

# Output directory
OUTPUT_DIR = Path(
    r"D:\Sali_IPRO\1.projects\3DVisualiyation\output\elevation_profiles_2026_2230"
)

# Sampling interval along profile lines [m]
SAMPLE_INTERVAL = 2.0

# Line identification field
PNUMBER_FIELD = "PNumber"

# Names used in charts and console
DEM_2026_NAME = "DEM_2026_Current"
DEM_2230_NAME = "DEM_2230_Future"

# Plot colors
COLOR_2026 = "blue"
COLOR_2230 = "red"


# =========================================================
# INITIALIZE QGIS
# =========================================================

qgs = QgsApplication([], False)
qgs.initQgis()

try:

    # =====================================================
    # CREATE OUTPUT DIRECTORIES
    # =====================================================

    csv_dir = OUTPUT_DIR / "csv"
    plot_dir = OUTPUT_DIR / "plots"

    csv_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    plot_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    # =====================================================
    # CHECK INPUT FILES
    # =====================================================

    input_files = [
        (LINE_PATH, "Line layer"),
        (DEM_2026_PATH, "DEM 2026"),
        (DEM_2230_PATH, "DEM 2230"),
    ]

    for input_path, input_name in input_files:

        if not input_path.exists():

            raise FileNotFoundError(
                f"{input_name} does not exist:\n"
                f"{input_path}"
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
        DEM_2026_NAME
    )

    dem_2230 = QgsRasterLayer(
        str(DEM_2230_PATH),
        DEM_2230_NAME
    )

    # =====================================================
    # VALIDATE INPUT LAYERS
    # =====================================================

    if not lines.isValid():

        raise RuntimeError(
            f"Could not load line layer:\n"
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

    # =====================================================
    # CRS CHECK
    # =====================================================

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

    if not lines.crs().isValid():

        raise RuntimeError(
            "The CRS of the line layer is invalid."
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

    # Only print the unit. Do not evaluate it as True/False,
    # because meters can internally be represented by zero.
    print(
        "Line layer map units:",
        lines.crs().mapUnits()
    )

    print(
        "CRS check completed successfully."
    )

    # EPSG:25832 is a projected CRS with meter units.
    # Therefore SAMPLE_INTERVAL = 2.0 means 2 meters.

    # =====================================================
    # CHECK PNUMBER FIELD
    # =====================================================

    available_fields = (
        lines.fields().names()
    )

    if PNUMBER_FIELD not in available_fields:

        raise RuntimeError(
            f"Field '{PNUMBER_FIELD}' was not found.\n"
            f"Available fields: {available_fields}"
        )

    # =====================================================
    # LOAD MATPLOTLIB
    # =====================================================

    try:

        import matplotlib

        # Required for execution without a graphical interface
        matplotlib.use("Agg")

        import matplotlib.pyplot as plt

    except ImportError:

        raise RuntimeError(
            "matplotlib is not available in the "
            "QGIS Python environment."
        )

    # =====================================================
    # HELPER FUNCTION: SAMPLE RASTER
    # =====================================================

    def sample_raster(raster, point):
        """
        Samples Band 1 of a raster at the specified point.

        Returns None when the value is invalid, NoData,
        NaN or infinite.
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
    # HELPER FUNCTION: CREATE SAMPLE DISTANCES
    # =====================================================

    def create_sample_distances(length):
        """
        Creates sample distances:

        0, 2, 4, 6, ...

        The exact endpoint is added when necessary.
        """

        distances = []
        distance = 0.0

        while distance <= length:

            distances.append(
                distance
            )

            distance += SAMPLE_INTERVAL

        # Add exact endpoint if not already included
        if (
            not distances
            or abs(distances[-1] - length) > 1e-8
        ):

            distances.append(
                length
            )

        return distances

    # =====================================================
    # HELPER FUNCTION: SAFE FILE NAME
    # =====================================================

    def safe_filename(value):
        """
        Creates a safe filename from PNumber.
        """

        return (
            str(value)
            .strip()
            .replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")
        )

    # =====================================================
    # READ AND SORT LINE FEATURES
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
        f"Number of line features: {len(features)}"
    )

    print()

    # =====================================================
    # PROCESS EACH LINE
    # =====================================================

    processed_count = 0
    skipped_count = 0

    for feature in features:

        pnumber = feature[
            PNUMBER_FIELD
        ]

        geometry = feature.geometry()

        # -------------------------------------------------
        # CHECK PNUMBER
        # -------------------------------------------------

        if pnumber is None:

            print(
                "WARNING: A feature has no PNumber. "
                "Feature skipped."
            )

            skipped_count += 1
            continue

        # -------------------------------------------------
        # CHECK GEOMETRY
        # -------------------------------------------------

        if (
            geometry is None
            or geometry.isEmpty()
        ):

            print(
                f"WARNING: PNumber={pnumber}: "
                "empty geometry. Feature skipped."
            )

            skipped_count += 1
            continue

        # -------------------------------------------------
        # LINE LENGTH
        # -------------------------------------------------

        length = geometry.length()

        if length <= 0:

            print(
                f"WARNING: PNumber={pnumber}: "
                "line length is zero. Feature skipped."
            )

            skipped_count += 1
            continue

        print("=" * 60)

        print(
            f"Processing PNumber={pnumber} | "
            f"Length={length:.2f} m"
        )

        # -------------------------------------------------
        # CREATE SAMPLE DISTANCES
        # -------------------------------------------------

        distances = create_sample_distances(
            length
        )

        # -------------------------------------------------
        # SAMPLE BOTH DEMs
        # -------------------------------------------------

        rows = []

        for distance in distances:

            point_geometry = geometry.interpolate(
                distance
            )

            if point_geometry.isEmpty():

                print(
                    f"  WARNING: Could not create sample "
                    f"at distance {distance:.2f} m."
                )

                continue

            point = point_geometry.asPoint()

            # Current terrain elevation: 2026
            elevation_2026 = sample_raster(
                dem_2026,
                point
            )

            # Future terrain elevation: 2230
            elevation_2230 = sample_raster(
                dem_2230,
                point
            )

            # ---------------------------------------------
            # ELEVATION CHANGE
            #
            # Future minus current:
            #
            # Delta elevation = Z_2230 - Z_2026
            #
            # Negative result = subsidence
            # Positive result = elevation increase
            # ---------------------------------------------

            delta_elevation = None

            if (
                elevation_2026 is not None
                and elevation_2230 is not None
            ):

                delta_elevation = (
                    elevation_2230
                    - elevation_2026
                )

            rows.append(
                {
                    "pnumber": pnumber,
                    "distance_m": distance,
                    "elevation_2026_m": elevation_2026,
                    "elevation_2230_m": elevation_2230,
                    "delta_elevation_m": delta_elevation,
                }
            )

        if not rows:

            print(
                f"  WARNING: No sample points were created "
                f"for PNumber={pnumber}."
            )

            skipped_count += 1
            continue

        # =================================================
        # OUTPUT FILE IDENTIFIER
        # =================================================

        filename_id = safe_filename(
            pnumber
        )

        # =================================================
        # WRITE CSV
        # =================================================

        csv_path = (
            csv_dir
            / f"elevation_profile_{filename_id}.csv"
        )

        with csv_path.open(
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as file:

            writer = csv.writer(
                file,
                delimiter=","
            )

            writer.writerow(
                [
                    "PNumber",
                    "Distance_m",
                    "Elevation_DEM_2026_Current_m",
                    "Elevation_DEM_2230_Future_m",
                    "Delta_Elevation_2230_minus_2026_m",
                ]
            )

            for row in rows:

                writer.writerow(
                    [
                        row["pnumber"],

                        f'{row["distance_m"]:.2f}',

                        (
                            f'{row["elevation_2026_m"]:.3f}'
                            if row["elevation_2026_m"] is not None
                            else ""
                        ),

                        (
                            f'{row["elevation_2230_m"]:.3f}'
                            if row["elevation_2230_m"] is not None
                            else ""
                        ),

                        (
                            f'{row["delta_elevation_m"]:.3f}'
                            if row["delta_elevation_m"] is not None
                            else ""
                        ),
                    ]
                )

        # =================================================
        # PREPARE PLOT DATA
        # =================================================

        x_2026 = [
            row["distance_m"]
            for row in rows
            if row["elevation_2026_m"] is not None
        ]

        y_2026 = [
            row["elevation_2026_m"]
            for row in rows
            if row["elevation_2026_m"] is not None
        ]

        x_2230 = [
            row["distance_m"]
            for row in rows
            if row["elevation_2230_m"] is not None
        ]

        y_2230 = [
            row["elevation_2230_m"]
            for row in rows
            if row["elevation_2230_m"] is not None
        ]

        # =================================================
        # CREATE ELEVATION PROFILE PLOT
        # =================================================

        fig, ax = plt.subplots(
            figsize=(12, 6)
        )

        # Current terrain: 2026
        if x_2026:

            ax.plot(
                x_2026,
                y_2026,
                color=COLOR_2026,
                linewidth=1.5,
                label="DEM 2026 - Current terrain"
            )

        # Future terrain: 2230
        if x_2230:

            ax.plot(
                x_2230,
                y_2230,
                color=COLOR_2230,
                linewidth=1.5,
                label="DEM 2230 - Future terrain"
            )

        ax.set_title(
            f"Elevation Profile - PNumber {pnumber}",
            fontsize=14
        )

        ax.set_xlabel(
            "Distance along line [m]",
            fontsize=11
        )

        ax.set_ylabel(
            "Elevation [m]",
            fontsize=11
        )

        ax.set_xlim(
            0,
            length
        )

        ax.grid(
            True,
            alpha=0.30
        )

        if x_2026 or x_2230:

            ax.legend(
                loc="best"
            )

        fig.tight_layout()

        # =================================================
        # SAVE PLOT
        # =================================================

        plot_path = (
            plot_dir
            / f"elevation_profile_{filename_id}.png"
        )

        fig.savefig(
            plot_path,
            dpi=200,
            bbox_inches="tight"
        )

        plt.close(
            fig
        )

        # =================================================
        # CALCULATE STATISTICS
        # =================================================

        valid_2026_count = sum(
            row["elevation_2026_m"] is not None
            for row in rows
        )

        valid_2230_count = sum(
            row["elevation_2230_m"] is not None
            for row in rows
        )

        valid_delta_values = [
            row["delta_elevation_m"]
            for row in rows
            if row["delta_elevation_m"] is not None
        ]

        print(
            f"  Samples: {len(rows)}"
        )

        print(
            f"  DEM 2026 valid samples: "
            f"{valid_2026_count}"
        )

        print(
            f"  DEM 2230 valid samples: "
            f"{valid_2230_count}"
        )

        if valid_delta_values:

            minimum_delta = min(
                valid_delta_values
            )

            maximum_delta = max(
                valid_delta_values
            )

            mean_delta = (
                sum(valid_delta_values)
                / len(valid_delta_values)
            )

            print(
                "  Delta elevation (2230 - 2026):"
            )

            print(
                f"    Minimum: {minimum_delta:.3f} m"
            )

            print(
                f"    Maximum: {maximum_delta:.3f} m"
            )

            print(
                f"    Mean:    {mean_delta:.3f} m"
            )

        else:

            print(
                "  WARNING: No valid elevation differences "
                "could be calculated."
            )

        print(
            f"  CSV:  {csv_path}"
        )

        print(
            f"  Plot: {plot_path}"
        )

        print()

        processed_count += 1

    # =====================================================
    # FINISHED
    # =====================================================

    print("=" * 60)
    print("ELEVATION PROFILE PROCESSING COMPLETED")
    print("=" * 60)

    print(
        f"Processed lines: {processed_count}"
    )

    print(
        f"Skipped lines: {skipped_count}"
    )

    print(
        f"Output:\n{OUTPUT_DIR}"
    )

    print()

    print(
        "Elevation-change definition:"
    )

    print(
        "Delta Elevation = "
        "Elevation 2230 - Elevation 2026"
    )

    print(
        "Negative values indicate future subsidence."
    )

finally:

    qgs.exitQgis()