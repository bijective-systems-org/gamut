# The built-in nearest model of examples/07_models.py, fitted in Python and
# evaluated in Julia. Run that script first, in this folder: it writes
# lift_nearest.gamut. Both print the same lines.
using GamutFile
using Printf

answer = GamutFile.evaluate("lift_nearest.gamut", Dict("alpha" => [2.2, 7.9]))
lift = GamutFile.get_scalar(answer, "cl")
close(answer)
println("the nearest run's lift at 2.2 and 7.9 degrees: ", join([@sprintf("%.2f", v) for v in lift], " "))

# An angle outside the range the model was fitted on is evaluated, with a
# warning (W4), and the answer says for each row how far outside it lies.
answer = GamutFile.evaluate("lift_nearest.gamut", Dict("alpha" => [5.0, 12.0]))
outside = GamutFile.outside(answer, "alpha")
close(answer)
println("degrees outside the fitted range: ", join([@sprintf("%g", v) for v in outside], " "))
