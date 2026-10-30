"""Growing, splitting and rewriting files.

`append` adds one file's runs to another (the same declarations; category
names merged); `extract` keeps chosen runs as a new file, their ids kept;
`write_copy` rewrites a file with the default layout, keeping its identity.
The MATLAB, Julia and C++ examples combining are the same program and print
the same lines.
"""
import gamut


def sweep(path, machs):
    with gamut.create(path, writer="example sweep",
                       parameters={"mach": {"units": "1", "role": "condition"}},
                       labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                       scalars={"cd": "1"}) as study:
        for mach in machs:
            study.add_run({"mach": mach, "status": "failed" if mach > 0.85 else "converged",
                           "cd": 0.01 + 0.05 * max(0.0, mach - 0.7) ** 2})


sweep("monday.gamut", [0.5, 0.6, 0.7])
sweep("tuesday.gamut", [0.8, 0.9])
print("appended", gamut.append("monday.gamut", "tuesday.gamut"), "runs")

with gamut.open("monday.gamut") as study:
    good = study.select("status == converged")
gamut.extract("monday.gamut", "converged.gamut", good)
gamut.write_copy("converged.gamut", "converged_copy.gamut")

with gamut.open("converged.gamut") as study, gamut.open("converged_copy.gamut") as copy:
    print("kept ids:", *study.get_row_ids(), "at mach", *(f"{m:g}" for m in study.get_parameter("mach")))
    same = study.describe()["file_id"] == copy.describe()["file_id"]
    print("same file id after the rewrite:", "yes" if same else "no")
print("valid:", "yes" if gamut.validate("converged.gamut").ok else "no")
