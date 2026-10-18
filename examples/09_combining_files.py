"""Growing, splitting and rewriting files.

`append` adds one file's runs to another (the same declarations; category
names merged); `extract` keeps chosen runs as a new file, their ids kept;
`write_copy` rewrites a file with the default layout, keeping its identity.
"""
import mestra


def sweep(path, machs):
    with mestra.create(path, writer="example sweep",
                       parameters={"mach": {"units": "1", "role": "condition"}},
                       labels={"status": {"role": "status", "categories": ["converged", "failed"]}},
                       scalars={"cd": "1"}) as study:
        for mach in machs:
            study.add_run({"mach": mach, "status": "failed" if mach > 0.85 else "converged",
                           "cd": 0.01 + 0.05 * max(0.0, mach - 0.7) ** 2})


sweep("monday.mes", [0.5, 0.6, 0.7])
sweep("tuesday.mes", [0.8, 0.9])
print("appended", mestra.append("monday.mes", "tuesday.mes"), "runs")

with mestra.open("monday.mes") as study:
    good = study.select("status == converged")
mestra.extract("monday.mes", "converged.mes", good)
mestra.write_copy("converged.mes", "converged_copy.mes")

with mestra.open("converged.mes") as study, mestra.open("converged_copy.mes") as copy:
    print("kept ids:", study.get_row_ids(), "mach:", study.get_parameter("mach"))
    print("same file id after the rewrite:", study.describe()["file_id"] == copy.describe()["file_id"])
print("valid:", mestra.validate("converged.mes").ok)
