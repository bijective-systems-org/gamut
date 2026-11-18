// Write three runs to first.gamut and read back the lift coefficients.
//
//   cargo run --example sweep      (in rust/, with GAMUT_LIB_DIR set)

fn main() -> Result<(), gamut::Error> {
    // Values at the same position belong to the same run.
    let alpha = vec![0.0, 2.0, 4.0];
    let cl = vec![0.0, 0.22, 0.44];

    let mut study = gamut::create("first.gamut", "example sweep", "", "")?;
    study.declare_parameter("alpha", "condition", "degree")?;
    study.declare_scalar("cl", "1")?;
    study.add_runs(&[("alpha", alpha.into()), ("cl", cl.into())], &[])?;
    study.close()?;

    let study = gamut::open("first.gamut")?;
    let lift = study.get_scalar("cl", gamut::Selection::All)?;

    print!("cl:");
    for value in lift {
        print!(" {value:.2}");
    }
    println!();
    Ok(())
}
