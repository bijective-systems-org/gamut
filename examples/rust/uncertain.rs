// Uncertainty and gradients beside the values they describe.
//
// Each run stores a lift coefficient with its standard deviation and two
// quantiles, and its derivative with respect to angle of attack. Each names
// the result it describes, so a reader finds them without naming conventions.
// examples/06_uncertainty_gradients.py and the MATLAB, Julia and C++
// examples are the same program and print the same lines.
//
//   cargo run --example uncertain      (in rust/, with GAMUT_LIB_DIR set)
use gamut::{derivative_of, quantile_of, std_of};

fn main() -> Result<(), gamut::Error> {
    let alpha: Vec<f64> = (0..=8).map(f64::from).collect();
    let cl: Vec<f64> = alpha.iter().map(|a| 0.11 * a).collect();
    let spread: Vec<f64> = alpha.iter().map(|a| 0.01 + 0.002 * a).collect();
    let p05: Vec<f64> = cl.iter().zip(&spread).map(|(c, s)| c - 1.645 * s).collect();
    let p95: Vec<f64> = cl.iter().zip(&spread).map(|(c, s)| c + 1.645 * s).collect();

    let mut study = gamut::create("uncertain.gamut", "example ensemble", "", "")?;
    study.declare_parameter("alpha", "condition", "degree")?;
    study.declare_scalar("cl", "1")?;
    study.declare_scalar_of("cl_std", "1", std_of("cl"))?;
    study.declare_scalar_of("cl_p05", "1", quantile_of("cl", 0.05))?;
    study.declare_scalar_of("cl_p95", "1", quantile_of("cl", 0.95))?;
    study.declare_scalar_of("dcl_dalpha", "degree-1", derivative_of("cl", "alpha"))?;
    study.add_runs(&[("alpha", alpha.into()), ("cl", cl.into()), ("cl_std", spread.into()), ("cl_p05", p05.into()),
                     ("cl_p95", p95.into()), ("dcl_dalpha", vec![0.11; 9].into())], &[])?;
    study.close()?;

    let study = gamut::open("uncertain.gamut")?;
    let related = study.related("cl")?;
    let (q05, q95) = (related.quantile(0.05).unwrap(), related.quantile(0.95).unwrap());
    println!("the std of cl: {}", related.std.as_deref().unwrap_or(""));
    println!("its 0.05 and 0.95 quantiles: {q05} {q95}");
    println!("its derivative with respect to alpha: {}", related.derivatives["alpha"]);
    let (low, high) = (study.get_scalar(q05, ..)?, study.get_scalar(q95, ..)?);
    println!("90 % band at 8 degrees: {:.3} to {:.3}", low[low.len() - 1], high[high.len() - 1]);
    Ok(())
}
