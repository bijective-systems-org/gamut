# A family of geometries that share one mesh topology.
#
# Three cylinders of different radius, meshed with the same topology, so
# node k is the same place on every member, each run at three circulations.
# examples/03_geometry_family.py and the MATLAB and C++ examples are the
# same program and print the same lines. Positions count from 1.
using Gamut
using Printf
include(joinpath(@__DIR__, "_cylinder.jl"))

base, cells, _, _ = ring()
members = ["slim" => 0.8, "base" => 1.0, "wide" => 1.2]

Gamut.create("family.gamut"; writer="example family", mesh="shared", per="group:member",
              coordinates=(units="m", axes=2),
              labels=Dict("member" => (role="group", categories=first.(members)),
                          "split" => (role="split", categories=["train", "test"])),
              generalisation_group="member",
              parameters=Dict("gamma" => (units="m2 s-1", role="condition")),
              fields=Dict("cp" => (units="1", at="node"))) do study
    Gamut.set_mesh!(study; cells, n_nodes=size(base, 1))
    for (name, radius) in members
        points, _, t, r = ring(; radius)
        for gamma in (0.0, 2.0, 4.0)
            Gamut.add_run!(study, Dict("member" => name, "gamma" => gamma,
                                       "split" => name == "wide" ? "test" : "train");
                           fields=Dict("cp" => pressure(t, r; radius, gamma)), points)
        end
    end
end

Gamut.open("family.gamut") do study
    println(study.row_count, " runs on ", length(members), " members of one topology")
    for (name, _) in members
        row = Gamut.select(study, "member == $name")[1]
        @printf("  %s: first node at x = %.2f m\n", name, Gamut.get_points(study; row)[1, 1])
    end
    cp = Gamut.get_field(study, "cp"; nodes=[1])
    println("cp at the first node, run by run: ", join((@sprintf("%.2f", v) for v in cp), " "))
    test = Gamut.select(study, "split == test")
    println("held out for testing: ", length(test), " runs of ",
            join(unique(Gamut.get_label(study, "member"; rows=test)), ", "))
end
