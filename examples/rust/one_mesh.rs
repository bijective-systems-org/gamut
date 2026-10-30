// A sweep on one mesh: eight runs written, a ninth added, then read.
//
// Potential flow past a cylinder at nine values of circulation, on one ring
// of quadrilaterals. The Python, MATLAB, Julia and C++ examples of this
// name are the same program and print the same lines.
//
//   cargo run --example one_mesh      (in rust/, with GAMUT_LIB_DIR set)
use std::f64::consts::PI;

const N_THETA: usize = 48;
const N_R: usize = 12;
const N_NODES: usize = N_THETA * N_R;
const N_CELLS: usize = N_THETA * (N_R - 1);

// Stands for the solver: cp at every node for one value of circulation.
fn solve(t: &[f64], r: &[f64], gamma: f64) -> Vec<f64> {
    (0..N_NODES)
        .map(|k| {
            let u_t = -t[k].sin() * (1.0 + 1.0 / (r[k] * r[k])) + gamma / (2.0 * PI * r[k]);
            let u_r = t[k].cos() * (1.0 - 1.0 / (r[k] * r[k]));
            1.0 - (u_r * u_r + u_t * u_t)
        })
        .collect()
}

fn main() -> Result<(), gamut::Error> {
    let t: Vec<f64> = (0..N_NODES).map(|k| 2.0 * PI * (k % N_THETA) as f64 / N_THETA as f64).collect();
    let r: Vec<f64> = (0..N_NODES).map(|k| 6f64.powf((k / N_THETA) as f64 / (N_R - 1) as f64)).collect();
    let points: Vec<f64> = (0..N_NODES).flat_map(|k| [r[k] * t[k].cos(), r[k] * t[k].sin()]).collect();
    let mut cells = gamut::Cells { offsets: vec![0], ..Default::default() };   // VTK quadrilaterals
    for c in 0..N_CELLS as i64 {
        let (a, b) = (c, c - c % N_THETA as i64 + (c + 1) % N_THETA as i64);
        cells.types.push(9);
        cells.connectivity.extend([a, b, b + N_THETA as i64, a + N_THETA as i64]);
        cells.offsets.push(4 * (c + 1));
    }
    let surface: Vec<i64> = (0..N_NODES).map(|k| (k < N_THETA) as i64).collect();   // 1 ("wall") on the first ring

    let mut study = gamut::create("cylinder.gamut", "example sweep", "shared", "fixed")?;
    study.declare_coordinates("m", 2)?;
    study.declare_parameter("gamma", "design", "m2 s-1")?;
    study.declare_mesh_label("surface", "node", &["field", "wall"])?;
    study.declare_field("cp", "node", "1")?;
    study.set_mesh(&points, &cells, &[("surface", &surface)])?;
    for gamma in (0..8).map(|i| 0.5 * i as f64) {
        study.add_run(&[("gamma", gamma.into())], &[("cp", &solve(&t, &r, gamma))])?;
    }
    study.close()?;

    let mut study = gamut::open_append("cylinder.gamut")?;
    study.add_run(&[("gamma", 4.0.into())], &[("cp", &solve(&t, &r, 4.0))])?;
    study.close()?;

    let study = gamut::open("cylinder.gamut")?;
    println!("{} mesh, {} runs, {} nodes", study.type_()?, study.row_count()?, study.get_points(None)?.shape[0]);
    let names = study.categories("surface")?;
    // The code that means "wall" is its place in the table.
    let wall = names.iter().position(|n| n == "wall").unwrap() as i64;
    let label = study.get_mesh_label("surface", None)?;
    let on_wall: Vec<usize> = (0..label.len()).filter(|&k| label[k] == wall).collect();
    let block = study.get_field("cp", .., on_wall)?;   // runs x wall nodes
    let lowest = (0..block.shape[0])
        .map(|run| (0..block.shape[1]).map(|k| block[[run, k]]).fold(f64::INFINITY, f64::min));
    println!("lowest cp on the wall, by run:{}", lowest.map(|v| format!(" {v:.2}")).collect::<String>());
    let top = study.get_field("cp", .., 12)?;   // node 12, the top, in every run
    println!("cp at the top of the cylinder, run by run:{}",
             top.values.iter().map(|v| format!(" {v:.2}")).collect::<String>());
    Ok(())
}
