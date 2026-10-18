"""gamut: files for parametric simulation studies and their models.

Every call goes to the shared core (a C library); this package is its
Python face, with NumPy as its one dependency.
"""

from ._lib import GamutError, format_string as _format, path as _path, version as _version
from ._study import Study, create, open
from ._validate import Finding, Report, validate
from ._models import Nearest, create_model, evaluate, register_model_type
from ._files import append, extract, write_copy

__version__ = _version()
FORMAT = _format()


def library_path() -> str:
    """The core library this package loaded. MATLAB and Julia can use the
    same file (it carries its own HDF5 in a wheel)."""
    return _path


__all__ = ["FORMAT", "Finding", "GamutError", "Nearest", "Report", "Study", "append", "create",
           "create_model", "evaluate", "extract", "library_path", "open", "register_model_type",
           "validate", "write_copy"]
