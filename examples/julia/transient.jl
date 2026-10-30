# Transient runs: every saved step is a row.
#
# Two transient runs, each saved at 101 time steps. Time is a parameter with
# the role time, and a group label says which run each step belongs to.
# examples/05_time_series.py and the MATLAB and C++ examples are the same
# program and print the same lines. Positions count from 1.
using Gamut
using Printf

steps = collect(range(0.0, 10.0; length=101))
Gamut.create("transient.gamut"; writer="example transient",
              labels=Dict("run" => (role="group",)),
              parameters=Dict("t" => (units="s", role="time", run_group="run"),
                              "speed" => (units="m s-1", role="condition")),
              scalars=Dict("cl" => "1")) do study
    for (name, speed) in ("slow" => 20.0, "fast" => 35.0)
        frequency = 0.2 * speed / 10.0                              # shedding, Strouhal 0.2
        cl = 0.8 .* sin.(2π * frequency .* steps) .* (1 .- exp.(-steps))
        Gamut.add_runs!(study, Dict("run" => fill(name, length(steps)), "t" => steps,
                                    "speed" => fill(speed, length(steps)), "cl" => cl))
    end
end

Gamut.open("transient.gamut") do study
    println(study.row_count, " rows, ", length(Gamut.categories(study, "run")), " runs")
    fast = Gamut.select(study, "run == fast")
    t, cl = Gamut.get_parameter(study, "t"; rows=fast), Gamut.get_scalar(study, "cl"; rows=fast)
    peak = argmax(abs.(cl))
    @printf("fast run: %d steps, peak |cl| %.2f at t = %.1f s\n", length(fast), abs(cl[peak]), t[peak])
end
