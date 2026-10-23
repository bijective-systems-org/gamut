# A sweep on one mesh: eight runs written, a ninth added, then read.
#
# Potential flow past a cylinder at nine values of circulation, on one ring
# of quadrilaterals. The MATLAB, C++ and C examples of this name are the
# same program and print the same line. Positions
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
    for gamma in range(0, 3.5; length=8)
        Gamut.add_run!(study, Dict("gamma" => gamma); fields=Dict("cp" => solve(gamma)))
    end
end

Gamut.open("cylinder.gamut"; mode="a") do study
    Gamut.add_run!(study, Dict("gamma" => 4.0); fields=Dict("cp" => solve(4.0)))
end

cp = Gamut.open("cylinder.gamut") do study
    Gamut.get_field(study, "cp"; nodes=[13])                 # runs × nodes, from 1
end
println("cp at the top of the cylinder, run by run: ", join((@sprintf("%.2f", v) for v in cp), " "))
