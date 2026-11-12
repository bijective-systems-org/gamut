# Runs on different meshes: a refinement study.
#
# The same flow on three meshes of increasing resolution, with the pressure
# stored per cell. examples/04_changing_mesh.py and the MATLAB and C++
# examples are the same program and print the same lines. Positions count
# from 1.
using GamutFile
using Printf
include(joinpath(@__DIR__, "_cylinder.jl"))

GamutFile.create("refinement.gamut"; writer="example refinement", mesh="changing", per="run",
              coordinates=(units="m", axes=2),
              parameters=Dict("cells_round" => (units="1", role="design")),
              scalars=Dict("cp_min" => "1"),
              fields=Dict("cp" => (units="1", at="cell"))) do study
    for n in (24, 48, 96)
        points, cells, _, _ = ring(; n_theta=n, n_r=n ÷ 4)
        corners = reshape(cells[3], 4, :) .+ 1                      # four nodes per quad, from 1
        x = vec(sum(points[corners, 1]; dims=1)) ./ 4
        y = vec(sum(points[corners, 2]; dims=1)) ./ 4
        cp = pressure(atan.(y, x), hypot.(x, y))
        GamutFile.add_run!(study, Dict("cells_round" => n, "cp_min" => minimum(cp));
                       fields=Dict("cp" => cp), points, cells)
    end
end

GamutFile.open("refinement.gamut") do study
    rounds = GamutFile.get_parameter(study, "cells_round")
    for row in 1:study.row_count
        types, _, _ = GamutFile.get_cells(study; row)
        cp = GamutFile.get_field(study, "cp"; rows=row)
        @printf("%g cells round: %d nodes, %d cells, lowest cell cp %.3f\n", rounds[row],
                size(GamutFile.get_points(study; row), 1), length(types), minimum(cp))
    end
end
