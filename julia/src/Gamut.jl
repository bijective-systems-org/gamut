"""
    Gamut

Julia over the Gamut core library: the same calls as Python and MATLAB,
in Julia's spelling. Positions (rows, nodes, cells)
are 1-based; arrays come back with the logical axes in order, `p[run, node]`.
Cell connectivity holds the stored 0-based node numbers, as in every
language (VTK's convention).

The core is found at `ENV["GAMUT_LIBRARY"]`, else beside this package in
`build/` at the top of a checkout. Only the built-in `Nearest` model type
evaluates here; others are registered in Python or MATLAB.
"""
module Gamut

using Libdl

export GamutError

# --- the library ----------------------------------------------------------------------

const HANDLE = Ref{Ptr{Cvoid}}(C_NULL)
const SYMBOLS = Dict{Symbol,Ptr{Cvoid}}()
# The cache is filled lazily from any task, so every look-up takes the lock;
# finalizers never look up (they use pointers taken when the study opened).
const SYMBOLS_LOCK = ReentrantLock()

function library_path()
    p = get(ENV, "GAMUT_LIBRARY", "")
    isempty(p) || return p
    name = Sys.isapple() ? "libgamut.dylib" : Sys.iswindows() ? "gamut.dll" : "libgamut.so"
    return normpath(joinpath(@__DIR__, "..", "..", "build", name))
end

function sym(name::Symbol)
    lock(SYMBOLS_LOCK) do
        get!(SYMBOLS, name) do
            if HANDLE[] == C_NULL
                p = library_path()
                isfile(p) || error("the Gamut core library ($p) was not found; set " *
                                   "GAMUT_LIBRARY to its path: the Python wheel's (pip install " *
                                   "gamut-format, then python -c \"import gamut; " *
                                   "print(gamut.library_path())\"), or one built from a " *
                                   "checkout with cmake -S . -B build && cmake --build build")
                HANDLE[] = Libdl.dlopen(p)
            end
            Libdl.dlsym(HANDLE[], name)
        end
    end
end

struct CError
    rule::NTuple{8,UInt8}
    path::NTuple{512,UInt8}
    message::NTuple{2048,UInt8}
end

struct CSel
    kind::Cint
    start::Int64
    stop::Int64
    index::Ptr{Int64}
    count::Int64
end

"""
    GamutError(rule, message, path)

The one error: `rule` is the spec's rule id ("E7") or empty, `path` a
concept path (`node_fields/p`) or empty, `message` what went wrong.
"""
struct GamutError <: Exception
    rule::String
    message::String
    path::String
end
GamutError(rule, message) = GamutError(rule, message, "")
Base.showerror(io::IO, e::GamutError) =
    print(io, isempty(e.rule) ? e.message : "$(e.rule): $(e.message)")

function text(t::NTuple)
    n = something(findfirst(==(0x00), t), length(t) + 1) - 1
    return String(UInt8[t[i] for i in 1:n])
end

function check(status, err::Ref{CError})
    status == 0 && return nothing
    e = err[]
    throw(GamutError(text(e.rule), text(e.message), text(e.path)))
end

# A status-returning core call: @mes name (argument types...) arguments...
macro mes(name, types, args...)
    quote
        local err = Ref{CError}()
        local status = ccall(sym($(QuoteNode(name))), Cint, ($(types.args...), Ref{CError}),
                             $(map(esc, args)...), err)
        check(status, err)
    end
end

"""A name or text for the C side; a NUL would end it early, so it is refused."""
function cs(s)
    t = string(s)
    occursin('\0', t) && throw(GamutError("", "$(repr(t)) holds a NUL character, which no " *
                                                 "name or text may hold"))
    return t
end

# A list of strings as `const char* const*`; keep the returned vector alive.
function cstrings(items)
    strs = String[cs(x) for x in items]
    return strs, Ptr{UInt8}[pointer(s) for s in strs]
end

function take_strings(h::Ptr{Cvoid})
    try
        n = ccall(sym(:gamut_strings_count), Int64, (Ptr{Cvoid},), h)
        return String[unsafe_string(ccall(sym(:gamut_strings_get), Cstring, (Ptr{Cvoid}, Int64),
                                          h, i)) for i in 0:n-1]
    finally
        ccall(sym(:gamut_strings_free), Cvoid, (Ptr{Cvoid},), h)
    end
end

version() = unsafe_string(ccall(sym(:gamut_version), Cstring, ()))
format() = unsafe_string(ccall(sym(:gamut_format), Cstring, ()))

const DTYPE = Dict(UInt8 => 1, Int8 => 2, Int32 => 3, Int64 => 4, Float32 => 5, Float64 => 6)
const AS_GIVEN = 0
# The most rows a selection scans (docs/security.md).
const MAX_ROWS_SCANNED = Int64(1) << 27

function precision_code(v)
    v === nothing && return AS_GIVEN
    t = Dict("float32" => 5, "float64" => 6, "int64" => 4)
    key = v isa Type ? lowercase(string(v)) : string(v)
    haskey(t, key) || throw(GamutError("E4", "precision $(repr(v)) is not float32, float64 " *
                                              "or int64"))
    return t[key]
end

# Arrays cross in C order. Julia is column-major: a logical (run, node)
# array is laid out as its transpose.
c_order(a::AbstractVector) = collect(a)
c_order(a::AbstractArray) = vec(permutedims(a, ndims(a):-1:1))
function from_c_order(buf::Vector{T}, dims) where {T}
    length(dims) <= 1 && return length(dims) == 0 ? buf[1] : buf
    return permutedims(reshape(buf, reverse(Tuple(dims))), length(dims):-1:1)
end

# --- selections ------------------------------------------------------------------------

struct Selection
    sel::CSel
    keep::Vector{Int64}
    single::Bool
end

selection(::Nothing, what) = Selection(CSel(0, 0, 0, C_NULL, 0), Int64[], false)
selection(::Colon, what) = selection(nothing, what)
function selection(x::Integer, what)
    x isa Bool && throw(GamutError("", "$what: positions are integers, ranges or nothing"))
    keep = Int64[x - 1]
    return Selection(CSel(2, 0, 0, pointer(keep), 1), keep, true)
end
function selection(r::AbstractUnitRange{<:Integer}, what)
    return Selection(CSel(1, first(r) - 1, max(first(r) - 1, last(r)), C_NULL, 0), Int64[], false)
end
function selection(v::AbstractVector, what)
    eltype(v) <: Integer && !(eltype(v) <: Bool) || isempty(v) ||
        throw(GamutError("", "$what: positions are integers, ranges or nothing; got " *
                              "$(eltype(v)) values"))
    keep = Int64[i - 1 for i in v]
    return Selection(CSel(2, 0, 0, pointer(keep), length(keep)), keep, false)
end
selection(x, what) = throw(GamutError("", "$what: positions are integers, ranges or " *
                                           "nothing; got $(typeof(x))"))

# --- the study ------------------------------------------------------------------------

