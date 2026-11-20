# GamutFile

Julia for [Gamut](https://github.com/bijective-systems-org/gamut), an open
file format for parametric simulation studies and fitted models: each run's
inputs and the fields it produced, in one file, and the models fitted to them.

This package is the Julia layer of the Gamut repository, in its `julia/`
folder. Python, MATLAB, C++ and Rust call the same core library, a C++
library with a C interface, so a file written in one language reads the same
in every other. Julia gets that library from `Gamut_jll`.

```julia
using Pkg
Pkg.add("GamutFile")
using GamutFile
GamutFile.version()
```

- [Documentation](https://bijective-systems-org.github.io/gamut/), including
  [the Julia reference](https://bijective-systems-org.github.io/gamut/reference/julia.html)
- [Start here](https://bijective-systems-org.github.io/gamut/first-file.html): a first file in each language
- [Specification](https://bijective-systems-org.github.io/gamut/reference/specification.html)

To use another build of the core, such as one from a checkout, set
`GAMUT_LIBRARY` to its path before the first call.

[Apache 2.0](https://github.com/bijective-systems-org/gamut/blob/main/LICENSE), like the rest of the repository.
