# -*- coding: utf-8 -*-

"""
Main plugin logic for Surface Visibility and Viewing-Angle Change Analyzer.
"""

from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QAction, QMessageBox

from qgis.core import (
    QgsColorRampShader,
    QgsCoordinateTransform,
    QgsCsException,
    QgsGeometry,
    QgsMapLayerType,
    QgsPalettedRasterRenderer,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from qgis.gui import QgsVertexMarker

from .dialog import TerrainVisibilityDialog
from .observer_map_tool import ObserverMapTool

from .core.profile_generator import (
    ProfileGenerationError,
    generate_directional_profiles,
)

from .core.report_generator import (
    ReportGenerationError,
    generate_visibility_report,
)

from .core.surface_analysis import (
    SurfaceAnalysisError,
    generate_surface_outputs,
)

from .core.viewshed_engine import (
    ViewshedEngineError,
    create_viewshed,
    create_visibility_change,
)


class TerrainVisibilityChangePlugin:
    """
    Main QGIS Plugin class.
    """

    MENU_NAME = "&Surface Visibility"

    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()

        self.action = None
        self.dialog = None

        self.observer_map_tool = None
        self.previous_map_tool = None

        self.observer_point_map_crs = None
        self.observer_point_dem_crs = None
        self.observer_marker = None

    def initGui(self):
        """
        Creates plugin menu and toolbar entry.
        """

        self.action = QAction(
            "Surface Visibility and Viewing-Angle Analyzer",
            self.iface.mainWindow(),
        )

        self.action.setToolTip(
            "Compare DOM-based visibility and vertical viewing angles "
            "between two scenarios."
        )

        self.action.triggered.connect(
            self.run
        )

        self.iface.addPluginToMenu(
            self.MENU_NAME,
            self.action,
        )

        self.iface.addToolBarIcon(
            self.action
        )

    def unload(self):
        """
        Removes plugin interface elements.
        """

        if self.action is not None:
            self.iface.removePluginMenu(
                self.MENU_NAME,
                self.action,
            )

            self.iface.removeToolBarIcon(
                self.action
            )

        self._remove_observer_marker()

    def run(self):
        """
        Opens the plugin dialog.
        """

        if self.dialog is None:
            self.dialog = TerrainVisibilityDialog(
                self.iface.mainWindow()
            )

            self.dialog.refresh_layers_button.clicked.connect(
                self.refresh_layers
            )

            self.dialog.select_observer_button.clicked.connect(
                self.activate_observer_selection
            )

            self.dialog.run_button.clicked.connect(
                self.run_visibility_analysis
            )

        self.refresh_layers()

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def refresh_layers(self):
        """
        Refreshes DOM raster and analysis-boundary Polygon layers.
        """

        if self.dialog is None:
            return

        selected_2026_id = self.dialog.selected_dem_2026_id()
        selected_2230_id = self.dialog.selected_dem_2230_id()
        selected_boundary_id = self.dialog.selected_boundary_id()

        raster_layers = self._get_raster_layers()
        polygon_layers = self._get_polygon_layers()

        for combo in (
            self.dialog.dem_2026_combo,
            self.dialog.dem_2230_combo,
            self.dialog.boundary_combo,
        ):
            combo.blockSignals(True)
            combo.clear()

        self.dialog.dem_2026_combo.addItem(
            "-- Select DOM raster layer --",
            None,
        )

        self.dialog.dem_2230_combo.addItem(
            "-- Select DOM raster layer --",
            None,
        )

        self.dialog.boundary_combo.addItem(
            "-- Select polygon boundary layer --",
            None,
        )

        for layer in raster_layers:
            label = (
                f"{layer.name()} "
                f"({layer.crs().authid()})"
            )

            self.dialog.dem_2026_combo.addItem(
                label,
                layer.id(),
            )

            self.dialog.dem_2230_combo.addItem(
                label,
                layer.id(),
            )

        for layer in polygon_layers:
            label = (
                f"{layer.name()} "
                f"({layer.crs().authid()})"
            )

            self.dialog.boundary_combo.addItem(
                label,
                layer.id(),
            )

        self._restore_combo_selection(
            self.dialog.dem_2026_combo,
            selected_2026_id,
        )

        self._restore_combo_selection(
            self.dialog.dem_2230_combo,
            selected_2230_id,
        )

        self._restore_combo_selection(
            self.dialog.boundary_combo,
            selected_boundary_id,
        )

        for combo in (
            self.dialog.dem_2026_combo,
            self.dialog.dem_2230_combo,
            self.dialog.boundary_combo,
        ):
            combo.blockSignals(False)

        self.dialog.set_status(
            f"{len(raster_layers)} raster layer(s) and "
            f"{len(polygon_layers)} polygon layer(s) found. "
            "Select DOM 2026, DOM 2230 and the analysis boundary."
        )

    def activate_observer_selection(self):
        """
        Activates map click tool for observer selection.
        """

        if self.dialog is None:
            return

        dom_2026 = self._selected_raster_layer(
            self.dialog.selected_dem_2026_id()
        )

        if dom_2026 is None:
            self.dialog.set_status(
                "First select the existing surface model / DOM 2026.",
                is_error=True,
            )
            return

        self.previous_map_tool = self.canvas.mapTool()

        self.observer_map_tool = ObserverMapTool(
            self.canvas,
            self.handle_observer_click,
        )

        self.canvas.setMapTool(
            self.observer_map_tool
        )

        self.dialog.set_status(
            "Click once on the map to select the observer location."
        )

    def handle_observer_click(self, map_point):
        """
        Converts selected map coordinate to DOM CRS.
        """

        if self.dialog is None:
            return

        dom_2026 = self._selected_raster_layer(
            self.dialog.selected_dem_2026_id()
        )

        if dom_2026 is None:
            return

        map_crs = self.canvas.mapSettings().destinationCrs()
        dom_crs = dom_2026.crs()

        try:
            coordinate_transform = QgsCoordinateTransform(
                map_crs,
                dom_crs,
                QgsProject.instance(),
            )

            dom_point = coordinate_transform.transform(
                map_point
            )

        except QgsCsException as error:
            self.dialog.set_status(
                "Could not transform observer coordinates "
                f"to DOM CRS: {error}",
                is_error=True,
            )
            return

        self.observer_point_map_crs = QgsPointXY(
            map_point
        )

        self.observer_point_dem_crs = QgsPointXY(
            dom_point
        )

        self._show_observer_marker(
            self.observer_point_map_crs
        )

        self.dialog.set_observer_coordinates(
            self.observer_point_dem_crs.x(),
            self.observer_point_dem_crs.y(),
            dom_crs.authid(),
        )

        self.dialog.set_status(
            "Observer location selected. Select an output folder "
            "and run the analysis."
        )

        if self.previous_map_tool is not None:
            self.canvas.setMapTool(
                self.previous_map_tool
            )

    def run_visibility_analysis(self):
        """
        Executes viewshed, surface angle, profile and report generation.
        """

        validation = self._validate_inputs()

        if validation is None:
            return

        (
            dom_2026,
            dom_2230,
            boundary_layer,
            boundary_geometry,
            output_folder,
        ) = validation

        output_folder = Path(output_folder)

        output_viewshed_2026 = (
            output_folder / "viewshed_2026.tif"
        )

        output_viewshed_2230 = (
            output_folder / "viewshed_2230.tif"
        )

        output_visibility_change = (
            output_folder
            / "visibility_change_2026_to_2230.tif"
        )

        output_statistics_csv = (
            output_folder
            / "visibility_change_statistics.csv"
        )

        output_pdf = (
            output_folder
            / "visibility_change_report.pdf"
        )

        eye_height = self.dialog.eye_height()

        self.dialog.set_processing_state(
            True
        )

        try:
            self._update_gui_status(
                "Creating Viewshed for DOM 2026. Please wait..."
            )

            create_viewshed(
                dem_path=dom_2026.source(),
                output_path=output_viewshed_2026,
                observer_x=self.observer_point_dem_crs.x(),
                observer_y=self.observer_point_dem_crs.y(),
                observer_height=eye_height,
                target_height=0.0,
            )

            self._update_gui_status(
                "Creating Viewshed for DOM 2230. Please wait..."
            )

            create_viewshed(
                dem_path=dom_2230.source(),
                output_path=output_viewshed_2230,
                observer_x=self.observer_point_dem_crs.x(),
                observer_y=self.observer_point_dem_crs.y(),
                observer_height=eye_height,
                target_height=0.0,
            )

            self._update_gui_status(
                "Creating viewing-angle rasters and masking "
                "outputs to the analysis boundary..."
            )

            surface_outputs = generate_surface_outputs(
                dom_2026_path=dom_2026.source(),
                dom_2230_path=dom_2230.source(),
                viewshed_2026_path=output_viewshed_2026,
                viewshed_2230_path=output_viewshed_2230,
                boundary_wkt=boundary_geometry.asWkt(),
                observer_x=self.observer_point_dem_crs.x(),
                observer_y=self.observer_point_dem_crs.y(),
                eye_height=eye_height,
                output_folder=output_folder,
            )

            self._update_gui_status(
                "Creating visibility-change raster..."
            )

            create_visibility_change(
                viewshed_2026_path=output_viewshed_2026,
                viewshed_2230_path=output_viewshed_2230,
                output_path=output_visibility_change,
            )

            self._update_gui_status(
                "Creating eight directional profiles and CSV files..."
            )

            profile_outputs = generate_directional_profiles(
                dom_2026_path=dom_2026.source(),
                dom_2230_path=dom_2230.source(),
                viewshed_2026_path=output_viewshed_2026,
                viewshed_2230_path=output_viewshed_2230,
                viewing_angle_2026_path=surface_outputs[
                    "angle_2026"
                ],
                viewing_angle_2230_path=surface_outputs[
                    "angle_2230"
                ],
                viewing_angle_difference_path=surface_outputs[
                    "angle_difference"
                ],
                boundary_wkt=boundary_geometry.asWkt(),
                observer_x=self.observer_point_dem_crs.x(),
                observer_y=self.observer_point_dem_crs.y(),
                output_folder=output_folder,
                sampling_interval_m=1.0,
            )

            self._update_gui_status(
                "Creating statistics, CSV and PDF report..."
            )

            analysis_parameters = {
                "report_datetime": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "dem_2026_name": (
                    f"{dom_2026.name()}\n"
                    f"{dom_2026.source()}"
                ),
                "dem_2230_name": (
                    f"{dom_2230.name()}\n"
                    f"{dom_2230.source()}"
                ),
                "crs": dom_2026.crs().authid(),
                "boundary_name": boundary_layer.name(),
                "observer_coordinates": (
                    f"X: {self.observer_point_dem_crs.x():.3f} | "
                    f"Y: {self.observer_point_dem_crs.y():.3f} | "
                    f"CRS: {dom_2026.crs().authid()}"
                ),
                "eye_height": f"{eye_height:.2f} m",
                "target_height": "0.00 m",
                "sampling_interval_m": (
                    f"{profile_outputs['sampling_interval_m']:.2f} m"
                ),
                "line_of_sight_model": (
                    "Earth curvature and standard atmospheric "
                    "refraction enabled "
                    "(GDAL curvature coefficient: 0.85714)"
                ),
            }

            logo_path = (
                Path(__file__).resolve().parent
                / "styles"
                / "iproconsult_logo.png.jpg"
            )

            statistics = generate_visibility_report(
                change_raster_path=output_visibility_change,
                csv_path=output_statistics_csv,
                pdf_path=output_pdf,
                analysis_parameters=analysis_parameters,
                logo_path=logo_path,
                profile_outputs=profile_outputs,
                viewing_angle_difference_path=surface_outputs[
                    "angle_difference"
                ],
            )

            self._update_gui_status(
                "Adding result rasters to QGIS..."
            )

            layer_viewshed_2026 = self._add_raster_result(
                output_viewshed_2026,
                "Viewshed 2026",
            )

            layer_viewshed_2230 = self._add_raster_result(
                output_viewshed_2230,
                "Viewshed 2230",
            )

            layer_visibility_change = self._add_raster_result(
                output_visibility_change,
                "Visibility Change 2026 to 2230",
            )

            layer_angle_2026 = self._add_raster_result(
                surface_outputs["angle_2026"],
                "Viewing Angle 2026",
            )

            layer_angle_2230 = self._add_raster_result(
                surface_outputs["angle_2230"],
                "Viewing Angle 2230",
            )

            layer_angle_difference = self._add_raster_result(
                surface_outputs["angle_difference"],
                "Viewing Angle Difference 2230 minus 2026",
            )

            layer_not_visible_2026 = self._add_raster_result(
                surface_outputs["not_visible_2026"],
                "Not Visible Overlay 2026",
            )

            layer_not_visible_2230 = self._add_raster_result(
                surface_outputs["not_visible_2230"],
                "Not Visible Overlay 2230",
            )

            if (
                layer_viewshed_2026 is None
                or layer_viewshed_2230 is None
                or layer_visibility_change is None
                or layer_angle_2026 is None
                or layer_angle_2230 is None
                or layer_angle_difference is None
                or layer_not_visible_2026 is None
                or layer_not_visible_2230 is None
            ):
                raise RuntimeError(
                    "One or more result rasters could not be "
                    "loaded into QGIS."
                )

            self._apply_change_symbology(
                layer_visibility_change
            )

            self._apply_angle_symbology(
                layer_angle_2026
            )

            self._apply_angle_symbology(
                layer_angle_2230
            )

            self._apply_angle_difference_symbology(
                layer_angle_difference
            )

            self._apply_not_visible_symbology(
                layer_not_visible_2026
            )

            self._apply_not_visible_symbology(
                layer_not_visible_2230
            )

            loss_area = self._class_area_ha(
                statistics,
                3,
            )

            gain_area = self._class_area_ha(
                statistics,
                4,
            )

            message = (
                "Surface visibility and viewing-angle analysis "
                "completed successfully.\n\n"
                f"Valid analysis area: "
                f"{statistics['valid_area_ha']:.4f} ha\n"
                f"Visibility loss: "
                f"{loss_area:.4f} ha\n"
                f"Visibility gain: "
                f"{gain_area:.4f} ha\n\n"
                f"PDF report:\n{output_pdf}\n\n"
                f"Visibility statistics CSV:\n"
                f"{output_statistics_csv}\n\n"
                f"Profile summary CSV:\n"
                f"{profile_outputs['summary_path']}\n\n"
                f"Profile folder:\n"
                f"{profile_outputs['profile_folder']}"
            )

            self.dialog.set_status(
                message
            )

            QMessageBox.information(
                self.iface.mainWindow(),
                "Surface visibility analysis completed",
                message,
            )

        except (
            ViewshedEngineError,
            SurfaceAnalysisError,
            ProfileGenerationError,
            ReportGenerationError,
        ) as error:
            self._show_processing_error(
                str(error)
            )

        except Exception as error:
            self._show_processing_error(
                f"{type(error).__name__}: {error}"
            )

        finally:
            self.dialog.set_processing_state(
                False
            )

    def _validate_inputs(self):
        """
        Validates DOM layers, Polygon boundary, observer and output folder.

        Returns:
            (
                dom_2026,
                dom_2230,
                boundary_layer,
                boundary_geometry,
                output_folder,
            )
        """

        dom_2026 = self._selected_raster_layer(
            self.dialog.selected_dem_2026_id()
        )

        dom_2230 = self._selected_raster_layer(
            self.dialog.selected_dem_2230_id()
        )

        boundary_layer = self._selected_polygon_layer(
            self.dialog.selected_boundary_id()
        )

        errors = []

        if dom_2026 is None:
            errors.append(
                "Select the existing surface model / DOM 2026."
            )

        if dom_2230 is None:
            errors.append(
                "Select the future surface model / DOM 2230."
            )

        if boundary_layer is None:
            errors.append(
                "Select an analysis boundary polygon layer."
            )

        if (
            dom_2026 is not None
            and dom_2230 is not None
            and dom_2026.id() == dom_2230.id()
        ):
            errors.append(
                "DOM 2026 and DOM 2230 must be different layers."
            )

        if (
            dom_2026 is not None
            and dom_2230 is not None
            and dom_2026.crs() != dom_2230.crs()
        ):
            errors.append(
                "Both DOM layers must use the same CRS."
            )

        if (
            dom_2026 is not None
            and dom_2026.crs().isGeographic()
        ):
            errors.append(
                "Viewshed analysis requires a projected CRS "
                "with metre units."
            )

        if self.observer_point_dem_crs is None:
            errors.append(
                "Select an observer point on the map."
            )

        output_folder = self.dialog.output_folder()

        if not output_folder:
            errors.append(
                "Select an output folder."
            )

        elif not Path(output_folder).is_dir():
            errors.append(
                "The selected output folder does not exist."
            )

        boundary_geometry = None

        if (
            boundary_layer is not None
            and dom_2026 is not None
        ):
            try:
                boundary_geometry = (
                    self._combined_boundary_geometry(
                        boundary_layer,
                        dom_2026.crs(),
                    )
                )

            except Exception as error:
                errors.append(
                    "Could not prepare analysis-boundary geometry: "
                    f"{error}"
                )

        if (
            boundary_geometry is not None
            and self.observer_point_dem_crs is not None
        ):
            observer_geometry = QgsGeometry.fromPointXY(
                self.observer_point_dem_crs
            )

            if not boundary_geometry.contains(
                observer_geometry
            ):
                errors.append(
                    "Observer point must be inside the "
                    "analysis boundary polygon."
                )

        if (
            dom_2026 is not None
            and self.observer_point_dem_crs is not None
            and not dom_2026.extent().contains(
                self.observer_point_dem_crs
            )
        ):
            errors.append(
                "Observer point is outside DOM 2026 extent."
            )

        if (
            dom_2230 is not None
            and self.observer_point_dem_crs is not None
            and not dom_2230.extent().contains(
                self.observer_point_dem_crs
            )
        ):
            errors.append(
                "Observer point is outside DOM 2230 extent."
            )

        if errors:
            message = (
                "Input validation failed:\n\n- "
                + "\n- ".join(errors)
            )

            self.dialog.set_status(
                message,
                is_error=True,
            )

            QMessageBox.warning(
                self.iface.mainWindow(),
                "Surface Visibility Analyzer",
                message,
            )

            return None

        return (
            dom_2026,
            dom_2230,
            boundary_layer,
            boundary_geometry,
            output_folder,
        )

    def _combined_boundary_geometry(
        self,
        boundary_layer,
        target_crs,
    ):
        """
        Combines all Polygon features and transforms geometry to DOM CRS.
        """

        geometries = []

        for feature in boundary_layer.getFeatures():
            geometry = feature.geometry()

            if (
                geometry is not None
                and not geometry.isEmpty()
            ):
                geometries.append(
                    QgsGeometry(geometry)
                )

        if not geometries:
            raise RuntimeError(
                "Boundary layer contains no valid polygon geometry."
            )

        combined_geometry = QgsGeometry.unaryUnion(
            geometries
        )

        if boundary_layer.crs() != target_crs:
            coordinate_transform = QgsCoordinateTransform(
                boundary_layer.crs(),
                target_crs,
                QgsProject.instance(),
            )

            result = combined_geometry.transform(
                coordinate_transform
            )

            if result != 0:
                raise RuntimeError(
                    "Boundary geometry coordinate transformation failed."
                )

        return combined_geometry

    def _apply_change_symbology(self, raster_layer):
        """
        Applies categorical visibility-change symbology.
        """

        if raster_layer is None:
            return

        provider = raster_layer.dataProvider()

        if provider is None:
            return

        classes = [
            QgsPalettedRasterRenderer.Class(
                1,
                QColor("#666666"),
                "Not visible in both scenarios",
            ),
            QgsPalettedRasterRenderer.Class(
                2,
                QColor("#4C9A2A"),
                "Visible in both scenarios",
            ),
            QgsPalettedRasterRenderer.Class(
                3,
                QColor("#D73027"),
                "Visibility loss",
            ),
            QgsPalettedRasterRenderer.Class(
                4,
                QColor("#2C7FB8"),
                "Visibility gain",
            ),
            QgsPalettedRasterRenderer.Class(
                255,
                QColor(0, 0, 0, 0),
                "NoData / outside boundary",
            ),
        ]

        raster_layer.setRenderer(
            QgsPalettedRasterRenderer(
                provider,
                1,
                classes,
            )
        )

        raster_layer.triggerRepaint()

    def _apply_not_visible_symbology(self, raster_layer):
        """
        Applies transparent dark-grey Not Visible overlay.
        """

        if raster_layer is None:
            return

        provider = raster_layer.dataProvider()

        if provider is None:
            return

        classes = [
            QgsPalettedRasterRenderer.Class(
                1,
                QColor(70, 70, 70, 145),
                "Not visible",
            ),
            QgsPalettedRasterRenderer.Class(
                255,
                QColor(0, 0, 0, 0),
                "Visible / NoData",
            ),
        ]

        raster_layer.setRenderer(
            QgsPalettedRasterRenderer(
                provider,
                1,
                classes,
            )
        )

        raster_layer.triggerRepaint()

    def _apply_angle_symbology(self, raster_layer):
        """
        Applies colour classes to beta angle raster.
        """

        self._apply_pseudocolor_symbology(
            raster_layer,
            [
                (
                    -1.00,
                    QColor("#08306B"),
                    "≤ -1.00° | Clearly below eye level",
                ),
                (
                    -0.25,
                    QColor("#2171B5"),
                    "-1.00° to -0.25° | Below horizon",
                ),
                (
                    -0.10,
                    QColor("#9ECAE1"),
                    "-0.25° to -0.10° | Slightly below horizon",
                ),
                (
                    0.10,
                    QColor("#F2F2F2"),
                    "-0.10° to +0.10° | Approximately eye level",
                ),
                (
                    0.25,
                    QColor("#FEE391"),
                    "+0.10° to +0.25° | Slightly above horizon",
                ),
                (
                    0.50,
                    QColor("#FEC44F"),
                    "+0.25° to +0.50° | Above horizon",
                ),
                (
                    1.00,
                    QColor("#EC7014"),
                    "+0.50° to +1.00° | Clearly above horizon",
                ),
                (
                    90.00,
                    QColor("#B30000"),
                    "> +1.00° | Prominent surface or obstacle",
                ),
            ],
        )

    def _apply_angle_difference_symbology(self, raster_layer):
        """
        Applies diverging colour classes to Delta beta raster.
        """

        self._apply_pseudocolor_symbology(
            raster_layer,
            [
                (
                    -1.00,
                    QColor("#08306B"),
                    "≤ -1.00° | Strong decrease in 2230",
                ),
                (
                    -0.25,
                    QColor("#2171B5"),
                    "-1.00° to -0.25° | Decrease in 2230",
                ),
                (
                    -0.10,
                    QColor("#9ECAE1"),
                    "-0.25° to -0.10° | Slight decrease in 2230",
                ),
                (
                    0.10,
                    QColor("#F2F2F2"),
                    "-0.10° to +0.10° | No material change",
                ),
                (
                    0.25,
                    QColor("#FEE391"),
                    "+0.10° to +0.25° | Slight increase in 2230",
                ),
                (
                    0.50,
                    QColor("#FEC44F"),
                    "+0.25° to +0.50° | Increase in 2230",
                ),
                (
                    1.00,
                    QColor("#EC7014"),
                    "+0.50° to +1.00° | Strong increase in 2230",
                ),
                (
                    90.00,
                    QColor("#B30000"),
                    "> +1.00° | Very strong increase in 2230",
                ),
            ],
        )

    @staticmethod
    def _apply_pseudocolor_symbology(
        raster_layer,
        color_items,
    ):
        """
        Applies discrete pseudo-colour symbology.
        """

        if raster_layer is None:
            return

        provider = raster_layer.dataProvider()

        if provider is None:
            return

        shader = QgsRasterShader()
        color_shader = QgsColorRampShader()

        color_shader.setColorRampType(
            QgsColorRampShader.Discrete
        )

        ramp_items = []

        for value, color, label in color_items:
            ramp_items.append(
                QgsColorRampShader.ColorRampItem(
                    float(value),
                    color,
                    str(label),
                )
            )

        color_shader.setColorRampItemList(
            ramp_items
        )

        shader.setRasterShaderFunction(
            color_shader
        )

        raster_layer.setRenderer(
            QgsSingleBandPseudoColorRenderer(
                provider,
                1,
                shader,
            )
        )

        raster_layer.triggerRepaint()

    @staticmethod
    def _class_area_ha(statistics, class_value):
        """
        Returns area in hectare for one visibility-change class.
        """

        for item in statistics["classes"]:
            if item["value"] == class_value:
                return item["area_ha"]

        return 0.0

    def _show_processing_error(self, details):
        """
        Shows processing error in dialog and message box.
        """

        message = (
            "Surface visibility analysis failed:\n\n"
            f"{details}"
        )

        self.dialog.set_status(
            message,
            is_error=True,
        )

        QMessageBox.critical(
            self.iface.mainWindow(),
            "Surface visibility analysis failed",
            message,
        )

    def _update_gui_status(self, message):
        """
        Updates status box in dialog.
        """

        if self.dialog is not None:
            self.dialog.set_status(
                message
            )

    def _add_raster_result(
        self,
        raster_path,
        layer_name,
    ):
        """
        Adds output raster to current QGIS project.
        """

        result_layer = QgsRasterLayer(
            str(raster_path),
            layer_name,
        )

        if not result_layer.isValid():
            return None

        QgsProject.instance().addMapLayer(
            result_layer
        )

        return result_layer

    @staticmethod
    def _get_raster_layers():
        """
        Returns valid raster layers from active QGIS project.
        """

        raster_layers = []

        for layer in QgsProject.instance().mapLayers().values():
            if (
                layer.type() == QgsMapLayerType.RasterLayer
                and isinstance(layer, QgsRasterLayer)
                and layer.isValid()
            ):
                raster_layers.append(layer)

        return sorted(
            raster_layers,
            key=lambda layer: layer.name().lower(),
        )

    @staticmethod
    def _get_polygon_layers():
        """
        Returns valid Polygon/MultiPolygon vector layers.
        """

        polygon_layers = []

        for layer in QgsProject.instance().mapLayers().values():
            if (
                layer.type() == QgsMapLayerType.VectorLayer
                and isinstance(layer, QgsVectorLayer)
                and layer.isValid()
                and layer.geometryType()
                == QgsWkbTypes.PolygonGeometry
            ):
                polygon_layers.append(layer)

        return sorted(
            polygon_layers,
            key=lambda layer: layer.name().lower(),
        )

    @staticmethod
    def _restore_combo_selection(combo, layer_id):
        """
        Restores previously selected layer in QComboBox.
        """

        if layer_id is None:
            return

        index = combo.findData(
            layer_id
        )

        if index >= 0:
            combo.setCurrentIndex(
                index
            )

    @staticmethod
    def _selected_raster_layer(layer_id):
        """
        Returns valid QgsRasterLayer from QGIS layer ID.
        """

        if not layer_id:
            return None

        layer = QgsProject.instance().mapLayer(
            layer_id
        )

        if (
            layer is None
            or not isinstance(layer, QgsRasterLayer)
            or not layer.isValid()
        ):
            return None

        return layer

    @staticmethod
    def _selected_polygon_layer(layer_id):
        """
        Returns valid Polygon QgsVectorLayer from QGIS layer ID.
        """

        if not layer_id:
            return None

        layer = QgsProject.instance().mapLayer(
            layer_id
        )

        if (
            layer is None
            or not isinstance(layer, QgsVectorLayer)
            or not layer.isValid()
            or layer.geometryType()
            != QgsWkbTypes.PolygonGeometry
        ):
            return None

        return layer

    def _show_observer_marker(self, point):
        """
        Draws temporary red observer cross on QGIS canvas.
        """

        self._remove_observer_marker()

        self.observer_marker = QgsVertexMarker(
            self.canvas
        )

        self.observer_marker.setCenter(
            point
        )

        self.observer_marker.setColor(
            QColor(220, 30, 30)
        )

        self.observer_marker.setIconType(
            QgsVertexMarker.ICON_CROSS
        )

        self.observer_marker.setIconSize(
            14
        )

        self.observer_marker.setPenWidth(
            3
        )

    def _remove_observer_marker(self):
        """
        Removes temporary observer marker.
        """

        if self.observer_marker is not None:
            self.canvas.scene().removeItem(
                self.observer_marker
            )

            self.observer_marker = None