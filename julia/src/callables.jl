# The callable protocol of section 10, and the `affine` reference
# callable of section 27.
#
# A callable is exactly four things and nothing more: call, to_dict,
# from_dict, and an optional one-line repr.  Everything else it knows
# lives inside its own dictionary and is its own business.

"""
    Prediction(mean; uncertainty = nothing, level = nothing, method = nothing)

What a callable returns for one output (section 10).  `mean` is the
point prediction, held the way this package holds every array: the
Julia axes reversed from the file's, so a scalar slot's mean is a
vector over rows and an array slot's is (component, node, row).
`uncertainty` is optional: a band (section 9), the half-width of the
interval around the mean at coverage `level`, of the same shape, made
as `method` says.  The three go together, and a band missing its level
or its method is refused here rather than in a file.
"""
struct Prediction
    mean::Array{Float64}
    uncertainty::Union{Nothing,Array{Float64}}
    level::Union{Nothing,Float64}
    method::Union{Nothing,String}

    function Prediction(mean; uncertainty = nothing, level = nothing,
                        method = nothing)
        m = convert(Array{Float64}, mean)
        if uncertainty === nothing
            (level === nothing && method === nothing) ||
                throw(MestraError(nothing,
                    "level and method go with an uncertainty; a " *
                    "prediction without one has neither (section 10)"))
            return new(m, nothing, nothing, nothing)
        end
        u = convert(Array{Float64}, uncertainty)
        size(u) == size(m) || throw(MestraError(nothing,
            "a band has the shape of its mean; the mean is $(size(m)) " *
            "and the band $(size(u))"))
        (level isa Real && 0 < level < 1) || throw(MestraError(nothing,
            "a band states the coverage it claims as level in (0, 1); a " *
            "1.96-sigma Gaussian band is 0.95"))
        (method isa AbstractString && !isempty(method)) ||
            throw(MestraError(nothing,
                "a band says how it was made; give method one sentence"))
        any(x -> x < 0, u) && throw(MestraError(nothing,
            "a band is a half-width and is never negative"))
        return new(m, u, Float64(level), String(method))
    end
end

"""True when the record carries a band."""
has_uncertainty(p::Prediction) = p.uncertainty !== nothing

"""
    Callable

Keys in, predictions out.  A type conforming to the protocol defines

    (c::MyCallable)(keys)        -> Dict{String,Prediction}
    Mestra.to_dict(c)            -> Dict{String,Any}
    Mestra.from_dict(::Type{MyCallable}, d) -> MyCallable

and registers itself with `register_callable!("my type", MyCallable)`.
`Base.show(io, c)` is optional and is the one-line `repr` the file may
carry.

`call` returns one `Prediction` per output the callable serves, named
by the value of the slot's `output` attribute, whose mean is shaped as
the slot would be stored, (row, node | cell, component) for an array
and (row) for a scalar, and which carries a band when the model has
one.  How the band was computed is the model's business; what it
claims is on the record.
"""
abstract type Callable end

const CALLABLE_REGISTRY = Dict{String,Type}()

"""
    register_callable!(type, T)

Make `from_dict` dispatch on the `type` string a file carries.
"""
function register_callable!(type::AbstractString, T::Type)
    CALLABLE_REGISTRY[String(type)] = T
    return T
end

"""The Julia type registered for a `type` string, or nothing."""
callable_type(type::AbstractString) =
    get(CALLABLE_REGISTRY, String(type), nothing)

"""
    to_dict(c::Callable) -> Dict{String,Any}

The nested dictionary that fully represents the callable.  `type` and
`repr` are the container's attributes and are never in it (section 25).
"""
function to_dict end

"""
    from_dict(T, dict) -> Callable

The inverse of `to_dict`, dispatched on the `type` string through the
registry.
"""
function from_dict end

"""
    build_callable(ref::CallableRef) -> Callable

Turn what the file carries into a callable, if this reader owns the
type.  A reader that does not own it may still copy the dictionary and
must not interpret it (section 12), which is what `ref.dict` is for.
"""
function build_callable(ref::CallableRef)
    ref.type === nothing && throw(MestraError("E15",
        "callable $(ref.id) has no `type` attribute"))
    T = callable_type(ref.type)
    T === nothing && throw(MestraError(nothing,
        "no callable registered for type \"$(ref.type)\"; the dictionary " *
        "is opaque to this reader and must not be interpreted. To " *
        "evaluate it, load the package that provides the type, which " *
        "registers it, or call Mestra.register_callable! (the file's " *
        "writer attribute names the tool that wrote it)"))
    return from_dict(T, ref.dict)
end

# -------------------------------------------------------- keys tables

"""
    KeysTable

The keys table of section 26 is, in Julia, a `Dict{String,Vector{Float64}}`
of key name to column, with every column the same length and the row
order the evaluation order: output row i is the result for table row i.
A key with role `id` may hold a `Vector{String}` instead, so the
general element type is `AbstractVector`.

`normalise_keys` also accepts a `NamedTuple` of columns and a
`(matrix, names)` pair, where the matrix is (rows, keys) and the names
are in the file's key order, so that a caller may pass whichever is to
hand.
"""
const KeysTable = AbstractDict{String,<:AbstractVector}

