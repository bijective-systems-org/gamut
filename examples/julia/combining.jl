# Growing, splitting and rewriting files.
#
# `Gamut.append!` adds one file's runs to another (the same declarations;
# category names merged); `Gamut.extract` keeps chosen runs as a new file,
# their ids kept; `Gamut.write_copy` rewrites a file with the default layout,
# keeping its identity. examples/09_combining_files.py and the MATLAB and C++
# examples are the same program and print the same lines. Positions count
# from 1; row ids are the file's own, from 0.
using Gamut
using Printf

function sweep(path, machs)
    Gamut.create(path; writer="example sweep",
                  parameters=Dict("mach" => (units="1", role="condition")),
                  labels=Dict("status" => (role="status", categories=["converged", "failed"])),
                  scalars=Dict("cd" => "1")) do study
        for mach in machs
            Gamut.add_run!(study, Dict("mach" => mach, "status" => mach > 0.85 ? "failed" : "converged",
                                       "cd" => 0.01 + 0.05 * max(0.0, mach - 0.7)^2))
        end
    end
end

sweep("monday.gamut", [0.5, 0.6, 0.7])
sweep("tuesday.gamut", [0.8, 0.9])
println("appended ", Gamut.append!("monday.gamut", "tuesday.gamut"), " runs")

good = Gamut.open(study -> Gamut.select(study, "status == converged"), "monday.gamut")
Gamut.extract("monday.gamut", "converged.gamut", good)
Gamut.write_copy("converged.gamut", "converged_copy.gamut")

Gamut.open("converged.gamut") do study
    Gamut.open("converged_copy.gamut") do copy
        println("kept ids: ", join(Gamut.get_row_ids(study), " "), " at mach ",
                join((@sprintf("%g", m) for m in Gamut.get_parameter(study, "mach")), " "))
        same = Gamut.describe(study)["file_id"] == Gamut.describe(copy)["file_id"]
        println("same file id after the rewrite: ", same ? "yes" : "no")
    end
end
println("valid: ", all(f -> f.severity != "error", Gamut.validate("converged.gamut")) ? "yes" : "no")
