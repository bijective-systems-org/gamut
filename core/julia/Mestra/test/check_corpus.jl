# Holds the Julia package to the corpus written by core/corpus/generate.py:
# the same cases and expected answers as the Python and MATLAB checkers.
#   julia check_corpus.jl CORPUS_DIR     (with JSON and Mestra loadable)
using JSON
using Mestra

# A nested JSON list as an array in logical order (first index outermost).
function nested(v, ::Type{T}) where {T}
    v isa AbstractVector || return T(v)
    isempty(v) && return T[]
    v[1] isa AbstractVector || return T[T(x) for x in v]
    parts = [nested(x, T) for x in v]
    return permutedims(cat(parts...; dims=ndims(parts[1]) + 1), (ndims(parts[1]) + 1, 1:ndims(parts[1])...))
end

const DTYPES = Dict("float64" => Float64, "float32" => Float32, "int64" => Int64,
                    "int32" => Int32, "uint8" => UInt8, "int8" => Int8)

positions(x) = x === nothing ? nothing : Int.(x) .+ 1

function probe(path, p)
    if haskey(p, "evaluate")
        inputs = Dict(k => (v[1] isa AbstractString ? String.(v) : Float64.(v)) for (k, v) in p["evaluate"])
        out = Mestra.evaluate(path, inputs)
        try
            got = Mestra.get_scalar(out, p["scalar"])
            return got == Float64.(p["values"]) ? nothing : "evaluate $(p["scalar"]): $got != $(p["values"])"
        finally
            close(out)
        end
    end
    Mestra.open(path) do f
        if haskey(p, "info")
            got = getproperty(f, Symbol(p["info"]))
            return got == p["value"] ? nothing : "$(p["info"]): $(repr(got)) != $(repr(p["value"]))"
        elseif haskey(p, "label")
            got = Mestra.get_label(f, p["label"]; rows=positions(p["rows"]))
            return got == p["names"] ? nothing : "label $(p["label"]): $got != $(p["names"])"
        elseif haskey(p, "select")
            got = Mestra.select(f, p["select"])
            return got == positions(p["positions"]) ? nothing : "select: $got != $(p["positions"])"
        end
        T = DTYPES[p["dtype"]]
        got = Mestra.read(f, p["read"], positions(get(p, "rows", nothing)),
                          positions(get(p, "sites", nothing)), T; squeeze=false)
        want = nested(p["values"], T)
        size(got) == size(want) || return "read $(p["read"]): shape $(size(got)) != $(size(want))"
        reinterpret(UInt8, vec(collect(got))) == reinterpret(UInt8, vec(collect(want))) ||
            return "read $(p["read"]): $got != $want"
        return nothing
    end
end

function hostile(path, e)
    try
        Mestra.open(path) do f
            Mestra.names(f, "parameters")
            for r in get(e, "reads", [])
                try
                    Mestra.get_label(f, r["label"])
                catch x
                    x isa MestraError || rethrow()
                end
            end
        end
        haskey(e, "refused") && return "opened; expected refusal $(e["refused"])"
    catch x
        x isa MestraError || return "raised $(typeof(x)): $x"
        haskey(e, "refused") && x.rule != e["refused"] &&
            return "refused with $(repr(x.rule)), expected $(e["refused"])"
    end
    return nothing
end

function main(corpus)
    expected = JSON.parsefile(joinpath(corpus, "expected.json"); allownan=true)
    failures = String[]
    counts = Dict("valid" => 0, "rules" => 0, "hostile" => 0)
    for name in sort(collect(keys(expected)))
        e = expected[name]
        path = joinpath(corpus, "$name.mes")
        counts[e["group"]] += 1
        findings = try
            Mestra.validate(path)
        catch x
            push!(failures, "$name: validate raised $x")
            continue
        end
        found = Set(f.rule for f in findings)
        if e["group"] == "valid"
            isempty(findings) || push!(failures, "$name: a valid file drew " *
                                       join(("$(f.rule) $(f.path): $(f.message)" for f in findings), "; "))
            for p in get(e, "probes", [])
                why = try
                    probe(path, p)
                catch x
                    "probe raised $x"
                end
                why === nothing || push!(failures, "$name: $why")
            end
        else
            missing_ = [r for r in e["rules"] if !(r in found)]
            isempty(missing_) || push!(failures, "$name: expected $missing_, found $(sort(collect(found)))")
            if e["group"] == "hostile"
                why = hostile(path, e)
                why === nothing || push!(failures, "$name: $why")
            end
        end
    end
    total = sum(values(counts))
    failed = length(unique(first(split(f, ":")) for f in failures))
    println("$total cases ($(counts["valid"]) valid, $(counts["rules"]) rule, $(counts["hostile"]) " *
            "hostile): $(total - failed) hold")
    foreach(f -> println("  FAIL ", f), failures)
    return isempty(failures) ? 0 : 1
end

exit(main(ARGS[1]))
