# A sweep of a wing's angle of attack: six runs written, a seventh added,
# then read. examples/00_readme.py and the MATLAB and C++ examples are the
# same program and print the same line. Positions count from 1.
using Gamut
using Printf

solve(alpha) = 0.11 * alpha            # stands for the solver: lift at one angle

Gamut.create("sweep.gamut"; writer="example sweep",
              parameters=Dict("alpha" => (units="degree", role="condition")),
              labels=Dict("status" => (role="status", categories=["converged", "failed"])),
              scalars=Dict("cl" => "1")) do study
    for alpha in 0.0:2.0:10.0
        Gamut.add_run!(study, Dict("alpha" => alpha, "status" => "converged", "cl" => solve(alpha)))
    end
end

Gamut.open("sweep.gamut"; mode="a") do study
    Gamut.add_run!(study, Dict("alpha" => 12.0, "status" => "failed"))
end

cl = Gamut.open("sweep.gamut") do study
    Gamut.get_scalar(study, "cl"; rows=Gamut.select(study, "status == converged"))
end
println("lift of the runs that converged: ", join([@sprintf("%.2f", v) for v in cl], " "))
