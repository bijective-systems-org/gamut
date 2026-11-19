# Write three runs to first.gamut and read back the lift coefficients.
using GamutFile
using Printf

# Values at the same position belong to the same run.
alpha = [0.0, 2.0, 4.0]
cl = [0.0, 0.22, 0.44]

GamutFile.create("first.gamut"; writer="example sweep",
                 parameters=Dict("alpha" => (units="degree", role="condition")),
                 scalars=Dict("cl" => "1")) do study
    GamutFile.add_runs!(study, Dict("alpha" => alpha, "cl" => cl))
end

lift = GamutFile.open("first.gamut") do study
    GamutFile.get_scalar(study, "cl")
end

println("cl: ", join([@sprintf("%.2f", value) for value in lift], " "))
