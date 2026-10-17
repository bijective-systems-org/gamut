"""mestra: files for parametric simulation studies and their models.

Every call goes to the shared core (a C library); this package is its
Python face, with NumPy as its one dependency.
"""

from ._lib import MestraError, format_string as _format, version as _version
from ._study import Study, create, open
from ._validate import Finding, Report, validate
from ._models import Nearest, create_model, evaluate, register_model_type
from ._files import append, extract, write_copy

__version__ = _version()
FORMAT = _format()

__all__ = ["FORMAT", "Finding", "MestraError", "Nearest", "Report", "Study", "append", "create",
           "create_model", "evaluate", "extract", "open", "register_model_type", "validate",
           "write_copy"]
