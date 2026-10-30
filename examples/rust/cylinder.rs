// The ring of quadrilaterals around a cylinder that several examples share,
// as examples/_cylinder.py.
use std::f64::consts::PI;

pub struct Ring {
    pub points: Vec<f64>,   // nodes x 2, around each ring first
    pub cells: gamut::Cells, // VTK quadrilaterals
    pub t: Vec<f64>,        // each node's polar coordinates
    pub r: Vec<f64>,
}

pub fn ring(n_theta: usize, n_r: usize, radius: f64) -> Ring {
    let outer: f64 = 6.0;
    let mut g = Ring { points: Vec::new(), cells: gamut::Cells { offsets: vec![0], ..Default::default() },
                       t: Vec::new(), r: Vec::new() };
    for j in 0..n_r {
        for i in 0..n_theta {
            let (t, r) = (2.0 * PI * i as f64 / n_theta as f64, radius * outer.powf(j as f64 / (n_r - 1) as f64));
            g.t.push(t);
            g.r.push(r);
            g.points.extend([r * t.cos(), r * t.sin()]);
        }
    }
    for j in 0..n_r as i64 - 1 {
        for i in 0..n_theta as i64 {
            let n = n_theta as i64;
            let (a, b) = (j * n + i, j * n + (i + 1) % n);
            g.cells.types.push(9);
            g.cells.connectivity.extend([a, b, b + n, a + n]);
            g.cells.offsets.push(g.cells.connectivity.len() as i64);
        }
    }
    g
}

// Pressure coefficient of potential flow past a cylinder with circulation
// gamma, free stream speed 1, at the points with polar coordinates t, r.
pub fn pressure(t: &[f64], r: &[f64], radius: f64, gamma: f64) -> Vec<f64> {
    t.iter()
        .zip(r)
        .map(|(&t, &r)| {
            let u_r = t.cos() * (1.0 - radius * radius / (r * r));
            let u_t = -t.sin() * (1.0 + radius * radius / (r * r)) + gamma / (2.0 * PI * r);
            1.0 - (u_r * u_r + u_t * u_t)
        })
        .collect()
}
