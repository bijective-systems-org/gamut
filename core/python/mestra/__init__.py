"""mestra: files for parametric simulation studies and their models.

Every call goes to the shared core (a C library); this package is its
Python face, with NumPy as its one dependency.
"""

from ._lib import MestraError, format_string as _format, version as _version
from ._study import Study, create, open
from ._validate import Finding, Report, validate

__version__ = _version()
FORMAT = _format()

__all__ = ["FORMAT", "Finding", "MestraError", "Report", "Study", "create", "open",
           "validate"]