"""
A study file open to write (`Gamut.create`, `Gamut.open(path; mode="a")`)
or to read (`Gamut.open`). Close it with `close`, or use the do-block forms.
"""
mutable struct Study
    handle::Ptr{Cvoid}
    path::String
    writing::Bool
    mesh_kind::String
    per::String
    group::String
    axes::Int
    described::Dict{String,Dict{String,String}}
    remove_on_close::Bool
    function Study(h, path, writing, mesh_kind="", per="")
        s = new(h, path, writing, mesh_kind, per,
                startswith(per, "group:") ? per[7:end] : "", 3,
                Dict{String,Dict{String,String}}(), false)
        close_ptr, abandon_ptr = sym(:gamut_close), sym(:gamut_abandon)
        finalizer(s) do x
            # A study left open is finished as close would, its temporary file
            # removed as close removes it; errors have no one to go to here.
            h = getfield(x, :handle)
            h == C_NULL && return
            err = Ref{CError}()
            if ccall(close_ptr, Cint, (Ptr{Cvoid}, Ref{CError}), h, err) != 0
                ccall(abandon_ptr, Cvoid, (Ptr{Cvoid}, Cint), h, 0)
            end
            setfield!(x, :handle, C_NULL)
            p = getfield(x, :path)
            getfield(x, :remove_on_close) && try
                isfile(p) && rm(p)
            catch
            end
        end
        return s
    end
end

function handle(s::Study)
    s.handle == C_NULL && throw(GamutError("", "$(s.path) is closed"))
    return s.handle
end

# A refused close (a shared mesh never set, a model file without a model)
# keeps the study open to fix and close again.
function Base.close(s::Study)
    s.handle == C_NULL && return nothing
    @mes gamut_close (Ptr{Cvoid},) s.handle
    s.handle = C_NULL
    s.remove_on_close && isfile(s.path) && rm(s.path)
    return nothing
end

# Releases the file without finishing it; with `remove`, deletes a file
# this handle created. For giving up after an error.
function abandon(s::Study, remove::Bool)
    s.handle == C_NULL && return nothing
    h, s.handle = s.handle, C_NULL
    ccall(sym(:gamut_abandon), Cvoid, (Ptr{Cvoid}, Cint), h, remove ? 1 : 0)
    return nothing
end

Base.isopen(s::Study) = s.handle != C_NULL
Base.show(io::IO, s::Study) =
    print(io, "Gamut.Study(", repr(s.path), s.writing ? ", writing" : "", isopen(s) ? "" : ", closed", ")")

function with_study(f, s::Study)
    try
        r = f(s)
        close(s)
        return r
    catch
        # Leaving on an error: finish the file if it can be finished, else
        # discard a file this study created; the first error stands.
        try
            close(s)
        catch
            abandon(s, true)
        end
        rethrow()
    end
end

need_writer(s::Study) = s.writing || throw(GamutError("", "$(s.path) was opened to read"))
need_reader(s::Study) = !s.writing || throw(GamutError("", "$(s.path) is open to write; " *
                                                          "close it and open it to read"))

# --- creating ---------------------------------------------------------------------------

spec(v::AbstractString, key) = Dict{String,Any}(key => String(v))
spec(v::NamedTuple, key) = Dict{String,Any}(string(k) => x for (k, x) in pairs(v))
spec(v::AbstractDict, key) = Dict{String,Any}(string(k) => x for (k, x) in v)
spec(v, key) = throw(GamutError("", "a declaration is units text, a NamedTuple or a Dict"))

pairs_of(::Nothing) = Pair{String,Any}[]
pairs_of(d::AbstractDict) = [string(k) => v for (k, v) in d]
pairs_of(d::NamedTuple) = [string(k) => v for (k, v) in pairs(d)]

getstr(d, k, default="") = string(get(d, k, default))

function declare(h, kw)
    precision = Dict(pairs_of(get(kw, :precision, nothing)))
    round_bits = Dict(pairs_of(get(kw, :round_bits, nothing)))
    if !get(kw, :compression, true)
        @mes gamut_set_compression (Ptr{Cvoid}, Cint, Cint) h 0 0
    end
    for key in (:title, :license, :references, :source, :portion_marking, :trained_on)
        v = get(kw, key, nothing)
        v === nothing && continue
        value = v isa AbstractVector ? join(string.(v), " ") : string(v)
        @mes gamut_set_attribute (Ptr{Cvoid}, Cstring, Cstring) h cs(key) cs(value)
    end
    for (name, v) in pairs_of(get(kw, :labels, nothing))
        d = v === Bool ? Dict{String,Any}("role" => "categorical", "categories" => ["false", "true"]) :
            v isa AbstractString ? Dict{String,Any}("role" => v) : spec(v, "role")
        strs, ptrs = cstrings(get(d, "categories", String[]))
        GC.@preserve strs begin
            @mes gamut_declare_label (Ptr{Cvoid}, Cstring, Cstring, Ptr{Ptr{UInt8}}, Int64) h cs(name) cs(getstr(d, "role", "categorical")) ptrs length(ptrs)
        end
    end
    for (name, v) in pairs_of(get(kw, :parameters, nothing))
        d = spec(v, "units")
        has = haskey(d, "lower") || haskey(d, "upper")
        @mes gamut_declare_parameter (Ptr{Cvoid}, Cstring, Cstring, Cstring, Cint, Cint, Cdouble, Cdouble, Cstring) h cs(name) cs(getstr(d, "role", "design")) cs(getstr(d, "units")) precision_code(get(precision, name, get(d, "dtype", nothing))) (has ? 1 : 0) Float64(get(d, "lower", NaN)) Float64(get(d, "upper", NaN)) cs(getstr(d, "run_group"))
    end
    c = get(kw, :coordinates, nothing)
    if c !== nothing
        d = spec(c, "units")
        @mes gamut_declare_coordinates (Ptr{Cvoid}, Cstring, Cint, Cint, Cstring, Cstring) h cs(getstr(d, "units")) precision_code(get(d, "precision", nothing)) Int(get(d, "axes", 3)) cs(getstr(d, "model")) cs(getstr(d, "output"))
    end
    for (name, v) in pairs_of(get(kw, :mesh_labels, nothing))
        d = spec(v, "at")
        strs, ptrs = cstrings(get(d, "categories", String[]))
        GC.@preserve strs begin
            @mes gamut_declare_mesh_label (Ptr{Cvoid}, Cstring, Cstring, Ptr{Ptr{UInt8}}, Int64) h cs(name) cs(getstr(d, "at", "cell")) ptrs length(ptrs)
        end
    end
    function result(name, d, where)
        q = get(d, "q", nothing)
        @mes gamut_declare_result (Ptr{Cvoid}, Cstring, Cstring, Cstring, Cint, Cstring, Cstring, Cint, Cdouble, Cstring, Cstring, Cstring, Cstring, Cint, Cstring, Cstring) h cs(name) cs(where) cs(getstr(d, "units")) precision_code(get(precision, name, get(d, "precision", nothing))) cs(getstr(d, "of")) cs(getstr(d, "statistic")) (q === nothing ? 0 : 1) Float64(something(q, 0.0)) cs(getstr(d, "method")) cs(getstr(d, "with_respect_to")) cs(getstr(d, "axis")) cs(getstr(d, "vector")) Int(get(round_bits, name, get(d, "round_bits", -1))) cs(getstr(d, "model")) cs(getstr(d, "output"))
    end
    for (name, v) in pairs_of(get(kw, :scalars, nothing))
        result(name, spec(v, "units"), "scalar")
    end
    for (name, v) in pairs_of(get(kw, :fields, nothing))
        d = spec(v, "units")
        result(name, d, getstr(d, "at", "node"))
    end
    g = get(kw, :generalisation_group, nothing)
    if g !== nothing
        @mes gamut_set_generalisation_group (Ptr{Cvoid}, Cstring) h cs(g)
    end
    for (name, v) in pairs_of(get(kw, :constants, nothing))
        number, units = v
        if number isa Float32
            @mes gamut_set_constant (Ptr{Cvoid}, Cstring, Cstring, Cint, Cdouble, Int64) h cs(name) cs(units) 5 Float64(number) 0
        elseif number isa Integer && !(number isa Bool)
            @mes gamut_set_constant (Ptr{Cvoid}, Cstring, Cstring, Cint, Cdouble, Int64) h cs(name) cs(units) 4 0.0 Int64(number)
        else
            @mes gamut_set_constant (Ptr{Cvoid}, Cstring, Cstring, Cint, Cdouble, Int64) h cs(name) cs(units) 6 Float64(number) 0
        end
    end
