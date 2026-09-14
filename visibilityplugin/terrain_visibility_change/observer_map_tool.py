# -*- coding: utf-8 -*-

from qgis.gui import QgsMapToolEmitPoint


class ObserverMapTool(QgsMapToolEmitPoint):
    """
    Map tool that receives one point after a user click.
    """

    def __init__(self, canvas, callback):
        super().__init__(canvas)

        self._callback = callback

        self.canvasClicked.connect(
            self._handle_canvas_click
        )

    def _handle_canvas_click(self, point, mouse_button):
        """
        Sends the clicked point to the plugin callback.
        """

        self._callback(point)