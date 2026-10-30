# Reading only what you need: rows by condition, nodes by zone.
#
# Runs are chosen with a small expression language and nodes by a mesh
# label. Values arrive in the units they were stored in; this program
# converts them itself, where Python's reads convert on request.
# examples/08_selecting_parts.py and the MATLAB and C++ examples are the
# same program and print the same lines. Positions count from 1.
using Gamut
using Printf
include(joinpath(@__DIR__, "_cylinder.jl"))

points, cells, t, r = ring()
surface = Int64.(r .== minimum(r))                              # 1 on the wall
Gamut.create("parts.gamut"; writer="example parts", mesh="shared", per="fixed",
              coordinates=(units="m", axes=2),
              parameters=Dict("gamma" => (units="m2 s-1", role="condition"),
                              "speed" => (units="m s-1", role="condition")),
              labels=Dict("status" => (role="status", categories=["converged", "failed"])),
              mesh_labels=Dict("surface" => (at="node", categories=["field", "wall"])),
              fields=Dict("p" => (units="Pa", at="node"))) do study
    Gamut.set_mesh!(study; points, cells, labels=Dict("surface" => surface))
    for speed in (10.0, 20.0, 40.0), gamma in (0.0, 2.0, 4.0)
        q = 0.5 * 1.225 * speed^2                               # dynamic pressure, air at sea level
        Gamut.add_run!(study, Dict("gamma" => gamma, "speed" => speed, "status" => "converged");
                       fields=Dict("p" => q .* pressure(t, r; gamma)))
    end
end

Gamut.open("parts.gamut") do study
    rows = Gamut.select(study, "speed >= 20 and gamma > 1 and status == converged")
    println("chosen: ", length(rows), " runs")
    wall = findfirst(==("wall"), Gamut.categories(study, "surface")) - 1   # the code that means "wall"
    on_wall = findall(==(wall), vec(Gamut.get_mesh_label(study, "surface")))
    p_wall = Gamut.get_field(study, "p"; rows, nodes=on_wall) ./ 1000      # stored in Pa; kPa
    @printf("wall pressure: %d runs x %d nodes, lowest %.3f kPa\n", size(p_wall)..., minimum(p_wall))
    speeds = Gamut.get_parameter(study, "speed"; rows) .* 3.6               # stored in m s-1; km/h
    println("speeds in km/h: ", join((@sprintf("%.1f", v) for v in speeds), " "))
end