end

"""
    Gamut.create(path; writer, parameters, labels, scalars, fields, mesh_labels,
                  constants, mesh, per, coordinates, precision, round_bits, title,
                  license, references, source, portion_marking, generalisation_group,
                  compression)

Creates a data file and returns it open to add runs.
Declarations are Dicts (or NamedTuples) from a name to its units text or
to its specification, as in Python: `parameters = Dict("mach" => "1")`,
`fields = Dict("p" => (units = "Pa", at = "node"))`.
"""
function axes_of(kw)
    c = get(kw, :coordinates, nothing)
    c === nothing && return 3
    v = get(spec(c, "units"), "axes", 3)
    (v isa Integer && !(v isa Bool)) || throw(GamutError("E24", "coordinates: axes is 1, 2 or 3, not $(repr(v))"))
    return Int(v)
end

function create(path::AbstractString; writer::AbstractString, mesh=nothing, per=nothing, kw...)
    axes_of(kw)                      # before the file exists: a refusal leaves none
    out = Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_create (Cstring, Cstring, Cstring, Cstring, Ref{Ptr{Cvoid}}) cs(path) cs(writer) cs(something(mesh, "")) cs(something(per, "")) out
    return started(Study(out[], String(path), true, something(mesh, ""), something(per, "")), kw)
end
create(f::Function, path::AbstractString; kw...) = with_study(f, create(path; kw...))

"""
    Gamut.create_model(path; writer, parameters, labels, scalars, fields, constants,
                        mesh, per, coordinates, trained_on, title, license,
                        references, source, portion_marking)

Creates a model file (spec section 7): parameters with bounds, every result
naming the model and output that computes it; then `add_model!`.
"""
function create_model(path::AbstractString; writer::AbstractString, mesh=nothing, per="fixed", kw...)
    axes_of(kw)                      # before the file exists: a refusal leaves none
    out = Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_create_model (Cstring, Cstring, Cstring, Cstring, Ref{Ptr{Cvoid}}) cs(path) cs(writer) cs(something(mesh, "")) cs(per) out
    return started(Study(out[], String(path), true, something(mesh, ""), mesh === nothing ? "" : per), kw)
end
create_model(f::Function, path::AbstractString; kw...) = with_study(f, create_model(path; kw...))

const DECLARATIONS = (:parameters, :labels, :scalars, :fields, :mesh_labels, :constants,
                      :coordinates, :precision, :round_bits, :title, :license, :references,
                      :source, :portion_marking, :generalisation_group, :compression, :trained_on)

function started(s::Study, kw)
    unknown = setdiff(keys(kw), DECLARATIONS)
    if !isempty(unknown)
        abandon(s, true)
        throw(GamutError("", "unknown keyword $(first(unknown)); the declarations are " *
                              join(DECLARATIONS, ", ")))
    end
    s.axes = axes_of(kw)
    try
        declare(s.handle, kw)
    catch
        # A half-declared file is not wanted; the declaration error stands.
        abandon(s, true)
        rethrow()
    end
    return s
end

"""
    Gamut.open(path; mode="r", threads=1)

Opens a file to read, or with `mode="a"` to add runs in place. `threads`
decompresses field reads in that many threads.
"""
function open(path::AbstractString; mode::AbstractString="r", threads::Integer=1)
    out = Ref{Ptr{Cvoid}}(C_NULL)
    if mode == "r"
        @mes gamut_open (Cstring, Ref{Ptr{Cvoid}}) cs(path) out
        s = Study(out[], String(path), false)   # owns the handle, so a refusal closes it
        try
            s.mesh_kind = info(s, "mesh_kind")
            s.per = info(s, "per")
            s.group = startswith(s.per, "group:") ? s.per[7:end] : ""
            threads != 1 && @mes gamut_set_threads (Ptr{Cvoid}, Cint) s.handle threads
        catch
            close(s)
            rethrow()
        end
        return s
    elseif mode == "a"
        kind, per, axes = open(path) do r
            r.mesh_kind, r.per, isempty(r.mesh_kind) ? 3 : parse(Int, get(describe(r, "coordinates"), "axes", "3"))
        end
        @mes gamut_open_append (Cstring, Ref{Ptr{Cvoid}}) cs(path) out
        s = Study(out[], String(path), true, kind, per)
        s.axes = axes
        return s
    end
    throw(GamutError("", "mode is \"r\" or \"a\""))
end
open(f::Function, path::AbstractString; kw...) = with_study(f, open(path; kw...))

# --- writing ----------------------------------------------------------------------------

# Values as Float64, refusing an integer a Float64 would round (past 2^53), as
# the core does: for values computed with here before the core sees them.
function float64_exactly(v, name)
    for x in v
        x isa Integer && !(x isa Bool) && Float64(x) != x &&
            throw(GamutError("E4", "$name: $x is not exact as a float64, which holds every integer only to 2^53"))
    end
    return Float64.(v)
end

function stage_geometry(s::Study, points, cells, labels)
    h = handle(s)
    if points !== nothing
        p = points isa AbstractMatrix ? points : reshape(points, :, 1)
        T = eltype(p) <: AbstractFloat ? eltype(p) : Float64
        buf = c_order(T === eltype(p) ? p : float64_exactly(p, "coordinates"))
        GC.@preserve buf begin
            @mes gamut_geometry_points (Ptr{Cvoid}, Cint, Ptr{Cvoid}, Int64, Int64, Cint) h DTYPE[T] pointer(buf) length(buf) size(p, 1) size(p, 2)
        end
    end
    if cells !== nothing
        types = Vector{UInt8}(cells[1])
        offsets = Vector{Int64}(cells[2])
        conn = Vector{Int64}(cells[3])
        @mes gamut_geometry_cells (Ptr{Cvoid}, Ptr{UInt8}, Int64, Ptr{Int64}, Int64, Ptr{Int64}, Int64) h types length(types) offsets length(offsets) conn length(conn)
    end
    for (name, v) in pairs_of(labels)
        vals = Vector{Int64}(v)
        @mes gamut_geometry_label (Ptr{Cvoid}, Cstring, Ptr{Int64}, Int64) h cs(name) vals length(vals)
    end
