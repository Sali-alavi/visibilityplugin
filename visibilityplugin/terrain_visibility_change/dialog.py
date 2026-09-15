# -*- coding: utf-8 -*-

"""
User interface for the Surface Visibility and Viewing-Angle Change Analyzer.
"""

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class TerrainVisibilityDialog(QDialog):
    """
    Main dialog for Surface Visibility and Viewing-Angle Change Analyzer.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle(
            "Surface Visibility and Viewing-Angle Change Analyzer"
        )

        self.setMinimumWidth(620)
        self.setModal(False)

        self._create_widgets()
        self._create_layout()
        self._connect_signals()

    def _create_widgets(self):
        self.dem_2026_combo = QComboBox()
        self.dem_2026_combo.setToolTip(
            "Select the existing surface model / DOM for 2026."
        )

        self.dem_2230_combo = QComboBox()
        self.dem_2230_combo.setToolTip(
            "Select the future surface model / DOM for 2230."
        )

        self.boundary_combo = QComboBox()
        self.boundary_combo.setToolTip(
            "Select the polygon layer defining the analysis boundary."
        )

        self.refresh_layers_button = QPushButton(
            "Refresh raster and polygon layers"
        )

        self.select_observer_button = QPushButton(
            "Select observer on map"
        )

        self.observer_coordinates_label = QLabel(
            "No observer point selected."
        )
        self.observer_coordinates_label.setWordWrap(True)

        self.eye_height_spin = QDoubleSpinBox()
        self.eye_height_spin.setDecimals(2)
        self.eye_height_spin.setMinimum(0.10)
        self.eye_height_spin.setMaximum(1000.00)
        self.eye_height_spin.setSingleStep(0.10)
        self.eye_height_spin.setValue(1.80)
        self.eye_height_spin.setSuffix(" m")

        self.curvature_label = QLabel(
            "Enabled: Earth curvature and standard atmospheric "
            "refraction (GDAL curvature coefficient: 0.85714)."
        )
        self.curvature_label.setWordWrap(True)

        self.output_folder_label = QLabel(
            "No output folder selected."
        )
        self.output_folder_label.setWordWrap(True)

        self.select_output_button = QPushButton(
            "Select output folder"
        )

        self.run_button = QPushButton(
            "Run surface visibility analysis"
        )
        self.run_button.setDefault(True)

        self.close_button = QPushButton("Close")

        self.status_label = QLabel(
            "Select both DOM layers, an analysis boundary and "
            "an observer location."
        )
        self.status_label.setWordWrap(True)
        self.status_label.setFrameStyle(
            QFrame.StyledPanel | QFrame.Sunken
        )
        self.status_label.setContentsMargins(8, 8, 8, 8)

    def _create_layout(self):
        main_layout = QVBoxLayout()

        title_label = QLabel(
            "<b>Surface Visibility and Viewing-Angle Analysis</b><br>"
            "Compare DOM-based visibility and vertical viewing angles "
            "between two scenarios."
        )
        title_label.setWordWrap(True)
        main_layout.addWidget(title_label)

        surface_form = QFormLayout()

        surface_form.addRow(
            "Existing surface model:",
            self.dem_2026_combo,
        )

        surface_form.addRow(
            "Future surface model:",
            self.dem_2230_combo,
        )

        surface_form.addRow(
            "Analysis boundary polygon:",
            self.boundary_combo,
        )

        main_layout.addLayout(surface_form)
        main_layout.addWidget(self.refresh_layers_button)
        main_layout.addSpacing(10)

        observer_form = QFormLayout()

        observer_form.addRow(
            "Observer location:",
            self.select_observer_button,
        )

        observer_form.addRow(
            "Selected coordinates:",
            self.observer_coordinates_label,
        )

        observer_form.addRow(
            "Eye height above surface:",
            self.eye_height_spin,
        )

        main_layout.addLayout(observer_form)
        main_layout.addSpacing(10)

        line_of_sight_title = QLabel(
            "<b>Line-of-sight model</b>"
        )

        main_layout.addWidget(line_of_sight_title)
        main_layout.addWidget(self.curvature_label)
        main_layout.addSpacing(10)

        output_form = QFormLayout()

        output_form.addRow(
            "Output folder:",
            self.output_folder_label,
        )

        output_form.addRow(
            "",
            self.select_output_button,
        )

        main_layout.addLayout(output_form)
        main_layout.addSpacing(10)

        main_layout.addWidget(QLabel("<b>Status</b>"))
        main_layout.addWidget(self.status_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.run_button)
        buttons_layout.addWidget(self.close_button)

        main_layout.addLayout(buttons_layout)

        self.setLayout(main_layout)

    def _connect_signals(self):
        self.close_button.clicked.connect(self.close)
        self.select_output_button.clicked.connect(
            self.select_output_folder
        )

    def select_output_folder(self):
        selected_folder = QFileDialog.getExistingDirectory(
            self,
            "Select output folder",
        )

        if selected_folder:
            self.output_folder_label.setText(selected_folder)

    def set_status(self, message, is_error=False):
        color = "#8B0000" if is_error else "#1F4E79"

        self.status_label.setStyleSheet(
            f"QLabel {{ color: {color}; }}"
        )

        self.status_label.setText(message)

    def set_observer_coordinates(
        self,
        x_coordinate,
        y_coordinate,
        crs_authid,
    ):
        self.observer_coordinates_label.setText(
            f"X: {x_coordinate:.3f} | "
            f"Y: {y_coordinate:.3f} | "
            f"CRS: {crs_authid}"
        )

    def selected_dem_2026_id(self):
        return self.dem_2026_combo.currentData()

    def selected_dem_2230_id(self):
        return self.dem_2230_combo.currentData()

    def selected_boundary_id(self):
        return self.boundary_combo.currentData()

    def eye_height(self):
        return self.eye_height_spin.value()

    def output_folder(self):
        text = self.output_folder_label.text()

        if text == "No output folder selected.":
            return None

        return text

    def set_processing_state(self, is_processing):
        enabled = not is_processing

        self.dem_2026_combo.setEnabled(enabled)
        self.dem_2230_combo.setEnabled(enabled)
        self.boundary_combo.setEnabled(enabled)
        self.refresh_layers_button.setEnabled(enabled)
        self.select_observer_button.setEnabled(enabled)
        self.eye_height_spin.setEnabled(enabled)
        self.select_output_button.setEnabled(enabled)
        self.run_button.setEnabled(enabled)
        self.close_button.setEnabled(enabled)
