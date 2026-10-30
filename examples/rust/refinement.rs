// Runs on different meshes: a refinement study.
//
// The same flow on three meshes of increasing resolution, with the pressure
// stored per cell. examples/04_changing_mesh.py and the MATLAB, Julia and
// C++ examples are the same program and print the same lines.
//
//   cargo run --example refinement      (in rust/, with GAMUT_LIB_DIR set)
mod cylinder;
use cylinder::{pressure, ring};

fn main() -> Result<(), gamut::Error> {
    let mut study = gamut::create("refinement.gamut", "example refinement", "changing", "run")?;
    study.declare_coordinates("m", 2)?;
    study.declare_parameter("cells_round", "design", "1")?;
    study.declare_scalar("cp_min", "1")?;
    study.declare_field("cp", "cell", "1")?;
    for n in [24, 48, 96] {
        let g = ring(n, n / 4, 1.0);
        let (mut t, mut r) = (Vec::new(), Vec::new());   // each cell's centre, in polar coordinates
        for c in g.cells.offsets.windows(2) {
            let (mut x, mut y) = (0.0, 0.0);
            for &k in &g.cells.connectivity[c[0] as usize..c[1] as usize] {
                x += g.points[2 * k as usize];
                y += g.points[2 * k as usize + 1];
            }
            t.push((y / 4.0).atan2(x / 4.0));
            r.push((x / 4.0).hypot(y / 4.0));
        }
        let cp = pressure(&t, &r, 1.0, 0.0);
        let cp_min = cp.iter().copied().fold(f64::INFINITY, f64::min);
        study.add_run_with_geometry(&[("cells_round", (n as f64).into()), ("cp_min", cp_min.into())], &[("cp", &cp)],
                                    &gamut::Geometry { points: &g.points, cells: Some(&g.cells), labels: &[] })?;
    }
    study.close()?;

    let study = gamut::open("refinement.gamut")?;
    let rounds: Vec<f64> = study.get_parameter("cells_round", ..)?;
    for (row, round) in rounds.iter().enumerate() {
        let cells = study.get_cells(Some(row))?;
        let cp = study.get_field("cp", row, ..)?.values;
        println!("{round} cells round: {} nodes, {} cells, lowest cell cp {:.3}",
                 study.get_points(Some(row))?.shape[0], cells.types.len(),
                 cp.iter().copied().fold(f64::INFINITY, f64::min));
    }
    Ok(())
}
