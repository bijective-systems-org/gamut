// A sweep of a wing's angle of attack: six runs written, a seventh added,
// then read. The six are written at once, as columns. examples/00_readme.py
// and the MATLAB, Julia and C++ examples are the same program and print the
// same line.
//
//   cargo run --example sweep      (in rust/, with GAMUT_LIB_DIR set)

fn main() -> Result<(), gamut::Error> {
    let alpha = vec![0.0, 2.0, 4.0, 6.0, 8.0, 10.0];   // angles of attack, degrees
    let cl: Vec<f64> = alpha.iter().map(|a| 0.11 * a).collect();   // stands for the solver's lift coefficients

    let mut study = gamut::create("sweep.gamut", "example sweep", "", "")?;
    study.declare_parameter("alpha", "condition", "degree")?;
    study.declare_label("status", "status", &["converged", "failed"])?;
    study.declare_scalar("cl", "1")?;
    let status = vec!["converged"; alpha.len()];
    study.add_runs(&[("alpha", alpha.into()), ("cl", cl.into()), ("status", status.into())], &[])?;
    study.close()?;

    let mut study = gamut::open_append("sweep.gamut")?;
    study.add_run(&[("alpha", 12.0.into()), ("status", "failed".into())], &[])?;
    study.close()?;

    let study = gamut::open("sweep.gamut")?;
    let lift = study.get_scalar("cl", study.select("status == converged")?)?;
    println!("lift of the runs that converged:{}", lift.iter().map(|v| format!(" {v:.2}")).collect::<String>());
    Ok(())
}
