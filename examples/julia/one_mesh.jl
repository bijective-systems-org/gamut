# Fields on one mesh shared by every run, from Julia.
#
# The study of examples/02_one_mesh.py: potential flow past a cylinder at
# nine values of circulation, on one ring of quadrilaterals. Positions
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
surface = [ones(Int, n_theta); zeros(Int, n_theta * (n_r - 1))]   # wall: the first ring

Gamut.create("cylinder.gamut"; writer="example sweep", mesh="shared", per="fixed",
              coordinates=(units="m", axes=2),
              parameters=Dict("gamma" => (units="m2 s-1", role="design")),
              mesh_labels=Dict("surface" => (at="node", categories=["field", "wall"])),
              fields=Dict("cp" => (units="1", at="node"))) do study
    Gamut.set_mesh!(study; points, cells, labels=Dict("surface" => surface))
    for gamma in range(0, 4; length=9)
        u_theta = -sin.(t) .* (1 .+ 1 ./ r .^ 2) .+ gamma ./ (2π .* r)
        u_r = cos.(t) .* (1 .- 1 ./ r .^ 2)
        Gamut.add_run!(study, Dict("gamma" => gamma); fields=Dict("cp" => 1 .- (u_r .^ 2 .+ u_theta .^ 2)))
    end
end

Gamut.open("cylinder.gamut") do study
    println(study.type, " mesh, ", study.row_count, " runs, ", size(Gamut.get_points(study), 1), " nodes")
    cp = Gamut.get_field(study, "cp")                         # runs × nodes
    println("cp block: ", size(cp))
    wall = findfirst(==("wall"), Gamut.categories(study, "surface")) - 1   # the code that means "wall"
    on_wall = findall(==(wall), Gamut.get_mesh_label(study, "surface"))
    lowest = minimum(Gamut.get_field(study, "cp"; nodes=on_wall); dims=2)
    println("lowest cp on the wall, by run: ", round.(vec(lowest); digits=2))
    println("one node across every run: ", round.(vec(Gamut.get_field(study, "cp"; nodes=[13])); digits=2))
end

# The question the README asks in every language, with the same answer.
study = Gamut.open("cylinder.gamut")
rows = Gamut.select(study, "gamma > 2")
cp = Gamut.get_field(study, "cp"; rows, nodes=[13])        # runs × nodes, from 1
println("cp on top of the cylinder where gamma > 2: ", join((@sprintf("%.2f", v) for v in cp), " "))
close(study)
