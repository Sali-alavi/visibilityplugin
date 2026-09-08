from pathlib import Path
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

# ---------------------------------------------------------
# CURRENT TERRAIN: YEAR 2026
# ---------------------------------------------------------

DEM_2026_PATH = Path(
    r"D:\37_K+S_Nienburger_Mulde\260603_Landschaftsbild\dgm\32650-tiff-dgm2.tif"
)

# ---------------------------------------------------------
# FUTURE TERRAIN: YEAR 2230
# ---------------------------------------------------------

DEM_2230_PATH = Path(
    r"D:\Sali_IPRO\1.projects\3DVisualiyation\raster\DEM_2230.tif"
)

# ---------------------------------------------------------
# OUTPUT
#
# A separate output directory is used so that previous
# results are not overwritten.
# ---------------------------------------------------------

OUTPUT_DIR = Path(
    r"D:\Sali_IPRO\1.projects\3DVisualiyation\output\elevation_profiles_fixed_y_2026_2230"
)

# Sampling interval along each profile line [m]
SAMPLE_INTERVAL = 2.0

# Line identification field
PNUMBER_FIELD = "PNumber"

# Names displayed in plots
DEM_2026_NAME = "DEM 2026 - Current terrain"
DEM_2230_NAME = "DEM 2230 - Future terrain"

# Plot colors
COLOR_2026 = "blue"
COLOR_2230 = "red"

# Margin around the global elevation range
Y_MARGIN_PERCENT = 0.02


# =========================================================
# INITIALIZE QGIS
# =========================================================

qgs = QgsApplication([], False)
qgs.initQgis()

