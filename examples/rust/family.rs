// A family of geometries that share one mesh topology.
//
// Three cylinders of different radius, meshed with the same topology, so
// node k is the same place on every member, each run at three circulations.
// examples/03_geometry_family.py and the MATLAB, Julia and C++ examples are
// the same program and print the same lines.
//
//   cargo run --example family      (in rust/, with GAMUT_LIB_DIR set)
use std::collections::BTreeSet;

mod cylinder;
use cylinder::{pressure, ring};

fn main() -> Result<(), gamut::Error> {
    let members = [("slim", 0.8), ("base", 1.0), ("wide", 1.2)];
    let base = ring(48, 12, 1.0);

    let mut study = gamut::create("family.gamut", "example family", "shared", "group:member")?;
    study.declare_coordinates("m", 2)?;
    study.declare_label("member", "group", &["slim", "base", "wide"])?;
    study.declare_label("split", "split", &["train", "test"])?;
    study.set_generalisation_group("member")?;
    study.declare_parameter("gamma", "condition", "m2 s-1")?;
    study.declare_field("cp", "node", "1")?;
    study.set_mesh_nodes(base.t.len(), &base.cells, &[])?;
    for (name, radius) in members {
        let member = ring(48, 12, radius);
        for gamma in [0.0, 2.0, 4.0] {
            let split = if name == "wide" { "test" } else { "train" };
            study.add_run_with_geometry(&[("member", name.into()), ("gamma", gamma.into()), ("split", split.into())],
                                        &[("cp", &pressure(&member.t, &member.r, radius, gamma))],
                                        &gamut::Geometry { points: &member.points, ..Default::default() })?;
        }
    }
    study.close()?;

    let study = gamut::open("family.gamut")?;
    println!("{} runs on {} members of one topology", study.row_count()?, members.len());
    for (name, _) in members {
        let first = study.select(&format!("member == {name}"))?[0];
        println!("  {name}: first node at x = {:.2} m", study.get_points(Some(first))?[[0, 0]]);
    }
    let first_node = study.get_field("cp", .., 0)?;
    println!("cp at the first node, run by run:{}",
             first_node.values.iter().map(|v| format!(" {v:.2}")).collect::<String>());
    let test = study.select("split == test")?;
    let held: BTreeSet<String> = study.get_label("member", &test)?.into_iter().collect();
    println!("held out for testing: {} runs of {}", test.len(), held.into_iter().collect::<Vec<_>>().join(", "));
    Ok(())
}
