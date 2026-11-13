# Growing, splitting and rewriting files.
#
# `GamutFile.append!` adds one file's runs to another (the same declarations;
# category names merged); `GamutFile.extract` keeps chosen runs as a new file,
# their ids kept; `GamutFile.write_copy` rewrites a file with the default layout,
# keeping its identity. examples/09_combining_files.py and the MATLAB and C++
# examples are the same program and print the same lines. Positions count
# from 1; row ids are the file's own, from 0.
using GamutFile
using Printf

function sweep(path, machs)
    GamutFile.create(path; writer="example sweep",
                  parameters=Dict("mach" => (units="1", role="condition")),
                  labels=Dict("status" => (role="status", categories=["converged", "failed"])),
                  scalars=Dict("cd" => "1")) do study
        for mach in machs
            GamutFile.add_run!(study, Dict("mach" => mach, "status" => mach > 0.85 ? "failed" : "converged",
                                       "cd" => 0.01 + 0.05 * max(0.0, mach - 0.7)^2))
        end
    end
end

sweep("monday.gamut", [0.5, 0.6, 0.7])
sweep("tuesday.gamut", [0.8, 0.9])
println("appended ", GamutFile.append!("monday.gamut", "tuesday.gamut"), " runs")

good = GamutFile.open(study -> GamutFile.select(study, "status == converged"), "monday.gamut")
GamutFile.extract("monday.gamut", "converged.gamut", good)
GamutFile.write_copy("converged.gamut", "converged_copy.gamut")

GamutFile.open("converged.gamut") do study
    GamutFile.open("converged_copy.gamut") do copy
        println("kept ids: ", join(GamutFile.get_row_ids(study), " "), " at mach ",
                join((@sprintf("%g", m) for m in GamutFile.get_parameter(study, "mach")), " "))
        same = GamutFile.describe(study)["file_id"] == GamutFile.describe(copy)["file_id"]
        println("same file id after the rewrite: ", same ? "yes" : "no")
    end
end
println("valid: ", all(f -> f.severity != "error", GamutFile.validate("converged.gamut")) ? "yes" : "no")
