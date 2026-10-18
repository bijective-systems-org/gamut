# A sweep on one mesh, written run by run, then read by condition.
#
# Potential flow past a cylinder at nine values of circulation, on one ring
# of quadrilaterals. examples/00_readme.py and the MATLAB and C examples are
# the same program and print the same line. Positions
# (runs, nodes, cells) are 1-based; the node numbers inside cells stay
# 0-based, as in VTK and every other language.
using Gamut
using Printf

n_theta, n_r = 48, 12
theta = range(0, 2π; length=n_theta + 1)[1:end-1]
radius = exp10.(range(0, log10(6); length=n_r))
t = vec([θ for θ in theta, ρ in radius])                 # around each ring first
r = vec([ρ for θ in theta, ρ in radius])
points = hcat(r .* cos.(t), r .* sin.(t))
quads = [[j * n_theta + i, j * n_theta + (i + 1) % n_theta,
          (j + 1) * n_theta + (i + 1) % n_theta, (j + 1) * n_theta + i]
         for i in 0:n_theta-1, j in 0:n_r-2]
cells = (fill(UInt8(9), length(quads)),                  # VTK quadrilateral
         collect(0:4:4 * length(quads)),
         reduce(vcat, vec(quads)))
solve(gamma) = 1 .- ((cos.(t) .* (1 .- 1 ./ r .^ 2)) .^ 2 .+           # stands for the solver
                     (-sin.(t) .* (1 .+ 1 ./ r .^ 2) .+ gamma ./ (2π .* r)) .^ 2)

Gamut.create("cylinder.gamut"; writer="example sweep", mesh="shared", per="fixed",
              coordinates=(units="m", axes=2),
              parameters=Dict("gamma" => (units="m2 s-1", role="design")),
              fields=Dict("cp" => (units="1", at="node"))) do study
    Gamut.set_mesh!(study; points, cells)
    for gamma in range(0, 4; length=9)
        Gamut.add_run!(study, Dict("gamma" => gamma); fields=Dict("cp" => solve(gamma)))
    end
end

cp = Gamut.open("cylinder.gamut") do study
    rows = Gamut.select(study, "gamma > 2")
    Gamut.get_field(study, "cp"; rows, nodes=[13])           # runs × nodes, from 1
end
println("cp on top of the cylinder where gamma > 2: ", join((@sprintf("%.2f", v) for v in cp), " "))