try:

    # =====================================================
    # CREATE OUTPUT DIRECTORY
    # =====================================================

    OUTPUT_DIR.mkdir(
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

    for input_path, input_description in input_files:

        if not input_path.exists():

            raise FileNotFoundError(
                f"{input_description} was not found:\n"
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
        "DEM_2026"
    )

    dem_2230 = QgsRasterLayer(
        str(DEM_2230_PATH),
        "DEM_2230"
    )

    # =====================================================
    # VALIDATE LAYERS
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

    # =====================================================
    # CHECK CRS
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
            "The profile line layer, DEM 2026 and DEM 2230 "
            "must use the same CRS."
        )

    # Only display the unit. Do not test it as True/False,
    # because meter units can internally be represented by 0.
    print(
        "Line layer map units:",
        lines.crs().mapUnits()
    )

    print(
        "CRS check completed successfully."
    )

    # EPSG:25832 uses meters, so SAMPLE_INTERVAL = 2.0
    # represents a sampling interval of 2 meters.

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

        # Required when running without a graphical interface
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
        Samples Band 1 of the raster at the specified point.

        Returns None for:
        - unsuccessful samples
        - NoData values
        - nonnumeric values
        - NaN values
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
    # HELPER FUNCTION: CREATE SAMPLE DISTANCES
    # =====================================================

    def create_distances(length):
        """
        Creates sampling distances:

        0, 2, 4, 6, ...

        The exact endpoint is added when it does not coincide
        with the regular sampling interval.
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
    # HELPER FUNCTION: SAFE FILE NAME
    # =====================================================

    def safe_filename(value):
        """
        Converts a PNumber value into a safe filename.
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
    # READ AND SORT FEATURES
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
    # FIRST PASS
    #
    # Sample all elevation profiles and determine the
    # global elevation minimum and maximum.
    # =====================================================

    print("=" * 60)
    print("STEP 1: READING ALL ELEVATION PROFILES")
    print("=" * 60)

    # A list is used instead of a dictionary so that no
    # feature is overwritten if a PNumber occurs more than once.
    profile_data = []

    all_elevations = []

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
        # CHECK LENGTH
        # -------------------------------------------------

        length = geometry.length()

        if length <= 0:

            print(
                f"WARNING: PNumber={pnumber}: "
                "line length is zero. Feature skipped."
            )

            skipped_count += 1
            continue

        distances = create_distances(
            length
        )

        # -------------------------------------------------
        # SAMPLE PROFILE
        # -------------------------------------------------

        rows = []

        for distance in distances:

            point_geometry = geometry.interpolate(
                distance
            )

            if point_geometry.isEmpty():

                print(
                    f"WARNING: PNumber={pnumber}: "
                    f"sample at {distance:.2f} m "
                    "could not be created."
                )

                continue

            point = point_geometry.asPoint()

            # Current terrain elevation
            elevation_2026 = sample_raster(
                dem_2026,
                point
            )

            # Future terrain elevation
            elevation_2230 = sample_raster(
                dem_2230,
                point
            )

            rows.append(
                {
                    "distance_m": distance,
                    "elevation_2026_m": elevation_2026,
                    "elevation_2230_m": elevation_2230,
                }
            )

            # Add all valid elevations to the global list.
            # The global Y-axis therefore covers both years
            # and all profile lines.
            if elevation_2026 is not None:

                all_elevations.append(
                    elevation_2026
                )

            if elevation_2230 is not None:

                all_elevations.append(
                    elevation_2230
                )

        if not rows:

            print(
                f"WARNING: PNumber={pnumber}: "
                "no sample points were created. "
                "Feature skipped."
            )

            skipped_count += 1
            continue

        valid_2026_count = sum(
            row["elevation_2026_m"] is not None
            for row in rows
        )

        valid_2230_count = sum(
            row["elevation_2230_m"] is not None
            for row in rows
        )

        profile_data.append(
            {
                "pnumber": pnumber,
                "length_m": length,
                "rows": rows,
            }
        )

        print(
            f"PNumber={pnumber} | "
            f"Length={length:.2f} m | "
            f"Samples={len(rows)} | "
            f"2026 valid={valid_2026_count} | "
            f"2230 valid={valid_2230_count}"
        )

    # =====================================================
    # CALCULATE GLOBAL ELEVATION RANGE
    # =====================================================

    if not profile_data:

        raise RuntimeError(
            "No valid profile lines could be processed."
        )

    if not all_elevations:

        raise RuntimeError(
            "No valid elevation values were found in either DEM."
        )

    global_min = min(
        all_elevations
    )

    global_max = max(
        all_elevations
    )

    elevation_range = (
        global_max
        - global_min
    )

    print()
    print("=" * 60)
    print("GLOBAL ELEVATION RANGE")
    print("=" * 60)

    print(
        f"Minimum elevation: {global_min:.3f} m"
    )

    print(
        f"Maximum elevation: {global_max:.3f} m"
    )

    print(
        f"Elevation range: {elevation_range:.3f} m"
    )

    # =====================================================
    # CALCULATE FIXED Y-AXIS LIMITS
    # =====================================================

    if elevation_range > 0:

        margin = (
            elevation_range
            * Y_MARGIN_PERCENT
        )

    else:

        # Fallback when all sampled elevations are equal
        margin = 1.0

    fixed_y_min = (
        global_min
        - margin
    )

    fixed_y_max = (
        global_max
        + margin
    )

    print(
        f"Display margin: {margin:.3f} m"
    )

    print(
        f"Fixed Y-axis minimum: {fixed_y_min:.3f} m"
    )

    print(
        f"Fixed Y-axis maximum: {fixed_y_max:.3f} m"
    )

    print("=" * 60)
    print()

    # =====================================================
    # SECOND PASS
    #
    # Create all plots using exactly the same Y-axis limits.
    # =====================================================

    print("=" * 60)
    print("STEP 2: CREATING FIXED-SCALE PROFILES")
    print("=" * 60)
    print()

    plot_count = 0

    for profile in profile_data:

        pnumber = profile[
            "pnumber"
        ]

        length = profile[
            "length_m"
        ]

        rows = profile[
            "rows"
        ]

        # -------------------------------------------------
        # CURRENT TERRAIN: 2026
        # -------------------------------------------------

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

        # -------------------------------------------------
        # FUTURE TERRAIN: 2230
        # -------------------------------------------------

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

        # -------------------------------------------------
        # CREATE FIGURE
        # -------------------------------------------------

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
                label=DEM_2026_NAME
            )

        # Future terrain: 2230
        if x_2230:

            ax.plot(
                x_2230,
                y_2230,
                color=COLOR_2230,
                linewidth=1.5,
                label=DEM_2230_NAME
            )

        # -------------------------------------------------
        # FIXED Y-AXIS
        #
        # Exactly the same limits are used for every plot.
        # -------------------------------------------------

        ax.set_ylim(
            fixed_y_min,
            fixed_y_max
        )

        # -------------------------------------------------
        # INDIVIDUAL X-AXIS
        #
        # The X-axis corresponds to the length of each line.
        # -------------------------------------------------

        ax.set_xlim(
            0,
            length
        )

        # -------------------------------------------------
        # TITLE AND LABELS
        # -------------------------------------------------

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

        # -------------------------------------------------
        # GRID AND LEGEND
        # -------------------------------------------------

        ax.grid(
            True,
            alpha=0.30
        )

        if x_2026 or x_2230:

            ax.legend(
                loc="best"
            )

        # -------------------------------------------------
        # SAVE PLOT
        # -------------------------------------------------

        fig.tight_layout()

        filename_id = safe_filename(
            pnumber
        )

        plot_path = (
            OUTPUT_DIR
            / f"elevation_profile_{filename_id}_fixed_y.png"
        )

        fig.savefig(
            plot_path,
            dpi=200,
            bbox_inches="tight"
        )

        plt.close(
            fig
        )

        plot_count += 1

        print(
            f"PNumber={pnumber} | "
            f"Plot created: {plot_path.name}"
        )

    # =====================================================
    # FINISHED
    # =====================================================

    print()
    print("=" * 60)
    print("FIXED Y-AXIS PROFILE PROCESSING COMPLETED")
    print("=" * 60)

    print(
        f"Plots created: {plot_count}"
    )

    print(
        f"Skipped features: {skipped_count}"
    )

    print(
        f"Global minimum: {global_min:.3f} m"
    )

    print(
        f"Global maximum: {global_max:.3f} m"
    )

    print(
        f"Fixed Y-axis: "
        f"{fixed_y_min:.3f} to "
        f"{fixed_y_max:.3f} m"
    )

    print(
        "Blue line: DEM 2026 - Current terrain"
    )

    print(
        "Red line: DEM 2230 - Future terrain"
    )

    print(
        f"Output directory:\n{OUTPUT_DIR}"
    )

finally:

    qgs.exitQgis()