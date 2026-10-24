# The Julia package over the shared core: each kind of study written with
# the package and read back with it, the refusals, and the built-in model.
using Test
using Gamut

function grid(nx, ny)
    # Node k = j * nx + i at (i, j), one row per node.
    pts = zeros(nx * ny, 2)
    for j in 0:ny-1, i in 0:nx-1
        pts[j * nx + i + 1, :] = [i, j]
    end
    conn = Int64[]
    for j in 0:ny-2, i in 0:nx-2
        a = j * nx + i
        append!(conn, (a, a + 1, a + nx + 1, a + nx))
    end
    n = (nx - 1) * (ny - 1)
    return pts, (fill(UInt8(9), n), collect(Int64, 0:4:4n), conn)
end

mktempdir() do tmp
    @testset "a table, one run at a time" begin
        p = joinpath(tmp, "polar.gamut")
        Gamut.create(p; writer="tests",
                      parameters=Dict("mach" => (units="1", role="condition"), "alpha" => "degree"),
                      labels=Dict("status" => (role="status", categories=["converged", "failed"])),
                      scalars=Dict("cl" => "1", "cd" => "1"),
                      constants=Dict("s_ref" => (12.5, "m2")), title="Wing A polar") do s
            for i in 0:19
                id = Gamut.add_run!(s, Dict("mach" => 0.3 + 0.01i, "alpha" => Float64(i % 5),
                                             "status" => i == 7 ? "failed" : "converged",
                                             "cl" => 0.1 * (i % 5), "cd" => 0.01f0))
                @test id == i
            end
        end
        Gamut.open(p) do f
            @test f.kind == "data" && f.type == "table" && f.row_count == 20
            @test Gamut.describe(f)["title"] == "Wing A polar"
            @test Gamut.get_scalar(f, "cl"; rows=1:3) ≈ [0.0, 0.1, 0.2]
            @test Gamut.get_label(f, "status"; rows=8) == "failed"       # 1-based
            @test Gamut.get_constant(f, "s_ref") == 12.5
            @test eltype(Gamut.get_scalar(f, "cd")) == Float32             # as given
            @test Gamut.get_row_ids(f) == collect(0:19)
            @test Gamut.select(f, "status == failed") == [8]
            t = Gamut.table(f)
            @test t["status"][8] == "failed"
        end
    end

    @testset "a sweep on one mesh, region reads" begin
        p = joinpath(tmp, "sweep.gamut")
        pts, cells = grid(4, 3)
        prun = reshape(Float32.(0:6*12-1), 12, 6)'          # runs × nodes
        Gamut.create(p; writer="tests", mesh="shared", per="fixed",
                      coordinates=(units="m", axes=2),
                      parameters=Dict("mach" => "1"),
                      mesh_labels=Dict("zone" => (at="cell", categories=["inlet", "wall"])),
                      fields=Dict("p" => (units="Pa", at="node"),
                                  "u" => (units="m s-1", at="cell", vector="velocity", axis="x"))) do s
            Gamut.set_mesh!(s; points=pts, cells=cells, labels=Dict("zone" => [0, 0, 0, 1, 1, 1]))
            Gamut.add_runs!(s, Dict("mach" => collect(0.1:0.1:0.6));
                             fields=Dict("p" => prun, "u" => zeros(6, 6)))
        end
        Gamut.open(p) do f
            @test f.type == "shared" && f.row_count == 6
            @test Gamut.get_field(f, "p") == prun
            @test Gamut.get_field(f, "p"; rows=2:3, nodes=[1, 5, 12]) == prun[2:3, [1, 5, 12]]
            @test Gamut.get_field(f, "p"; rows=4) == prun[4, :]
            @test Gamut.get_points(f) == pts
            types, offsets, conn = Gamut.get_cells(f)
            @test types == cells[1] && offsets == cells[2] && conn == cells[3]   # 0-based nodes
            @test Gamut.get_mesh_label(f, "zone") == [0, 0, 0, 1, 1, 1]
            @test Gamut.categories(f, "zone") == ["inlet", "wall"]
            @test_throws GamutError Gamut.categories(f, "mach")
            @test Gamut.related(f, "u")["vector"] == ["u"]
        end
        # Threads give the same answer.
        a = Gamut.open(f -> Gamut.get_field(f, "p"; rows=2:5, nodes=3:9), p)
        b = Gamut.open(f -> Gamut.get_field(f, "p"; rows=2:5, nodes=3:9), p; threads=4)
        @test a == b
    end

    @testset "a family: geometry per member" begin
        p = joinpath(tmp, "family.gamut")
        pts, cells = grid(3, 3)
        geometry = Dict(m => Float32.(pts .* (1 + k)) for (k, m) in enumerate(["c", "a", "b"]))
        Gamut.create(p; writer="TopoLink", mesh="shared", per="group:member",
                      coordinates=(units="m", axes=2),
                      labels=Dict("member" => (role="group", categories=["a", "b", "c"])),
                      parameters=Dict("mach" => "1"), fields=Dict("p" => (units="Pa", at="node"))) do s
            Gamut.set_mesh!(s; cells=cells, n_nodes=9)
            members = ["c", "c", "a", "a"]
            Gamut.add_runs!(s, Dict("member" => members, "mach" => [5.0, 8.0, 5.0, 8.0]);
                             fields=Dict("p" => ones(4, 9)), points=[geometry[m] for m in members])
            @test_throws GamutError Gamut.add_runs!(s, Dict("member" => ["b", "b"], "mach" => [1.0, 2.0]);
                                                      points=[geometry["b"], geometry["a"]])
        end
        Gamut.open(p; mode="a") do s
            Gamut.add_run!(s, Dict("member" => "b", "mach" => 5.0); fields=Dict("p" => zeros(9)),
                            points=geometry["b"])
        end
        Gamut.open(p) do f
            @test f.row_count == 5
            @test Gamut.get_points(f; row=1) == geometry["c"]
            @test Gamut.get_points(f; row=5) == geometry["b"]
        end
        @test isempty(Gamut.validate(p))
    end

    @testset "a changing mesh, one row at a time" begin
        p = joinpath(tmp, "remeshed.gamut")
        big, bigcells = grid(4, 4)
        small, smallcells = grid(2, 2)
        Gamut.create(p; writer="tests", mesh="changing", per="run",
                      coordinates=(units="m", axes=2), parameters=Dict("r" => "m"),
                      fields=Dict("p" => (units="Pa", at="node"))) do s
            Gamut.add_run!(s, Dict("r" => 1.0); fields=Dict("p" => collect(0.0:15.0)),
                            points=big, cells=bigcells)
            Gamut.add_run!(s, Dict("r" => 2.0); fields=Dict("p" => collect(100.0:103.0)),
                            points=small, cells=smallcells)
        end
        Gamut.open(p) do f
            @test f.type == "changing"
            @test Gamut.get_field(f, "p"; rows=2) == collect(100.0:103.0)
            @test size(Gamut.get_points(f; row=1)) == (16, 2)
            types, offsets, conn = Gamut.get_cells(f; row=2)
            @test types == [9] && conn == [0, 1, 3, 2]
            @test_throws GamutError Gamut.get_field(f, "p")
            @test_throws GamutError Gamut.get_cells(f)
        end
    end

    @testset "a derivative along each axis is its own entry" begin
        pts, cells = grid(2, 2)
        p = joinpath(tmp, "derivatives.gamut")
        Gamut.create(p; writer="t", mesh="shared", per="fixed", coordinates=(units="m", axes=2),
                      scalars=Dict("cl" => "1"),
                      fields=Dict(k => (units="m-1", at="node", of="cl", with_respect_to="coordinates", axis=a)
                                  for (k, a) in ("dcl_dx" => "x", "dcl_dy" => "y"))) do s
            Gamut.set_mesh!(s; points=pts, cells=cells)
            Gamut.add_run!(s, Dict("cl" => 1.0); fields=Dict("dcl_dx" => zeros(4), "dcl_dy" => zeros(4)))
        end
        Gamut.open(p) do f
            @test Gamut.related(f, "cl")["derivatives"] ==
                  Dict("coordinates:x" => "dcl_dx", "coordinates:y" => "dcl_dy")
        end
    end

    @testset "a Bool note is an integer note" begin
        p = joinpath(tmp, "notes.gamut")
        Gamut.create(p; writer="t") do s
            Gamut.set_note!(s, "flag", true)
            Gamut.set_note!(s, "n", 3)
            Gamut.set_note!(s, "x", 1.5)
        end
        kinds = Gamut.open(p) do f
            k, t, v = (Ref{Ptr{Cvoid}}(C_NULL) for _ in 1:3)
            ccall(Gamut.sym(:gamut_notes), Cint, (Ptr{Cvoid}, Ref{Ptr{Cvoid}}, Ref{Ptr{Cvoid}},
                  Ref{Ptr{Cvoid}}, Ptr{Cvoid}), f.handle, k, t, v, C_NULL)
            names, kinds, _ = Gamut.take_strings(k[]), Gamut.take_strings(t[]), Gamut.take_strings(v[])
            Dict(zip(names, kinds))
        end
        @test kinds == Dict("flag" => "int", "n" => "int", "x" => "float")
    end

    @testset "refusals carry rules and add nothing" begin
        p = joinpath(tmp, "bad.gamut")
        e = try Gamut.create(p; writer="t", parameters=Dict("x" => "m//s")); nothing catch x; x end
        @test e isa GamutError && e.rule == "E7" && !isfile(p)
        e = try
            Gamut.create(p; writer="t", mesh="shared", per="fixed", coordinates=(units="m", axes=2),
                          fields=Dict("p" => (units="Pa", at="node")), scalars=Dict("p" => "Pa"))
            nothing
        catch x
            x
        end
        @test e isa GamutError && e.rule == "E8" && !isfile(p)
        @test_throws GamutError Gamut.create(p; writer="t", parameter=Dict("x" => "m"))
        e = try Gamut.create(p; writer="t", mesh="shared"); nothing catch x; x end
        @test e isa GamutError && e.rule == "E6" && !isfile(p)
        for bound in ((lower=0.0,), (upper=1.0,))
            e = try Gamut.create(p; writer="t", parameters=Dict("x" => (units="1", bound...))); nothing catch x; x end
            @test e isa GamutError && e.rule == "E16" && !isfile(p)
        end
        pts, cells = grid(2, 2)
        Gamut.create(joinpath(tmp, "cells.gamut"); writer="t", mesh="shared", per="fixed",
                      coordinates=(units="m", axes=2)) do s
            for offsets in (Int64[0], Int64[0, 4, 9])
                e = try Gamut.set_mesh!(s; points=pts, cells=(cells[1], offsets, cells[3])); nothing catch x; x end
                @test e isa GamutError && e.rule == "E5"
            end
            Gamut.set_mesh!(s; points=pts, cells=cells)
        end
        e = try
            Gamut.create(p; writer="t", mesh="changing", per="run",
                          coordinates=(units="m", axes="two"))
            nothing
        catch x
            x
        end
        @test e isa GamutError && e.rule == "E24" && !isfile(p)
        @test_throws GamutError Gamut.create(p; writer="t", parameters=Dict("x\0y" => "m"))
        Gamut.create(p; writer="t", parameters=Dict("x" => "m")) do s
            e = try Gamut.add_run!(s, Dict("y" => 1.0)); nothing catch x; x end
            @test e.rule == "E2"
            Gamut.add_run!(s, Dict("x" => 1.0))
        end
        Gamut.open(p) do f
            @test f.row_count == 1
            @test_throws GamutError Gamut.get_parameter(f, "x"; rows=[1.5])
            @test_throws GamutError Gamut.get_parameter(f, "x"; rows=true)
        end
    end

    @testset "copies between files" begin
        a, b, e, w = (joinpath(tmp, n) for n in ("ja.gamut", "jb.gamut", "je.gamut", "jw.gamut"))
        for (p, xs, cases) in ((a, [1.0, 2.0], ["p", "q"]), (b, [3.0, 4.0], ["r", "p"]))
            Gamut.create(p; writer="t", parameters=Dict("x" => "m"),
                          labels=Dict("case" => "categorical")) do s
                Gamut.add_runs!(s, Dict("x" => xs, "case" => cases))
            end
        end
        @test Gamut.append!(a, b) == 2
        Gamut.extract(a, e, [2, 4])
        Gamut.open(e) do f
            @test Gamut.get_row_ids(f) == [1, 3] && Gamut.get_label(f, "case") == ["q", "p"]
        end
        Gamut.write_copy(a, w)
        ida = Gamut.open(f -> Gamut.describe(f)["file_id"], a)
        idw = Gamut.open(f -> Gamut.describe(f)["file_id"], w)
        @test ida == idw
        @test_throws GamutError Gamut.append!(a, a)
        @test isempty(Gamut.validate(e)) && isempty(Gamut.validate(w))
    end

    @testset "how far each row lies outside its parameter's bounds" begin
        p = joinpath(tmp, "bounds.gamut")
        Gamut.create(p; writer="tests",
                      parameters=Dict("x" => (units="m", lower=0.0, upper=1.0), "mach" => "1"),
                      scalars=Dict("cl" => "1")) do s
            Gamut.add_runs!(s, Dict("x" => [-0.5, 0.0, 0.25, 1.0, 1.5], "mach" => fill(0.5, 5),
                                     "cl" => zeros(5)))
        end
        Gamut.open(p) do f
            @test Gamut.outside(f, "x") == [-0.5, 0.0, 0.0, 0.0, 0.5]
            @test Gamut.outside(f, "x"; rows=[1, 5]) == [-0.5, 0.5]          # 1-based
            @test Gamut.outside(f, "x"; rows=2:4) == [0.0, 0.0, 0.0]
            @test Gamut.outside(f, "x"; rows=5) == 0.5
            e = try Gamut.outside(f, "mach"); nothing catch x; x end
            @test e isa GamutError && occursin("mach declares no bounds", e.message)
            e = try Gamut.outside(f, "cl"); nothing catch x; x end
            @test e isa GamutError && occursin("no parameter", e.message)
            e = try Gamut.outside(f, "x"; rows=[6]); nothing catch x; x end
            @test e isa GamutError && occursin("outside the 5 positions", e.message)
            @test_throws GamutError Gamut.outside(f, "x"; rows=[1.5])
        end
    end

    @testset "the built-in nearest model" begin
        mp = joinpath(tmp, "nearest.gamut")
        Gamut.create_model(mp; writer="tests",
                            parameters=Dict("alpha" => (units="degree", lower=0.0, upper=10.0)),
                            scalars=Dict("cl" => (units="1", model="fit", output="cl"))) do s
            Gamut.add_model!(s, "fit", Gamut.Nearest(["alpha"], [0.0], [10.0], [0.0; 5.0; 10.0;;],
                                                       Dict("cl" => [0.1, 0.5, 1.0])), ["alpha"])
        end
        @test isempty(Gamut.validate(mp))
        out = Gamut.evaluate(mp, Dict("alpha" => [1.0, 4.0, 9.0]))
        @test Gamut.get_scalar(out, "cl") == [0.1, 0.5, 1.0]
        path = out.path
        close(out)
        @test !isfile(path)
        # The answer keeps the model's bounds and marks each row against them.
        out = @test_logs (:warn, r"W4") Gamut.evaluate(mp, Dict("alpha" => [-2.0, 5.0, 12.0]))
        @test Gamut.outside(out, "alpha") == [-2.0, 0.0, 2.0]
        close(out)
        numbers = Gamut.open(s -> Gamut.model_numbers(s, "fit"), mp)
        @test numbers["lower"] == [0.0] && numbers["columns"] == ["alpha"]
    end
end
