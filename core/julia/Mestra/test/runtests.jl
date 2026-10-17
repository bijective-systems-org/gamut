# The Julia package over the shared core: each kind of study written with
# the package and read back with it, the refusals, and the built-in model.
using Test
using Mestra

function grid(nx, ny)
    pts = Float64[[i, j][a] for j in 0:ny-1 for i in 0:nx-1, a in 1:2]
    pts = reshape(pts, nx * ny, 2)
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
        p = joinpath(tmp, "polar.mes")
        Mestra.create(p; writer="tests",
                      parameters=Dict("mach" => (units="1", role="condition"), "alpha" => "degree"),
                      labels=Dict("status" => (role="status", categories=["converged", "failed"])),
                      scalars=Dict("cl" => "1", "cd" => "1"),
                      constants=Dict("s_ref" => (12.5, "m2")), title="Wing A polar") do s
            for i in 0:19
                id = Mestra.add_run!(s, Dict("mach" => 0.3 + 0.01i, "alpha" => Float64(i % 5),
                                             "status" => i == 7 ? "failed" : "converged",
                                             "cl" => 0.1 * (i % 5), "cd" => 0.01f0))
                @test id == i
            end
        end
        Mestra.open(p) do f
            @test f.kind == "data" && f.type == "table" && f.row_count == 20
            @test Mestra.describe(f)["title"] == "Wing A polar"
            @test Mestra.get_scalar(f, "cl"; rows=1:3) ≈ [0.0, 0.1, 0.2]
            @test Mestra.get_label(f, "status"; rows=8) == "failed"       # 1-based
            @test Mestra.get_constant(f, "s_ref") == 12.5
            @test eltype(Mestra.get_scalar(f, "cd")) == Float32             # as given
            @test Mestra.get_row_ids(f) == collect(0:19)
            @test Mestra.select(f, "status == failed") == [8]
            t = Mestra.table(f)
            @test t["status"][8] == "failed"
        end
    end

    @testset "a sweep on one mesh, region reads" begin
        p = joinpath(tmp, "sweep.mes")
        pts, cells = grid(4, 3)
        prun = reshape(Float32.(0:6*12-1), 12, 6)'          # runs × nodes
        Mestra.create(p; writer="tests", mesh="shared", per="fixed",
                      coordinates=(units="m", axes=2),
                      parameters=Dict("mach" => "1"),
                      mesh_labels=Dict("zone" => (at="cell", categories=["inlet", "wall"])),
                      fields=Dict("p" => (units="Pa", at="node"),
                                  "u" => (units="m s-1", at="cell", vector="velocity", axis="x"))) do s
            Mestra.set_mesh!(s; points=pts, cells=cells, labels=Dict("zone" => [0, 0, 0, 1, 1, 1]))
            Mestra.add_runs!(s, Dict("mach" => collect(0.1:0.1:0.6));
                             fields=Dict("p" => prun, "u" => zeros(6, 6)))
        end
        Mestra.open(p) do f
            @test f.type == "shared" && f.row_count == 6
            @test Mestra.get_field(f, "p") == prun
            @test Mestra.get_field(f, "p"; rows=2:3, nodes=[1, 5, 12]) == prun[2:3, [1, 5, 12]]
            @test Mestra.get_field(f, "p"; rows=4) == prun[4, :]
            @test Mestra.get_points(f) == pts
            types, offsets, conn = Mestra.get_cells(f)
            @test types == cells[1] && offsets == cells[2] && conn == cells[3]   # 0-based nodes
            @test Mestra.get_mesh_label(f, "zone") == [0, 0, 0, 1, 1, 1]
            @test Mestra.related(f, "u")["vector"] == ["u"]
        end
        # Threads give the same answer.
        a = Mestra.open(f -> Mestra.get_field(f, "p"; rows=2:5, nodes=3:9), p)
        b = Mestra.open(f -> Mestra.get_field(f, "p"; rows=2:5, nodes=3:9), p; threads=4)
        @test a == b
    end

    @testset "a family: geometry per member" begin
        p = joinpath(tmp, "family.mes")
        pts, cells = grid(3, 3)
        geometry = Dict(m => Float32.(pts .* (1 + k)) for (k, m) in enumerate(["c", "a", "b"]))
        Mestra.create(p; writer="TopoLink", mesh="shared", per="group:member",
                      coordinates=(units="m", axes=2),
                      labels=Dict("member" => (role="group", categories=["a", "b", "c"])),
                      parameters=Dict("mach" => "1"), fields=Dict("p" => (units="Pa", at="node"))) do s
            Mestra.set_mesh!(s; cells=cells, n_nodes=9)
            members = ["c", "c", "a", "a"]
            Mestra.add_runs!(s, Dict("member" => members, "mach" => [5.0, 8.0, 5.0, 8.0]);
                             fields=Dict("p" => ones(4, 9)), points=[geometry[m] for m in members])
            @test_throws MestraError Mestra.add_runs!(s, Dict("member" => ["b", "b"], "mach" => [1.0, 2.0]);
                                                      points=[geometry["b"], geometry["a"]])
        end
        Mestra.open(p; mode="a") do s
            Mestra.add_run!(s, Dict("member" => "b", "mach" => 5.0); fields=Dict("p" => zeros(9)),
                            points=geometry["b"])
        end
        Mestra.open(p) do f
            @test f.row_count == 5
            @test Mestra.get_points(f; row=1) == geometry["c"]
            @test Mestra.get_points(f; row=5) == geometry["b"]
        end
        @test isempty(Mestra.validate(p))
    end

    @testset "a changing mesh, one row at a time" begin
        p = joinpath(tmp, "remeshed.mes")
        big, bigcells = grid(4, 4)
        small, smallcells = grid(2, 2)
        Mestra.create(p; writer="tests", mesh="changing", per="run",
                      coordinates=(units="m", axes=2), parameters=Dict("r" => "m"),
                      fields=Dict("p" => (units="Pa", at="node"))) do s
            Mestra.add_run!(s, Dict("r" => 1.0); fields=Dict("p" => collect(0.0:15.0)),
                            points=big, cells=bigcells)
            Mestra.add_run!(s, Dict("r" => 2.0); fields=Dict("p" => collect(100.0:103.0)),
                            points=small, cells=smallcells)
        end
        Mestra.open(p) do f
            @test f.type == "changing"
            @test Mestra.get_field(f, "p"; rows=2) == collect(100.0:103.0)
            @test size(Mestra.get_points(f; row=1)) == (16, 2)
            types, offsets, conn = Mestra.get_cells(f; row=2)
            @test types == [9] && conn == [0, 1, 3, 2]
            @test_throws MestraError Mestra.get_field(f, "p")
            @test_throws MestraError Mestra.get_cells(f)
        end
    end

    @testset "refusals carry rules and add nothing" begin
        p = joinpath(tmp, "bad.mes")
        e = try Mestra.create(p; writer="t", parameters=Dict("x" => "m//s")); nothing catch x; x end
        @test e isa MestraError && e.rule == "E7" && !isfile(p)
        e = try
            Mestra.create(p; writer="t", mesh="shared", per="fixed", coordinates=(units="m", axes=2),
                          fields=Dict("p" => (units="Pa", at="node")), scalars=Dict("p" => "Pa"))
            nothing
        catch x
            x
        end
        @test e isa MestraError && e.rule == "E8" && !isfile(p)
        @test_throws MestraError Mestra.create(p; writer="t", parameter=Dict("x" => "m"))
        @test_throws MestraError Mestra.create(p; writer="t", parameters=Dict("x\0y" => "m"))
        Mestra.create(p; writer="t", parameters=Dict("x" => "m")) do s
            e = try Mestra.add_run!(s, Dict("y" => 1.0)); nothing catch x; x end
            @test e.rule == "E2"
            Mestra.add_run!(s, Dict("x" => 1.0))
        end
        Mestra.open(p) do f
            @test f.row_count == 1
            @test_throws MestraError Mestra.get_parameter(f, "x"; rows=[1.5])
            @test_throws MestraError Mestra.get_parameter(f, "x"; rows=true)
        end
    end

    @testset "copies between files" begin
        a, b, e, w = (joinpath(tmp, n) for n in ("ja.mes", "jb.mes", "je.mes", "jw.mes"))
        for (p, xs, cases) in ((a, [1.0, 2.0], ["p", "q"]), (b, [3.0, 4.0], ["r", "p"]))
            Mestra.create(p; writer="t", parameters=Dict("x" => "m"),
                          labels=Dict("case" => "categorical")) do s
                Mestra.add_runs!(s, Dict("x" => xs, "case" => cases))
            end
        end
        @test Mestra.append!(a, b) == 2
        Mestra.extract(a, e, [2, 4])
        Mestra.open(e) do f
            @test Mestra.get_row_ids(f) == [1, 3] && Mestra.get_label(f, "case") == ["q", "p"]
        end
        Mestra.write_copy(a, w)
        ida = Mestra.open(f -> Mestra.describe(f)["file_id"], a)
        idw = Mestra.open(f -> Mestra.describe(f)["file_id"], w)
        @test ida == idw
        @test_throws MestraError Mestra.append!(a, a)
        @test isempty(Mestra.validate(e)) && isempty(Mestra.validate(w))
    end

    @testset "the built-in nearest model" begin
        mp = joinpath(tmp, "nearest.mes")
        Mestra.create_model(mp; writer="tests",
                            parameters=Dict("alpha" => (units="degree", lower=0.0, upper=10.0)),
                            scalars=Dict("cl" => (units="1", model="fit", output="cl"))) do s
            Mestra.add_model!(s, "fit", Mestra.Nearest(["alpha"], [0.0], [10.0], [0.0; 5.0; 10.0;;],
                                                       Dict("cl" => [0.1, 0.5, 1.0])), ["alpha"])
        end
        @test isempty(Mestra.validate(mp))
        out = Mestra.evaluate(mp, Dict("alpha" => [1.0, 4.0, 9.0]))
        @test Mestra.get_scalar(out, "cl") == [0.1, 0.5, 1.0]
        path = out.path
        close(out)
        @test !isfile(path)
    end
end