normalise_keys(t::AbstractDict) =
    Dict{String,AbstractVector}(String(k) => v for (k, v) in t)

normalise_keys(t::NamedTuple) =
    Dict{String,AbstractVector}(String(k) => v for (k, v) in pairs(t))

function normalise_keys(t::Tuple{AbstractMatrix,Any})
    m, names = t
    size(m, 2) == length(names) || throw(MestraError(nothing,
        "a keys matrix of $(size(m, 2)) columns with $(length(names)) names"))
    return Dict{String,AbstractVector}(String(names[j]) => collect(m[:, j])
                                       for j in 1:length(names))
end

function keys_table_rows(t::AbstractDict)
    isempty(t) && return 0
    lengths = unique(length.(collect(Base.values(t))))
    length(lengths) == 1 || throw(MestraError(nothing,
        "the columns of a keys table must all be the same length"))
    return lengths[1]
end

# ------------------------------------------------------------- affine

"""One output of an `affine` callable: y = A x + b, reshaped to
`shape` in C order (section 27), and, when the output carries a band,
a constant `uncertainty` the same in every row with its `level` and
`method`: all three or none."""
struct AffineOutput
    A::Matrix{Float64}      # (n_out_flat, n_keys)
    b::Vector{Float64}      # (n_out_flat,)
    shape::Vector{Int64}    # the slot's dimensions after the row one
    uncertainty::Union{Nothing,Vector{Float64}}   # (n_out_flat,)
    level::Union{Nothing,Float64}
    method::Union{Nothing,String}
end

AffineOutput(A, b, shape) = AffineOutput(A, b, shape, nothing, nothing, nothing)

has_band(o::AffineOutput) = o.uncertainty !== nothing

"""Section 27: a band is all three of uncertainty, level and method, the
uncertainty is one value per output element, and the level is a
coverage."""
function check_band(name, o::AffineOutput)
    parts = (o.uncertainty !== nothing) + (o.level !== nothing) +
            (o.method !== nothing)
    parts == 0 && return o
    parts == 3 || throw(MestraError(nothing,
        "a band on the affine output `$(name)` is all three of " *
        "uncertainty, level and method"))
    length(o.uncertainty) == n_out_flat(o) || throw(MestraError(nothing,
        "the affine output `$(name)` has an uncertainty of " *
        "$(length(o.uncertainty)) values where its shape needs " *
        "$(n_out_flat(o))"))
    0 < o.level < 1 || throw(MestraError(nothing,
        "the affine output `$(name)` has a level that is not a coverage " *
        "in (0, 1)"))
    isempty(o.method) && throw(MestraError(nothing,
        "the affine output `$(name)` has a method that is not one sentence"))
    return o
end

"""
    Affine(keys, outputs)

The one callable type this package defines, so that the protocol, the
codec and evaluation can be conformance tested with no proprietary
model.  `keys` is the declared key order and `outputs` maps the value
of a slot's `output` attribute to its A, b and shape.
"""
struct Affine <: Callable
    keys::Vector{String}
    outputs::Dict{String,AffineOutput}

    function Affine(keys, outputs)
        for (name, o) in outputs
            check_band(name, o)
        end
        return new(keys, outputs)
    end
end

Base.show(io::IO, c::Affine) =
    print(io, "affine(", join(c.keys, ", "), " -> ",
          join(sort(collect(keys(c.outputs)), by = codeunits), ", "), ")")

n_out_flat(o::AffineOutput) = isempty(o.shape) ? 1 : Int(prod(o.shape))

