# A sweep of a wing's angle of attack: six runs written, a seventh added,
# then read. The six are written at once, as columns. examples/00_readme.py
# and the MATLAB and C++ examples are the same program and print the same
# line. Positions count from 1.
using GamutFile
using Printf

alpha = collect(0.0:2.0:10.0)  # six angles of attack, in degrees
cl = 0.11 .* alpha             # stands for the solver's lift coefficients

GamutFile.create("sweep.gamut"; writer="example sweep",
              parameters=Dict("alpha" => (units="degree", role="condition")),
              labels=Dict("status" => (role="status",
                                       categories=["converged", "failed"])),
              scalars=Dict("cl" => "1")) do study
    status = fill("converged", length(alpha))
    GamutFile.add_runs!(study, Dict("alpha" => alpha, "cl" => cl, "status" => status))
end

GamutFile.open("sweep.gamut"; mode="a") do study
    GamutFile.add_run!(study, Dict("alpha" => 12.0, "status" => "failed"))
end

lift = GamutFile.open("sweep.gamut") do study
    GamutFile.get_scalar(study, "cl"; rows=GamutFile.select(study, "status == converged"))
end
println("lift of the runs that converged: ", join([@sprintf("%.2f", v) for v in lift], " "))