end

"""
    set_mesh!(study; points=nothing, cells=nothing, labels=nothing, n_nodes=nothing)

A shared mesh: its cells `(types, offsets, connectivity)`, its fixed mesh
labels, and its points (nodes × axes) when the geometry is fixed; when the
coordinates come with the runs, `n_nodes` instead of points.
"""
function set_mesh!(s::Study; points=nothing, cells=nothing, labels=nothing, n_nodes=nothing)
    need_writer(s)
    h = handle(s)
    @mes gamut_geometry_begin (Ptr{Cvoid},) h
    if points === nothing
        n_nodes === nothing && throw(GamutError("", "give the points, or n_nodes when the " *
                                                     "coordinates come with the runs"))
        @mes gamut_geometry_points (Ptr{Cvoid}, Cint, Ptr{Cvoid}, Int64, Int64, Cint) h 6 C_NULL 0 n_nodes s.axes
    end
    stage_geometry(s, points, cells, labels)
    @mes gamut_set_mesh (Ptr{Cvoid},) h
    return nothing
end

"""
    add_run!(study, values; fields=nothing, points=nothing, cells=nothing, mesh_labels=nothing)

Adds one run and returns its id. `values` maps each parameter, label (by
name, or a Bool for a yes/no label) and scalar to this run's value;
`fields` each field to one value per node or cell.
"""
function add_run!(s::Study, values; fields=nothing, points=nothing, cells=nothing, mesh_labels=nothing)
    cols = Dict{String,Any}(k => [v] for (k, v) in pairs_of(values))
    flds = Dict{String,Any}(k => (s.mesh_kind == "changing" ? collect(v) : reshape(collect(v), 1, :))
                            for (k, v) in pairs_of(fields))
    return commit!(s, 1, cols, flds, points === nothing ? nothing : [points],
                   cells === nothing ? nothing : [cells],
                   mesh_labels === nothing ? nothing : [mesh_labels])[1]
end

"""
    add_runs!(study, columns; fields=nothing, points=nothing, cells=nothing, mesh_labels=nothing)

Adds many runs at once: `columns` maps each name to one value per run;
`fields` to runs × sites (a changing mesh: every run's values end to end);
`points`, `cells`, `mesh_labels` one per run (or per new group member).
"""
function add_runs!(s::Study, columns; fields=nothing, points=nothing, cells=nothing, mesh_labels=nothing)
    cols = Dict{String,Any}(pairs_of(columns))
    lengths = unique(length(v) for v in values(cols))
    length(lengths) == 1 || throw(GamutError("E5", "every column needs the same number of runs; given " *
        (isempty(cols) ? "no columns" : join(("$k $(length(v))" for (k, v) in sort!(collect(cols); by=first)), ", "))))
    return commit!(s, lengths[1], cols, Dict{String,Any}(pairs_of(fields)), points, cells, mesh_labels)
end

function commit!(s::Study, n, columns, fields, points, cells, mesh_labels)
    need_writer(s)
    h = handle(s)
    @mes gamut_batch_begin (Ptr{Cvoid}, Int64) h n
    keep = Any[]
    group_names = nothing
    for (name, vals) in columns
        v = collect(vals)
        if eltype(v) <: Union{AbstractString,Bool} || eltype(v) == Any && all(x -> x isa Union{AbstractString,Bool}, v)
            names = String[x === true ? "true" : x === false ? "false" : string(x) for x in v]
            strs, ptrs = cstrings(names)
            GC.@preserve strs begin
                @mes gamut_batch_names (Ptr{Cvoid}, Cstring, Ptr{Ptr{UInt8}}, Int64) h cs(name) ptrs length(ptrs)
            end
            name == s.group && (group_names = names)
            continue
        end
        buf = numbers(v)
        push!(keep, buf)
        first = ndims(v) > 1 ? size(v, 1) : 0
        @mes gamut_batch_values (Ptr{Cvoid}, Cstring, Cint, Ptr{Cvoid}, Int64, Int64) h cs(name) DTYPE[eltype(buf)] pointer(buf) first length(buf)
    end
    for (name, vals) in fields
        buf = numbers(c_order(vals))
        push!(keep, buf)
        first = ndims(vals) > 1 ? size(vals, 1) : 0
        @mes gamut_batch_values (Ptr{Cvoid}, Cstring, Cint, Ptr{Cvoid}, Int64, Int64) h cs(name) DTYPE[eltype(buf)] pointer(buf) first length(buf)
    end
    if points !== nothing
        pts = collect(points)
        cls = cells === nothing ? fill(nothing, length(pts)) : collect(cells)
        mls = mesh_labels === nothing ? fill(nothing, length(pts)) : collect(mesh_labels)
        if !isempty(s.group)
            group_names === nothing && throw(GamutError("E2", "give $(s.group) by name so " *
                                                               "geometry can be matched to members"))
            for (i, member) in enumerate(group_names)
                pts[i] === nothing && continue
                @mes gamut_geometry_begin (Ptr{Cvoid},) h
                stage_geometry(s, pts[i], cls[i], mls[i])
                @mes gamut_batch_geometry_for_member (Ptr{Cvoid}, Cstring) h cs(member)
            end
        else
            for i in eachindex(pts)
                @mes gamut_geometry_begin (Ptr{Cvoid},) h
                stage_geometry(s, pts[i], cls[i], mls[i])
                @mes gamut_batch_geometry_for_row (Ptr{Cvoid},) h
            end
        end
    end
    first = Ref{Int64}(0)
    GC.@preserve keep begin
        @mes gamut_batch_commit (Ptr{Cvoid}, Ref{Int64}) h first
    end
    return collect(first[]:first[]+n-1)
end

# Values as one of the core's dtypes, kept as given (precision is the
# core's to resolve).
function numbers(v::AbstractArray)
    T = eltype(v)
    T <: Union{Float32,Float64,Int8,UInt8,Int32,Int64} && return collect(v)
    T <: Bool && throw(GamutError("E4", "booleans are given as a label's names"))
    T <: Integer && return Vector{Int64}(vec(v))
    T <: Real && return float64_exactly(vec(v), "a value")
    all(x -> x isa Integer && !(x isa Bool), v) && return Int64[x for x in v]
    all(x -> x isa Real, v) && return float64_exactly(vec(v), "a value")
    throw(GamutError("E4", "values are numbers; got $(T)"))
end

"""    set_note!(study, key, value)    Free-form public notes: text, integers, floats."""
function set_note!(s::Study, key, value)
    h = handle(s)
    if value isa Integer       # a Bool is the integer 1 or 0, as in Python
        @mes gamut_set_note_int (Ptr{Cvoid}, Cstring, Int64) h cs(key) Int64(value)
    elseif value isa Real
        @mes gamut_set_note_float (Ptr{Cvoid}, Cstring, Cdouble) h cs(key) Float64(value)
    else
        @mes gamut_set_note_text (Ptr{Cvoid}, Cstring, Cstring) h cs(key) cs(value)
    end