"""
    (c::Affine)(table) -> Dict{String,Prediction}

Evaluate every output on a keys table.  The dot product is accumulated
over the keys in the declared key order and b is added last, with no
fused multiply-add (section 27).  The loop below is
written out for that reason: it uses Float64 throughout, it never
calls `muladd`, and it carries no `@simd` or `@fastmath`, either of
which would let the compiler reassociate or contract it.  Julia's
floating-point semantics forbid the compiler from fusing `acc + a * x`
into an FMA on its own, so the order in the source is the order that
runs.
"""
function (c::Affine)(table)
    t = normalise_keys(table)
    nrows = keys_table_rows(t)
    x = Matrix{Float64}(undef, nrows, length(c.keys))
    for (j, k) in pairs(c.keys)
        haskey(t, k) || throw(MestraError(nothing,
            "the keys table has no column `$(k)`, which this callable " *
            "declares"))
        col = t[k]
        length(col) == nrows || throw(MestraError(nothing,
            "column `$(k)` has $(length(col)) rows, not $(nrows)"))
        for i in 1:nrows
            x[i, j] = Float64(col[i])
        end
    end
    out = Dict{String,Prediction}()
    for (name, o) in c.outputs
        size(o.A, 2) == length(c.keys) || throw(MestraError(nothing,
            "output `$(name)` has an A of $(size(o.A, 2)) columns for " *
            "$(length(c.keys)) keys"))
        nf = n_out_flat(o)
        size(o.A, 1) == nf && length(o.b) == nf || throw(MestraError(nothing,
            "output `$(name)` has A and b that do not match its shape"))
        y = Matrix{Float64}(undef, nrows, nf)
        for r in 1:nrows
            for i in 1:nf
                acc = 0.0
                for k in 1:length(c.keys)
                    acc = acc + o.A[i, k] * x[r, k]
                end
                acc = acc + o.b[i]
                y[r, i] = acc
            end
        end
        mean = reshape_output(y, o.shape)
        if has_band(o)
            # The band is a constant, repeated for each row, so that
            # evaluation stays exact (section 27).
            u = repeat(reshape(o.uncertainty, 1, nf), nrows, 1)
            out[name] = Prediction(mean; uncertainty = reshape_output(u, o.shape),
                                   level = o.level, method = o.method)
        else
            out[name] = Prediction(mean)
        end
    end
    return out
end

"""Give a (rows, n_out_flat) block the slot's stored shape.  The
result is held the way this package holds every array: the Julia axes
reversed from the file's, so its linear memory is the file's order."""
function reshape_output(y::Matrix{Float64}, shape::Vector{Int64})
    nrows = size(y, 1)
    cdims = vcat(nrows, Int.(shape))
    # y is (row, flat) with flat contiguous in C order within a row,
    # which is the file's order, so the transpose is already it.
    flat = vec(permutedims(y, (2, 1)))
    return reshape(flat, reverse(cdims)...)
end

function output_dict(o::AffineOutput)
    d = Dict{String,Any}("A" => copy(o.A), "b" => copy(o.b),
                         "shape" => copy(o.shape))
    if has_band(o)
        # Section 25: the band is a dataset, and the level and the
        # method are attributes on the entry.
        d["uncertainty"] = copy(o.uncertainty)
        d["level"] = o.level
        d["method"] = o.method
    end
    return d
end

to_dict(c::Affine) = Dict{String,Any}(
    "keys" => copy(c.keys),
    "outputs" => Dict{String,Any}(name => output_dict(o)
                                  for (name, o) in c.outputs))

const AFFINE_OUTPUT_KEYS = Set(["A", "b", "shape", "uncertainty", "level",
                                "method"])

function from_dict(::Type{Affine}, d::AbstractDict)
    extra = setdiff(Set(keys(d)), Set(["keys", "outputs"]))
    isempty(extra) || throw(MestraError(nothing,
        "an `affine` dictionary with keys section 27 does not define: " *
        join(sort(collect(extra)), ", ")))
    haskey(d, "keys") && haskey(d, "outputs") || throw(MestraError(nothing,
        "an `affine` dictionary needs `keys` and `outputs`"))
    ks = String[String(k) for k in d["keys"]]
    outs = Dict{String,AffineOutput}()
    for (name, entry) in d["outputs"]
        e = setdiff(Set(keys(entry)), AFFINE_OUTPUT_KEYS)
        isempty(e) || throw(MestraError(nothing,
            "an `affine` output with keys section 27 does not define: " *
            join(sort(collect(e)), ", ")))
        A = Float64.(entry["A"])
        ndims(A) == 2 || throw(MestraError(nothing,
            "an `affine` A must be two-dimensional"))
        outs[String(name)] = AffineOutput(
            A, Float64.(vec(entry["b"])), Int64.(vec(entry["shape"])),
            haskey(entry, "uncertainty") ?
                Float64.(vec(entry["uncertainty"])) : nothing,
            haskey(entry, "level") ? Float64(entry["level"]) : nothing,
            haskey(entry, "method") ? String(entry["method"]) : nothing)
    end
    return Affine(ks, outs)
end

"""
    affine(keys, outputs) -> Affine

Build an `affine` callable from plain arrays, for example

    affine(["mach", "alpha"],
           Dict("cl" => (A = [2.0 0.1], b = [0.05], shape = Int64[])))

An output with a band gives `uncertainty`, `level` and `method` too.
"""
function affine(keys, outputs::AbstractDict)
    outs = Dict{String,AffineOutput}()
    for (name, o) in outputs
        A = Float64.(o.A)
        outs[String(name)] = AffineOutput(
            ndims(A) == 2 ? A : reshape(A, 1, length(A)),
            Float64.(vec(o.b)), Int64.(vec(o.shape)),
            hasproperty(o, :uncertainty) ? Float64.(vec(o.uncertainty)) :
                nothing,
            hasproperty(o, :level) ? Float64(o.level) : nothing,
            hasproperty(o, :method) ? String(o.method) : nothing)
    end
    return Affine(String[String(k) for k in keys], outs)
end
