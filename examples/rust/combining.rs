// Growing, splitting and rewriting files.
//
// gamut::append adds one file's runs to another (the same declarations;
// category names merged); gamut::extract keeps chosen runs as a new file,
// their ids kept; gamut::write_copy rewrites a file with the default layout,
// keeping its identity. examples/09_combining_files.py and the MATLAB, Julia
// and C++ examples are the same program and print the same lines.
//
//   cargo run --example combining      (in rust/, with GAMUT_LIB_DIR set)

fn sweep(path: &str, machs: &[f64]) -> Result<(), gamut::Error> {
    let mut study = gamut::create(path, "example sweep", "", "")?;
    study.declare_parameter("mach", "condition", "1")?;
    study.declare_label("status", "status", &["converged", "failed"])?;
    study.declare_scalar("cd", "1")?;
    for &mach in machs {
        let excess = (mach - 0.7).max(0.0);
        let status = if mach > 0.85 { "failed" } else { "converged" };
        study.add_run(&[("mach", mach.into()), ("status", status.into()), ("cd", (0.01 + 0.05 * excess * excess).into())],
                      &[])?;
    }
    study.close()
}

fn main() -> Result<(), gamut::Error> {
    sweep("monday.gamut", &[0.5, 0.6, 0.7])?;
    sweep("tuesday.gamut", &[0.8, 0.9])?;
    println!("appended {} runs", gamut::append("monday.gamut", "tuesday.gamut")?);

    let good = gamut::open("monday.gamut")?.select("status == converged")?;
    gamut::extract("monday.gamut", "converged.gamut", good)?;
    gamut::write_copy("converged.gamut", "converged_copy.gamut")?;

    let (study, copy) = (gamut::open("converged.gamut")?, gamut::open("converged_copy.gamut")?);
    let ids = study.get_row_ids(..)?;
    let machs: Vec<f64> = study.get_parameter("mach", ..)?;
    println!("kept ids:{} at mach{}", ids.iter().map(|id| format!(" {id}")).collect::<String>(),
             machs.iter().map(|m| format!(" {m}")).collect::<String>());
    let same = study.describe("")?["file_id"] == copy.describe("")?["file_id"];
    println!("same file id after the rewrite: {}", if same { "yes" } else { "no" });
    println!("valid: {}", if gamut::validate("converged.gamut")?.ok { "yes" } else { "no" });
    Ok(())
}
