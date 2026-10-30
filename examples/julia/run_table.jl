# A study with no mesh: a table of runs, each with its inputs and results.
# A sweep of a wing over Mach number and angle of attack.
# examples/01_run_table.py and the MATLAB and C++ examples are the same
# program and print the same lines. Positions count from 1.
using Gamut
using Printf

Gamut.create("polar.gamut"; writer="example sweep",
              parameters=Dict("mach" => (units="1", role="condition"),
                              "alpha" => (units="degree", role="condition")),
              labels=Dict("status" => (role="status", categories=["converged", "failed"])),
              scalars=Dict("cl" => "1", "cd" => "1"),
              constants=Dict("reference_area" => (12.5, "m2")),
              title="Wing A polar") do study
    for mach in (0.6, 0.7, 0.8), alpha in -2.0:2.0:8.0
        cl = 0.11 * alpha / sqrt(1 - mach^2)          # stand-in for a solver
        cd = 0.008 + 0.04 * cl^2
        failed = mach == 0.8 && alpha == 8
        Gamut.add_run!(study, Dict("mach" => mach, "alpha" => alpha,
                                   "status" => failed ? "failed" : "converged",
                                   "cl" => failed ? NaN : cl, "cd" => failed ? NaN : cd))
    end
end

Gamut.open("polar.gamut") do study
    println(study.row_count, " runs; ", Gamut.describe(study)["title"])
    cl = Gamut.get_scalar(study, "cl"; rows=Gamut.select(study, "mach == 0.7"))
    println("lift at Mach 0.7: ", join((@sprintf("%.3f", v) for v in cl), " "))
    failed = Gamut.select(study, "status == failed")
    mach = Gamut.get_parameter(study, "mach"; rows=failed)
    alpha = Gamut.get_parameter(study, "alpha"; rows=failed)
    @printf("failed: Mach %.1f, alpha %g degree\n", mach[1], alpha[1])
    @printf("reference area: %g %s\n", Gamut.get_constant(study, "reference_area"),
            Gamut.describe(study, "reference_area")["units"])
end
