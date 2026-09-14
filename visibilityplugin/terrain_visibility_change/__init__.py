# -*- coding: utf-8 -*-

"""
Terrain Visibility Change Analyzer
QGIS Plugin entry point.
"""


def classFactory(iface):
    """
    QGIS calls this function when loading the plugin.
    """

    from .plugin import TerrainVisibilityChangePlugin

    return TerrainVisibilityChangePlugin(iface)