end

# --- reading ----------------------------------------------------------------------------

function info(s::Study, key)
    out = Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_info (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}) handle(s) cs(key) out
    v = take_strings(out[])
    return isempty(v) ? "" : v[1]
end

function Base.getproperty(s::Study, name::Symbol)
    name === :kind && return (need_reader(s); info(s, "kind"))
    name === :type && return (need_reader(s); info(s, "type"))
    name === :row_count && return (need_reader(s); parse(Int, info(s, "row_count")))
    name === :addons && return begin
        need_reader(s)
        out = Ref{Ptr{Cvoid}}(C_NULL)
        @mes gamut_info (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}) handle(s) "addons" out
        take_strings(out[])
    end
    return getfield(s, name)
end
Base.propertynames(::Study) = (:path, :kind, :type, :row_count, :addons)

"""    names(study, group)    "parameters", "labels", "scalars", "constants", "node_fields", ..."""
function names(s::Study, group)
    need_reader(s)
    out = Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_names (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}) handle(s) cs(group) out
    return take_strings(out[])
end

"""    describe(study, name=nothing)    A concept's attributes as text; with no name the file's own."""
function describe(s::Study, name=nothing)
    need_reader(s)
    key = name === nothing ? "" : string(name)
    get!(s.described, key) do
        k, v = Ref{Ptr{Cvoid}}(C_NULL), Ref{Ptr{Cvoid}}(C_NULL)
        @mes gamut_describe (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}, Ref{Ptr{Cvoid}}) handle(s) cs(key) k v
        Dict(zip(take_strings(k[]), take_strings(v[])))
    end |> copy
end

# A concept's attributes as a reader relies on them: an entry the file lacks
# is refused, rather than a missing key.
struct Declaration
    name::String
    entries::Dict{String,String}
end
declared(s::Study, name) = Declaration(string(name), describe(s, name))
Base.get(d::Declaration, key, default) = get(d.entries, key, default)
Base.haskey(d::Declaration, key) = haskey(d.entries, key)
Base.getindex(d::Declaration, key) = haskey(d.entries, key) ? d.entries[key] :
    throw(GamutError("", "$(d.name) has no $key; gamut validate says what the file breaks", d.name))

"""    model_numbers(study, id)    A model's stored numbers (spec section 12) as a Dict; its type need not be registered."""
function model_numbers(s::Study, id)
    need_reader(s)
    out = Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_model_numbers (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}) handle(s) cs(id) out
    try
        return from_tree(out[])
    finally
        ccall(sym(:gamut_tree_free), Cvoid, (Ptr{Cvoid},), out[])
    end
end

function read(s::Study, name, rows, sites, ::Type{T}; squeeze=true) where {T}
    need_reader(s)
    r, x = selection(rows, "rows"), selection(sites, "sites")
    shape = zeros(Int64, 4)
    rank = Ref{Cint}(0)
    rsel, ssel = Ref(r.sel), Ref(x.sel)
    rk, xk = r.keep, x.keep
    GC.@preserve rk xk begin
        @mes gamut_shape (Ptr{Cvoid}, Cstring, Ref{CSel}, Ref{CSel}, Ref{Cint}, Ptr{Int64}, Cint) handle(s) cs(name) rsel ssel rank shape length(shape)
        dims = shape[1:rank[]]
        buf = Vector{T}(undef, prod(dims; init=1))
        @mes gamut_read (Ptr{Cvoid}, Cstring, Ref{CSel}, Ref{CSel}, Cint, Ptr{Cvoid}, Int64) handle(s) cs(name) rsel ssel DTYPE[T] pointer(buf) sizeof(buf)
    end
    out = from_c_order(buf, dims)
    if squeeze && r.single && length(dims) >= 1 && dims[1] == 1
        out = length(dims) == 1 ? out[1] : selectdim(out, 1, 1) |> collect
    end
    return out
end

result_type(s, name) = get(describe(s, name), "dtype", "") == "float32" ? Float32 : Float64

get_row_ids(s::Study; rows=nothing) = read(s, "row", rows, nothing, Int64)
get_parameter(s::Study, name; rows=nothing) =
    read(s, name, rows, nothing, get(describe(s, name), "dtype", "") == "int64" ? Int64 : Float64)
get_label_codes(s::Study, name; rows=nothing) = read(s, name, rows, nothing, Int64)
get_scalar(s::Study, name; rows=nothing) = read(s, name, rows, nothing, result_type(s, name))

"""
    outside(study, name; rows=nothing)

How far each row's value of the parameter `name` lies outside the bounds
the file declares for it, in the parameter's units: 0 inside or on a bound,
`value - lower` (negative) below, `value - upper` (positive) above, `NaN`
where the value is missing. A parameter with no bounds is refused. The
answer of `evaluate` keeps the model's bounds, so this says which of its
rows lie outside the range the model was fitted on, and how far.
"""
function outside(s::Study, name; rows=nothing)
    need_reader(s)
    r = selection(rows, "rows")
    shape = zeros(Int64, 4)
    rank = Ref{Cint}(0)
    rsel = Ref(r.sel)
    rk = r.keep
    GC.@preserve rk begin
        @mes gamut_shape (Ptr{Cvoid}, Cstring, Ref{CSel}, Ptr{CSel}, Ref{Cint}, Ptr{Int64}, Cint) handle(s) cs(name) rsel C_NULL rank shape length(shape)
        # Sized as a read of the parameter; for any other name the core refuses.
        out = Vector{Float64}(undef, rank[] == 1 ? shape[1] : 0)
        @mes gamut_outside (Ptr{Cvoid}, Cstring, Ref{CSel}, Ptr{Float64}, Int64) handle(s) cs(name) rsel out sizeof(out)
    end
    return r.single ? out[1] : out
end

function get_label(s::Study, name; rows=nothing)
    need_reader(s)
    r = selection(rows, "rows")
    out = Ref{Ptr{Cvoid}}(C_NULL)
    rsel = Ref(r.sel)
    rk = r.keep
    GC.@preserve rk begin
        @mes gamut_label_names (Ptr{Cvoid}, Cstring, Ref{CSel}, Ref{Ptr{Cvoid}}) handle(s) cs(name) rsel out
    end
    v = take_strings(out[])
    return r.single ? v[1] : v
end

function get_constant(s::Study, name)
    get(describe(s, name), "dtype", "") == "int64" ? read(s, name, nothing, nothing, Int64) :
        read(s, name, nothing, nothing, Float64)
end

function one_row(row)
    row === nothing && return nothing
    (row isa Integer && !(row isa Bool)) || throw(GamutError("", "row: one integer position; got $(repr(row))"))
    return [row]
end

"""    get_cells(study; row=nothing)    (types, offsets, connectivity); a changing mesh needs the row."""
function get_cells(s::Study; row=nothing)
    r = one_row(row)
    return (read(s, "cells/types", r, nothing, UInt8), read(s, "cells/offsets", r, nothing, Int64),
            read(s, "cells/connectivity", r, nothing, Int64))
