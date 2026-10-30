// A study with no mesh: a table of runs, each with its inputs and results.
// A sweep of a wing over Mach number and angle of attack.
// examples/01_run_table.py and the MATLAB, Julia and C++ examples are the
// same program and print the same lines.
//
//   cargo run --example run_table      (in rust/, with GAMUT_LIB_DIR set)

fn main() -> Result<(), gamut::Error> {
    let mut study = gamut::create("polar.gamut", "example sweep", "", "")?;
    study.declare_parameter("mach", "condition", "1")?;
    study.declare_parameter("alpha", "condition", "degree")?;
    study.declare_label("status", "status", &["converged", "failed"])?;
    study.declare_scalar("cl", "1")?;
    study.declare_scalar("cd", "1")?;
    study.set_constant("reference_area", 12.5, "m2")?;
    study.set_attribute("title", "Wing A polar")?;
    for mach in [0.6_f64, 0.7, 0.8] {
        for alpha in (-2..=8).step_by(2).map(f64::from) {
            let cl = 0.11 * alpha / (1.0 - mach * mach).sqrt(); // stand-in for a solver
            let cd = 0.008 + 0.04 * cl * cl;
            let failed = mach == 0.8 && alpha == 8.0;
            study.add_run(&[("mach", mach.into()), ("alpha", alpha.into()),
                            ("status", if failed { "failed" } else { "converged" }.into()),
                            ("cl", if failed { f64::NAN } else { cl }.into()),
                            ("cd", if failed { f64::NAN } else { cd }.into())], &[])?;
        }
    }
    study.close()?;

    let study = gamut::open("polar.gamut")?;
    println!("{} runs; {}", study.row_count()?, study.describe("")?["title"]);
    let cl = study.get_scalar("cl", study.select("mach == 0.7")?)?;
    println!("lift at Mach 0.7:{}", cl.iter().map(|v| format!(" {v:.3}")).collect::<String>());
    let failed = study.select("status == failed")?;
    let mach: Vec<f64> = study.get_parameter("mach", failed.clone())?;
    let alpha: Vec<f64> = study.get_parameter("alpha", failed)?;
    println!("failed: Mach {:.1}, alpha {} degree", mach[0], alpha[0]);
    println!("reference area: {} {}", study.get_constant::<f64>("reference_area")?,
             study.describe("reference_area")?["units"]);
    Ok(())
}
