# Uncertainty and gradients beside the values they describe.
#
# Each run stores a lift coefficient with its standard deviation and two
# quantiles, and its derivative with respect to angle of attack. Each names
# the result it describes, so a reader finds them without naming
# conventions. examples/06_uncertainty_gradients.py and the MATLAB and C++
# examples are the same program and print the same lines.
using Gamut
using Printf

alpha = collect(range(0.0, 8.0; length=9))
cl = 0.11 .* alpha
spread = 0.01 .+ 0.002 .* alpha
Gamut.create("uncertain.gamut"; writer="example ensemble",
              parameters=Dict("alpha" => (units="degree", role="condition")),
              scalars=Dict("cl" => "1",
                           "cl_std" => (units="1", of="cl", statistic="std"),
                           "cl_p05" => (units="1", of="cl", statistic="quantile", q=0.05),
                           "cl_p95" => (units="1", of="cl", statistic="quantile", q=0.95),
                           "dcl_dalpha" => (units="degree-1", of="cl", with_respect_to="alpha"))) do study
    Gamut.add_runs!(study, Dict("alpha" => alpha, "cl" => cl, "cl_std" => spread,
                                "cl_p05" => cl .- 1.645 .* spread, "cl_p95" => cl .+ 1.645 .* spread,
                                "dcl_dalpha" => fill(0.11, 9)))
end

Gamut.open("uncertain.gamut") do study
    related = Gamut.related(study, "cl")
    println("the std of cl: ", related["std"])
    println("its 0.05 and 0.95 quantiles: ", related["quantiles"][0.05], " ", related["quantiles"][0.95])
    println("its derivative with respect to alpha: ", related["derivatives"]["alpha"])
    low = Gamut.get_scalar(study, related["quantiles"][0.05])
    high = Gamut.get_scalar(study, related["quantiles"][0.95])
    @printf("90 %% band at 8 degrees: %.3f to %.3f\n", low[end], high[end])
end