end

"""    get_points(study; row=nothing)    nodes × axes; a row is needed unless per = fixed."""
function get_points(s::Study; row=nothing)
    row === nothing && s.per ∉ ("fixed", "") && throw(GamutError("", "this mesh's geometry changes; give the row"))
    T = get(describe(s, "coordinates"), "dtype", "") == "float32" ? Float32 : Float64
    out = read(s, "coordinates", one_row(row), nothing, T; squeeze=false)
    return row !== nothing && s.mesh_kind == "shared" ? out[1, :, :] : out
end

"""    get_field(study, name; rows=nothing, nodes=nothing, cells=nothing)    runs × sites on a shared mesh."""
function get_field(s::Study, name; rows=nothing, nodes=nothing, cells=nothing)
    sites = nodes !== nothing ? nodes : cells
    if s.mesh_kind == "changing"
        rows isa Integer && !(rows isa Bool) || rows isa AbstractVector && length(rows) == 1 ||
            throw(GamutError("", "$name: a changing mesh is read one row at a time; reads " *
                                  "across rows need a shared mesh"))
        rows = rows isa Integer ? [rows] : collect(rows)
    end
    # A changing mesh's field has no row axis (one row at a time).
    return read(s, name, rows, sites, result_type(s, name); squeeze=s.mesh_kind != "changing")
end

get_mesh_label(s::Study, name; row=nothing) = read(s, name, one_row(row), nothing, Int64; squeeze=false)

"""    categories(study, name)    The category table of a label or mesh label: code c names entry c + 1."""
function categories(s::Study, name)
    t = get(describe(s, name), "category", "")
    isempty(t) && throw(GamutError("", "$name has no category table; its codes are its values"))
    out = Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_table (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}) handle(s) cs(t) out
    return take_strings(out[])
end

"""    table(study; names=nothing, rows=nothing)    the run table as columns; labels as names."""
function table(s::Study; names=nothing, rows=nothing)
    params = Gamut.names(s, "parameters")
    labels = Gamut.names(s, "labels")
    names = something(names, vcat(params, labels, Gamut.names(s, "scalars")))
    out = Dict{String,Any}()
    for n in names
        out[n] = n in labels ? get_label(s, n; rows) : n in params ? get_parameter(s, n; rows) :
                 get_scalar(s, n; rows)
    end
    return out
end

"""    select(study, where)    the 1-based row positions matching, e.g. "mach > 0.5 and status == converged"."""
function select(s::Study, where)
    need_reader(s)
    # The core refuses a larger file before it fills a buffer, so none
    # larger is allocated.
    out = Vector{Int64}(undef, 0 < s.row_count <= MAX_ROWS_SCANNED ? s.row_count : 1)
    n = Ref{Int64}(0)
    @mes gamut_select (Ptr{Cvoid}, Cstring, Ptr{Int64}, Int64, Ref{Int64}) handle(s) cs(where) out length(out) n
    return out[1:n[]] .+ 1
end

"""    related(study, name)    its std, quantiles, derivatives and vector parts (spec section 6)."""
function related(s::Study, name)
    need_reader(s)
    t, k, n = Ref{Ptr{Cvoid}}(C_NULL), Ref{Ptr{Cvoid}}(C_NULL), Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_related (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}, Ref{Ptr{Cvoid}}, Ref{Ptr{Cvoid}}) handle(s) cs(name) t k n
    kinds, keys, names = take_strings(t[]), take_strings(k[]), take_strings(n[])
    out = Dict{String,Any}("std" => nothing, "quantiles" => Dict{Float64,String}(),
                           "derivatives" => Dict{String,String}(), "vector" => String[])
    for (kind, key, other) in zip(kinds, keys, names)
        kind == "std" && (out["std"] = other)
        kind == "quantile" && (out["quantiles"][parse(Float64, key)] = other)
        kind == "derivative" && (out["derivatives"][key] = other)
        kind == "vector" && push!(out["vector"], other)
    end
    return out
end

# --- copies between files --------------------------------------------------------------

"""
    Gamut.append!(dst, src)

Adds the rows of `src` to `dst` in place and returns how many: new ids
continuing dst's, tables merged by name. Both need the same declarations
(bounds may differ), the same mesh, and one geometry for a group member
found in both; everything is checked before the first row is written.
"""
function append!(dst::AbstractString, src::AbstractString)
    n = Ref{Int64}(0)
    @mes gamut_append (Cstring, Cstring, Ref{Int64}) cs(dst) cs(src) n
    return Int(n[])
end

"""
    Gamut.extract(src, dst, rows)

The selected rows of `src` (1-based positions or a range) as a new file
`dst`: ids kept, every table whole, a changing mesh's instances reduced to
those the rows use.
"""
function extract(src::AbstractString, dst::AbstractString, rows)
    r = selection(rows, "rows")
    rsel = Ref(r.sel)
    rk = r.keep
    GC.@preserve rk begin
        @mes gamut_extract (Cstring, Cstring, Ref{CSel}) cs(src) cs(dst) rsel
    end
    return nothing
end

"""
    Gamut.write_copy(src, dst)

`src` rewritten as `dst` with the default layout (chunks, compression),
keeping its identity (file_id, created).
"""
write_copy(src::AbstractString, dst::AbstractString) =
    (@mes gamut_write_copy (Cstring, Cstring) cs(src) cs(dst); nothing)

# --- validation -------------------------------------------------------------------------

struct Finding
    rule::String
    severity::String
    path::String
    message::String
end

"""    Gamut.validate(path)    the findings of spec section 16 (empty when the file is valid)."""
function validate(path::AbstractString)
    out = Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_validate (Cstring, Ref{Ptr{Cvoid}}) cs(path) out
    r = out[]
    try
        n = ccall(sym(:gamut_report_count), Int64, (Ptr{Cvoid},), r)
        findings = Finding[]
        for i in 0:n-1
            rule, sev, p, msg = (Ref{Cstring}() for _ in 1:4)
            ccall(sym(:gamut_report_get), Cint, (Ptr{Cvoid}, Int64, Ref{Cstring}, Ref{Cstring}, Ref{Cstring}, Ref{Cstring}), r, i, rule, sev, p, msg)
            push!(findings, Finding(unsafe_string(rule[]), unsafe_string(sev[]), unsafe_string(p[]), unsafe_string(msg[])))
        end
        return findings
    finally
        ccall(sym(:gamut_report_free), Cvoid, (Ptr{Cvoid},), r)
    end
end

# --- model data and models ---------------------------------------------------------------

function to_tree(numbers::AbstractDict)
    out = Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_tree_new (Ref{Ptr{Cvoid}},) out
    t = out[]
    try
        fill_tree(t, "", numbers)
    catch
        ccall(sym(:gamut_tree_free), Cvoid, (Ptr{Cvoid},), t)
        rethrow()
    end
    return t
end

