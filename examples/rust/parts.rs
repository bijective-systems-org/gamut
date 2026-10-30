// Reading only what you need: rows by condition, nodes by zone.
//
// Runs are chosen with a small expression language and nodes by a mesh
// label. Values arrive in the units they were stored in; this program
// converts them itself, where Python's reads convert on request.
// examples/08_selecting_parts.py and the MATLAB, Julia and C++ examples are
// the same program and print the same lines.
//
//   cargo run --example parts      (in rust/, with GAMUT_LIB_DIR set)
mod cylinder;
use cylinder::{pressure, ring};

fn main() -> Result<(), gamut::Error> {
    let g = ring(48, 12, 1.0);
    let r_wall = g.r.iter().copied().fold(f64::INFINITY, f64::min);
    let surface: Vec<i64> = g.r.iter().map(|&r| (r == r_wall) as i64).collect();   // 1 on the wall

    let mut study = gamut::create("parts.gamut", "example parts", "shared", "fixed")?;
    study.declare_coordinates("m", 2)?;
    study.declare_parameter("gamma", "condition", "m2 s-1")?;
    study.declare_parameter("speed", "condition", "m s-1")?;
    study.declare_label("status", "status", &["converged", "failed"])?;
    study.declare_mesh_label("surface", "node", &["field", "wall"])?;
    study.declare_field("p", "node", "Pa")?;
    study.set_mesh(&g.points, &g.cells, &[("surface", &surface)])?;
    for speed in [10.0, 20.0, 40.0] {
        for gamma in [0.0, 2.0, 4.0] {
            let q = 0.5 * 1.225 * speed * speed;   // dynamic pressure, air at sea level
            let p: Vec<f64> = pressure(&g.t, &g.r, 1.0, gamma).iter().map(|v| v * q).collect();
            study.add_run(&[("gamma", gamma.into()), ("speed", speed.into()), ("status", "converged".into())],
                          &[("p", &p)])?;
        }
    }
    study.close()?;

    let study = gamut::open("parts.gamut")?;
    let rows = study.select("speed >= 20 and gamma > 1 and status == converged")?;
    println!("chosen: {} runs", rows.len());
    let names = study.categories("surface")?;
    let wall = names.iter().position(|n| n == "wall").unwrap() as i64;
    let label = study.get_mesh_label("surface", None)?;
    let on_wall: Vec<usize> = (0..label.len()).filter(|&k| label[k] == wall).collect();
    let p_wall = study.get_field("p", &rows, on_wall)?;   // stored in Pa
    let lowest = p_wall.values.iter().copied().fold(f64::INFINITY, f64::min) / 1000.0;
    println!("wall pressure: {} runs x {} nodes, lowest {lowest:.3} kPa", p_wall.shape[0], p_wall.shape[1]);
    let speeds: Vec<f64> = study.get_parameter("speed", &rows)?;   // stored in m s-1
    println!("speeds in km/h:{}", speeds.iter().map(|v| format!(" {:.1}", v * 3.6)).collect::<String>());
    Ok(())
}
