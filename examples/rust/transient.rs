// Transient runs: every saved step is a row.
//
// Two transient runs, each saved at 101 time steps. Time is a parameter with
// the role time, and a group label says which run each step belongs to.
// examples/05_time_series.py and the MATLAB, Julia and C++ examples are the
// same program and print the same lines.
//
//   cargo run --example transient      (in rust/, with GAMUT_LIB_DIR set)
use std::f64::consts::PI;

use gamut::Parameter;

fn main() -> Result<(), gamut::Error> {
    let steps: Vec<f64> = (0..=100).map(|k| 0.1 * k as f64).collect();

    let mut study = gamut::create("transient.gamut", "example transient", "", "")?;
    study.declare_label("run", "group", &[])?;
    study.declare_parameter_with("t", "time", "s", Parameter::default().run_group("run"))?;
    study.declare_parameter("speed", "condition", "m s-1")?;
    study.declare_scalar("cl", "1")?;
    for (name, speed) in [("slow", 20.0), ("fast", 35.0)] {
        let frequency = 0.2 * speed / 10.0;   // shedding, Strouhal 0.2
        let cl: Vec<f64> = steps.iter().map(|t| 0.8 * (2.0 * PI * frequency * t).sin() * (1.0 - (-t).exp())).collect();
        study.add_runs(&[("run", vec![name; steps.len()].into()), ("t", steps.clone().into()),
                         ("speed", vec![speed; steps.len()].into()), ("cl", cl.into())], &[])?;
    }
    study.close()?;

    let study = gamut::open("transient.gamut")?;
    println!("{} rows, {} runs", study.row_count()?, study.categories("run")?.len());
    let fast = study.select("run == fast")?;
    let t: Vec<f64> = study.get_parameter("t", &fast)?;
    let cl = study.get_scalar("cl", &fast)?;
    let peak = (0..cl.len()).fold(0, |p, k| if cl[k].abs() > cl[p].abs() { k } else { p });
    println!("fast run: {} steps, peak |cl| {:.2} at t = {:.1} s", fast.len(), cl[peak].abs(), t[peak]);
    Ok(())
}