function fill_tree(t, prefix, d)
    for (k, v) in d
        key = isempty(prefix) ? string(k) : "$prefix/$k"
        if v === nothing
            @mes gamut_tree_set_null (Ptr{Cvoid}, Cstring) t cs(key)
        elseif v isa Bool
            @mes gamut_tree_set_bool (Ptr{Cvoid}, Cstring, Cint) t cs(key) (v ? 1 : 0)
        elseif v isa Integer
            @mes gamut_tree_set_int (Ptr{Cvoid}, Cstring, Int64) t cs(key) Int64(v)
        elseif v isa Real
            @mes gamut_tree_set_float (Ptr{Cvoid}, Cstring, Cdouble) t cs(key) Float64(v)
        elseif v isa AbstractString
            @mes gamut_tree_set_string (Ptr{Cvoid}, Cstring, Cstring) t cs(key) cs(v)
        elseif v isa AbstractDict
            @mes gamut_tree_set_dict (Ptr{Cvoid}, Cstring) t cs(key)
            fill_tree(t, key, v)
        elseif v isa AbstractArray && eltype(v) <: AbstractString
            strs, ptrs = cstrings(vec(v))
            GC.@preserve strs begin
                @mes gamut_tree_set_strings (Ptr{Cvoid}, Cstring, Ptr{Ptr{UInt8}}, Int64) t cs(key) ptrs length(ptrs)
            end
        elseif v isa AbstractArray
            a = eltype(v) <: Bool ? Int8.(v) : eltype(v) <: Union{Int32,Int64,Float64} ? v :
                eltype(v) <: Integer ? Int64.(v) :
                throw(GamutError("E18", "$key: model data holds Bool, Int32, Int64 and Float64 arrays"))
            buf = c_order(a)
            shape = Int64[size(a)...]
            GC.@preserve buf begin
                @mes gamut_tree_set_array (Ptr{Cvoid}, Cstring, Cint, Ptr{Cvoid}, Int64, Cint, Ptr{Int64}) t cs(key) DTYPE[eltype(buf)] pointer(buf) length(buf) ndims(a) shape
            end
        else
            throw(GamutError("E18", "$key: $(typeof(v)) is not model data"))
        end
    end
end

function from_tree(t, prefix="")
    out = Dict{String,Any}()
    keys = Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_tree_keys (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}) t cs(prefix) keys
    for k in take_strings(keys[])
        key = isempty(prefix) ? k : "$prefix/$k"
        kind = Ref{Cint}(0)
        @mes gamut_tree_kind (Ptr{Cvoid}, Cstring, Ref{Cint}) t cs(key) kind
        if kind[] == 0
            out[k] = nothing
        elseif kind[] in (1, 2, 3)
            i, f = Ref{Int64}(0), Ref{Cdouble}(0)
            @mes gamut_tree_scalar (Ptr{Cvoid}, Cstring, Ref{Int64}, Ref{Cdouble}) t cs(key) i f
            out[k] = kind[] == 1 ? i[] != 0 : kind[] == 2 ? i[] : f[]
        elseif kind[] in (4, 6)
            s = Ref{Ptr{Cvoid}}(C_NULL)
            @mes gamut_tree_strings (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}) t cs(key) s
            v = take_strings(s[])
            out[k] = kind[] == 4 ? v[1] : v
        elseif kind[] == 7
            out[k] = from_tree(t, key)
        else
            dtype, rank = Ref{Cint}(0), Ref{Cint}(0)
            shape = zeros(Int64, 8)
            @mes gamut_tree_array_info (Ptr{Cvoid}, Cstring, Ref{Cint}, Ref{Cint}, Ptr{Int64}, Cint) t cs(key) dtype rank shape length(shape)
            T = Dict(2 => Int8, 3 => Int32, 4 => Int64, 6 => Float64)[dtype[]]
            dims = shape[1:rank[]]
            buf = Vector{T}(undef, prod(dims; init=1))
            @mes gamut_tree_array (Ptr{Cvoid}, Cstring, Ptr{Cvoid}, Int64) t cs(key) pointer(buf) sizeof(buf)
            a = from_c_order(buf, dims)
            out[k] = T == Int8 ? Bool.(a) : a
        end
    end
    return out
end

"""
    Gamut.Nearest(columns, lower, upper, x, outputs)

The built-in model: for each input row, the outputs of the closest stored
point (spec section 7.5), evaluated by the core so every language gets the
same answers. `x` is points × columns; each output has points first.
"""
struct Nearest
    columns::Vector{String}
    lower::Vector{Float64}
    upper::Vector{Float64}
    x::Matrix{Float64}
    outputs::Dict{String,Array{Float64}}
    function Nearest(columns, lower, upper, x, outputs)
        cols = String[string(c) for c in columns]
        m = new(cols, Float64.(collect(lower)), Float64.(collect(upper)),
                reshape(Float64.(collect(x)), :, length(cols)),
                Dict{String,Array{Float64}}(string(k) => Float64.(v) for (k, v) in pairs_of(outputs)))
        nearest_check(save(m))
        return m
    end
end
function nearest_check(numbers)
    t = to_tree(numbers)
    try
        @mes gamut_nearest_check (Ptr{Cvoid},) t
    finally
        ccall(sym(:gamut_tree_free), Cvoid, (Ptr{Cvoid},), t)
    end
end
model_type(::Nearest) = "nearest"
save(m::Nearest) = Dict{String,Any}("columns" => m.columns, "lower" => m.lower, "upper" => m.upper,
                                    "x" => m.x, "outputs" => Dict{String,Any}(m.outputs))
# Numbers from a file are checked before any is looked up: a damaged or
# foreign file may lack one (E17).
load_nearest(n) = (nearest_check(n); Nearest(n["columns"], n["lower"], n["upper"], n["x"], n["outputs"]))

function call(m::Nearest, inputs, wanted)
    missing = [c for c in m.columns if !haskey(inputs, c)]
    isempty(missing) || throw(GamutError("", "nearest needs the inputs $(join(missing, ", "))"))
    cols = [Vector{Float64}(vec(inputs[c])) for c in m.columns]
    nrows = !isempty(cols) ? length(cols[1]) : isempty(inputs) ? 0 : length(first(values(inputs)))
    t = to_tree(save(m))
    out = Dict{String,Any}()
    try
        strs, names = cstrings(m.columns)
        ptrs = Ptr{Cdouble}[pointer(c) for c in cols]
        lengths = Int64[length(c) for c in cols]
        for w in wanted
            output, kind = w[1], w[2]
            kind == "values" || throw(GamutError("", "nearest gives values only, not $kind"))
            per = Ref{Int64}(0)
            @mes gamut_nearest_output_size (Ptr{Cvoid}, Cstring, Ref{Int64}) t cs(output) per
            buf = Vector{Float64}(undef, nrows * per[])
            GC.@preserve strs cols begin
                @mes gamut_nearest_call (Ptr{Cvoid}, Ptr{Ptr{UInt8}}, Ptr{Ptr{Cdouble}}, Ptr{Int64}, Cint, Int64, Cstring, Ptr{Cdouble}, Int64) t names ptrs lengths length(cols) nrows cs(output) buf length(buf)
            end
            shape = size(m.outputs[output])[2:end]
            get!(out, output, Dict{String,Any}())["values"] =
                isempty(shape) ? buf : from_c_order(buf, (nrows, shape...))
        end
    finally
        ccall(sym(:gamut_tree_free), Cvoid, (Ptr{Cvoid},), t)
    end
    return out
