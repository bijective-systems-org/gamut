"""gamut: one file for a parametric simulation study and the models fitted to it.

A study is a table of runs. Each run has inputs (parameters), names
(labels, such as whether it converged) and results (scalars, and fields
on a mesh), all with units. The whole pattern:

    import gamut

    with gamut.create("polar.gamut", writer="my sweep",
                      parameters={"alpha": {"units": "degree", "role": "condition"}},
                      labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                      scalars={"cl": "1"}) as study:
        for alpha, cl in ((0.0, 0.01), (2.0, 0.23), (4.0, 0.45)):
            study.add_run({"alpha": alpha, "status": "converged", "cl": cl})

    with gamut.open("polar.gamut") as study:
        rows = study.select("alpha > 1 and status == converged")   # positions, from 0
        print(study.get_scalar("cl", rows=rows))

    print(gamut.validate("polar.gamut").ok)

Meshes and fields, families of shapes, time series, uncertainty and fitted
models build on the same calls; the documentation has an example of each,
in Python, MATLAB, Julia and C++: https://bijective-systems-org.github.io/gamut/

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
