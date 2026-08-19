"""CSV/JSON export of the five analytics reports.

Split the same way the rest of the module is: ``descriptors.py`` says *what*
each report exports (its file name, its query, which array of the report
becomes the table, and the table's column order); ``csv.py`` says *how* a
table is rendered once a format has been chosen. A sixth report or a third
format therefore costs one new descriptor or one new renderer, not a branch
crossed with every report.
"""

from __future__ import annotations

from app.modules.analytics.export.csv import render_csv
from app.modules.analytics.export.descriptors import (
    ANALYTICS_EXPORT_DESCRIPTORS,
    EXPORT_FORMATS,
    AnalyticsExportDescriptor,
    ExportFormat,
)

__all__ = [
    "ANALYTICS_EXPORT_DESCRIPTORS",
    "EXPORT_FORMATS",
    "AnalyticsExportDescriptor",
    "ExportFormat",
    "render_csv",
]