end

"""    add_model!(model_file, id, model, inputs; repr="")    a model and the inputs it reads."""
function add_model!(s::Study, id, model, inputs; repr="")
    t = to_tree(save(model))
    try
        strs, ptrs = cstrings(inputs)
        GC.@preserve strs begin
            @mes gamut_add_model (Ptr{Cvoid}, Cstring, Cstring, Ptr{Ptr{UInt8}}, Int64, Ptr{Cvoid}, Cstring) handle(s) cs(id) cs(model_type(model)) ptrs length(ptrs) t cs(repr)
        end
    finally
        ccall(sym(:gamut_tree_free), Cvoid, (Ptr{Cvoid},), t)
    end
end

const LOADERS = Dict{String,Function}("nearest" => load_nearest)

"""
    Gamut.evaluate(model_path, inputs; path=nothing, coordinates=nothing)

Evaluates a model file on a table of inputs (spec section 7.4) and returns
the resulting data file open to read. `inputs` maps each parameter to
values and each label to names from the model file's table, all of one
length. Without `path` the file is temporary, removed on close.
"""
function evaluate(model_path::AbstractString, inputs; path=nothing, coordinates=nothing)
    open(model_path) do m
        params, labels = names(m, "parameters"), names(m, "labels")
        given = Dict{String,Any}(pairs_of(inputs))
        n = isempty(given) ? 0 : length(first(values(given)))
        out_path = path === nothing ? tempname() * ".gamut" : String(path)
        # The core checks the inputs, runs the built-in models and writes the
        # answer; this layer converts values and calls the registered types.
        ev = Ref{Ptr{Cvoid}}(C_NULL)
        @mes gamut_evaluation_begin (Ptr{Cvoid}, Int64, Cstring, Ref{Ptr{Cvoid}}) handle(m) n cs(out_path) ev
        try
            for (name, v) in given
                if name in labels
                    strs, ptrs = cstrings(String[string(x) for x in v])
                    GC.@preserve strs @mes gamut_evaluation_names (Ptr{Cvoid}, Cstring, Ptr{Ptr{UInt8}}, Int64) ev[] cs(name) ptrs length(ptrs)
                elseif !(name in params)    # the core refuses the name (E2) before its values
                    @mes gamut_evaluation_values (Ptr{Cvoid}, Cstring, Cint, Ptr{Cvoid}, Int64) ev[] cs(name) 6 C_NULL 0
                else
                    int64 = get(describe(m, name), "dtype", "") == "int64"
                    col = int64 ? Vector{Int64}(vec(v)) : Vector{Float64}(float64_exactly(vec(v), name))
                    @mes gamut_evaluation_values (Ptr{Cvoid}, Cstring, Cint, Ptr{Cvoid}, Int64) ev[] cs(name) (int64 ? 4 : 6) col length(col)
                end
            end
            if coordinates !== nothing
                pts = c_order(float64_exactly(coordinates, "coordinates"))
                @mes gamut_evaluation_coordinates (Ptr{Cvoid}, Cint, Ptr{Cvoid}, Int64) ev[] 6 pts length(pts)
            end
            w, ids = Ref{Ptr{Cvoid}}(C_NULL), Ref{Ptr{Cvoid}}(C_NULL)
            @mes gamut_evaluation_ready (Ptr{Cvoid}, Ref{Ptr{Cvoid}}, Ref{Ptr{Cvoid}}) ev[] w ids
            found, models = take_strings(w[]), take_strings(ids[])
            for finding in found
                @warn finding
            end
            for id in models
                run_model(m, ev[], id)
            end
            @mes gamut_evaluation_finish (Ptr{Cvoid},) ev[]
        finally
            ccall(sym(:gamut_evaluation_free), Cvoid, (Ptr{Cvoid},), ev[])
        end
        r = open(out_path)
        r.remove_on_close = path === nothing
        return r
    end
end

# An input as a model reads it, from the evaluation.
function evaluation_input(ev::Ptr{Cvoid}, name)
    code, rank, shape = Ref{Cint}(0), Ref{Cint}(0), zeros(Int64, 3)
    @mes gamut_evaluation_input_info (Ptr{Cvoid}, Cstring, Ref{Cint}, Ref{Cint}, Ptr{Int64}, Cint) ev cs(name) code rank shape 3
    dims = shape[1:rank[]]
    buf = Vector{code[] == 4 ? Int64 : Float64}(undef, prod(dims))
    @mes gamut_evaluation_input (Ptr{Cvoid}, Cstring, Ptr{Cvoid}, Int64) ev cs(name) buf sizeof(buf)
    return from_c_order(buf, dims)
end

# Calls one model of a registered type with what it reads, and gives the
# evaluation each answer it is asked for.
function run_model(m::Study, ev::Ptr{Cvoid}, id)
    d = declared(m, "models/$id")
    loader = get(LOADERS, d["type"], nothing)
    loader === nothing && throw(GamutError("", "the model $id is of type $(repr(d["type"])), " *
                                                "whose software is not registered here"))
    model = loader(model_numbers(m, id))
    reads = split(d["inputs"])
    o, k, y = Ref{Ptr{Cvoid}}(C_NULL), Ref{Ptr{Cvoid}}(C_NULL), Ref{Ptr{Cvoid}}(C_NULL)
    @mes gamut_evaluation_requests (Ptr{Cvoid}, Cstring, Ref{Ptr{Cvoid}}, Ref{Ptr{Cvoid}}, Ref{Ptr{Cvoid}}) ev cs(id) o k y
    outputs, kinds, keys_ = take_strings(o[]), take_strings(k[]), take_strings(y[])
    wanted = Any[kind == "quantile" ? (out, kind, parse(Float64, key)) :
                 kind == "derivative" ? (out, kind, key) : (out, kind)
                 for (out, kind, key) in zip(outputs, kinds, keys_)]
    got = call(model, Dict(String(r) => evaluation_input(ev, r) for r in reads), wanted)
    for ((out, kind, key), ask) in zip(zip(outputs, kinds, keys_), wanted)
        record = get(got, out, nothing)
        record === nothing && throw(GamutError("", "the model $id gave no output $out"))
        v = kind == "values" ? get(record, "values", nothing) :
            kind == "std" ? get(record, "std", nothing) :
            kind == "quantile" ? get(get(record, "quantiles", Dict()), ask[3], nothing) :
            get(get(record, "derivatives", Dict()), key, nothing)
        v === nothing && throw(GamutError("", "the model $id gave no $kind for $out"))
        flat = numbers(c_order(v))      # as given: the core converts it as written values
        GC.@preserve flat @mes gamut_evaluation_answer (Ptr{Cvoid}, Cstring, Cstring, Cstring, Cstring, Cint, Ptr{Cvoid}, Int64) ev cs(id) cs(out) cs(kind) cs(key) DTYPE[eltype(flat)] pointer(flat) length(flat)
    end
end

end # module
