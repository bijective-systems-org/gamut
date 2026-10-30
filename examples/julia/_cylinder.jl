# The ring of quadrilaterals around a cylinder that several examples share,
# as examples/_cylinder.py.

"""Points (nodes × 2), cells (types, offsets, connectivity) and the polar
coordinates of each node, for a ring of quads around a cylinder."""
function ring(; n_theta=48, n_r=12, radius=1.0, outer=6.0)
    theta = range(0, 2π; length=n_theta + 1)[1:end-1]
    rings = radius .* exp10.(range(0, log10(outer); length=n_r))
    t = vec([θ for θ in theta, ρ in rings])            # around each ring first
    r = vec([ρ for θ in theta, ρ in rings])
    points = hcat(r .* cos.(t), r .* sin.(t))
    quads = [[j * n_theta + i, j * n_theta + (i + 1) % n_theta,
              (j + 1) * n_theta + (i + 1) % n_theta, (j + 1) * n_theta + i]
             for i in 0:n_theta-1, j in 0:n_r-2]
    cells = (fill(UInt8(9), length(quads)),             # VTK quadrilateral
             collect(0:4:4 * length(quads)),
             reduce(vcat, vec(quads)))
    return points, cells, t, r
end

"""Pressure coefficient of potential flow past a cylinder with circulation
gamma, free stream speed 1."""
function pressure(t, r; radius=1.0, gamma=0.0)
    u_r = cos.(t) .* (1 .- radius^2 ./ r .^ 2)
    u_t = -sin.(t) .* (1 .+ radius^2 ./ r .^ 2) .+ gamma ./ (2π .* r)
    return 1 .- (u_r .^ 2 .+ u_t .^ 2)
end
