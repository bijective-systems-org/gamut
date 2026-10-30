// The built-in nearest model of examples/07_models.py, fitted in Python and
// evaluated in Rust. Run that script first, in this folder: it writes
// lift_nearest.gamut. Both print the same lines.
//
//   cargo run --example nearest      (in rust/, with GAMUT_LIB_DIR set)

fn main() -> Result<(), gamut::Error> {
    let (answer, _) = gamut::evaluate("lift_nearest.gamut", &[("alpha", vec![2.2, 7.9].into())], "nearest_answer.gamut")?;
    let lift = answer.get_scalar("cl", ..)?;
    println!("the nearest run's lift at 2.2 and 7.9 degrees:{}",
             lift.iter().map(|v| format!(" {v:.2}")).collect::<String>());

    // An angle outside the range the model was fitted on is evaluated, and
    // reported (W4); the answer says for each row how far outside it lies.
    let (answer, warnings) =
        gamut::evaluate("lift_nearest.gamut", &[("alpha", vec![5.0, 12.0].into())], "nearest_outside.gamut")?;
    for warning in warnings {
        eprintln!("{warning}");
    }
    let outside = answer.outside("alpha", ..)?;
    println!("degrees outside the fitted range:{}", outside.iter().map(|v| format!(" {v}")).collect::<String>());
    Ok(())
}
