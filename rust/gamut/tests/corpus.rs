//! Holds the Rust crate to the corpus written by corpus/generate.py: the same
//! cases and expected answers as the Python, MATLAB and Julia checkers.
//!
//!   python corpus/generate.py DIR && GAMUT_CORPUS=DIR cargo test --test corpus
use std::collections::BTreeSet;
use std::path::Path;

use gamut::{Column, Element, Selection, Study};
use serde_json::Value as Json;

// expected.json as Python writes it: NaN and Infinity as bare tokens, which
// JSON proper has no words for, are made strings first.
fn read_expected(path: &Path) -> Json {
    let text = std::fs::read_to_string(path).expect("expected.json");
    let (mut out, mut in_string, mut escaped) = (String::new(), false, false);
    let mut rest = text.as_str();
    while let Some(ch) = rest.chars().next() {
        if !in_string {
            if let Some(word) = ["-Infinity", "Infinity", "NaN"].into_iter().find(|w| rest.starts_with(w)) {
                out.push_str(&format!("\"{word}\""));
                rest = &rest[word.len()..];
                continue;
            }
        }
        if in_string && !escaped && ch == '\\' {
            escaped = true;
        } else {
            if ch == '"' && !escaped {
                in_string = !in_string;
            }
            escaped = false;
        }
        out.push(ch);
        rest = &rest[ch.len_utf8()..];
    }
    serde_json::from_str(&out).expect("expected.json parses")
}

fn number(v: &Json) -> f64 {
    match v {
        Json::String(s) if s == "NaN" => f64::NAN,
        Json::String(s) if s == "Infinity" => f64::INFINITY,
        Json::String(s) if s == "-Infinity" => f64::NEG_INFINITY,
        _ => v.as_f64().expect("a number"),
    }
}

// A nested list as its shape and its values in C order.
fn flatten(v: &Json, shape: &mut Vec<usize>, depth: usize, out: &mut Vec<Json>) {
    match v {
        Json::Array(items) => {
            if shape.len() == depth {
                shape.push(items.len());
            }
            for item in items {
                flatten(item, shape, depth + 1, out);
            }
        }
        other => out.push(other.clone()),
    }
}

fn selection(v: Option<&Json>) -> Selection {
    match v {
        None | Some(Json::Null) => Selection::All,
        Some(Json::Array(items)) => items.iter().map(|k| k.as_u64().unwrap() as usize).collect::<Vec<_>>().into(),
        Some(k) => Selection::from(k.as_u64().unwrap() as usize),
    }
}

fn column(v: &Json) -> Column {
    let items = v.as_array().unwrap();
    if items.first().is_some_and(Json::is_string) {
        Column::Names(items.iter().map(|s| s.as_str().unwrap().to_string()).collect())
    } else {
        Column::Float(items.iter().map(number).collect())
    }
}

fn inputs(v: &Json) -> Vec<(String, Column)> {
    v.as_object().unwrap().iter().map(|(k, v)| (k.clone(), column(v))).collect()
}

fn evaluate(path: &str, given: &[(String, Column)], tmp: &Path) -> Result<Study, gamut::Error> {
    let out = tmp.join("answer.gamut");
    let _ = std::fs::remove_file(&out);
    let named: Vec<(&str, Column)> = given.iter().map(|(k, c)| (k.as_str(), c.clone())).collect();
    Ok(gamut::evaluate(path, &named, out.to_str().unwrap())?.0)
}

fn described(f: &Study, p: &Json) -> Option<String> {
    let key = p["describe"].as_str().unwrap();
    let got = f.describe("").ok()?.remove(key);
    let want = p["value"].as_str().map(String::from);
    (got != want).then(|| format!("describe {key}: {got:?} != {want:?}"))
}

fn same<T: Element + PartialEq>(f: &Study, p: &Json, want: &[Json], shape: &[usize], bits: impl Fn(T) -> u64,
                                from: impl Fn(&Json) -> T) -> Option<String> {
    let name = p["read"].as_str().unwrap();
    let got = match f.read::<T>(name, selection(p.get("rows")), selection(p.get("sites"))) {
        Ok(got) => got,
        Err(e) => return Some(format!("read {name}: {e}")),
    };
    if got.shape != shape {
        return Some(format!("read {name}: shape {:?} != {shape:?}", got.shape));
    }
    let want: Vec<u64> = want.iter().map(|v| bits(from(v))).collect();
    let got: Vec<u64> = got.values.into_iter().map(bits).collect();
    (got != want).then(|| format!("read {name}: {got:?} != {want:?} (as bits)"))
}

fn probe(path: &str, p: &Json, tmp: &Path) -> Option<String> {
    if let Some(given) = p.get("evaluate") {
        let out = match evaluate(path, &inputs(given), tmp) {
            Ok(out) => out,
            Err(e) => return Some(format!("evaluate: {e}")),
        };
        if p.get("describe").is_some() {
            return described(&out, p);
        }
        let name = p["scalar"].as_str().unwrap();
        let got = out.get_scalar(name, ..).ok()?;
        let want: Vec<f64> = p["values"].as_array().unwrap().iter().map(number).collect();
        return (got != want).then(|| format!("evaluate {name}: {got:?} != {want:?}"));
    }
    if let Some(how) = p.get("copy") {
        let dst = tmp.join("copy.gamut");
        let _ = std::fs::remove_file(&dst);
        let dst = dst.to_str().unwrap();
        let done = if how == "extract" {
            gamut::extract(path, dst, selection(p.get("rows")))
        } else {
            gamut::write_copy(path, dst)
        };
        if let Err(e) = done {
            return Some(format!("copy: {e}"));
        }
        return described(&gamut::open(dst).ok()?, p);
    }
    let f = match gamut::open(path) {
        Ok(f) => f,
        Err(e) => return Some(format!("open: {e}")),
    };
    if p.get("describe").is_some() {
        return described(&f, p);
    }
    if let Some(info) = p.get("info").and_then(Json::as_str) {
        let got = match info {
            "type" => Json::from(f.type_().ok()?),
            "kind" => Json::from(f.kind().ok()?),
            "addons" => Json::from(f.addons().ok()?),
            other => return Some(format!("no info {other} here")),
        };
        return (got != p["value"]).then(|| format!("{info}: {got} != {}", p["value"]));
    }
    if let Some(label) = p.get("label").and_then(Json::as_str) {
        let got = f.get_label(label, selection(p.get("rows"))).ok()?;
        return (Json::from(got.clone()) != p["names"]).then(|| format!("label {label}: {got:?} != {}", p["names"]));
    }
    if let Some(condition) = p.get("select").and_then(Json::as_str) {
        let got = f.select(condition).ok()?;
        return (Json::from(got.clone()) != p["positions"]).then(|| format!("select: {got:?} != {}", p["positions"]));
    }
    let (mut shape, mut want) = (Vec::new(), Vec::new());
    flatten(&p["values"], &mut shape, 0, &mut want);
    match p["dtype"].as_str().unwrap() {
        "float64" => same::<f64>(&f, p, &want, &shape, f64::to_bits, number),
        "float32" => same::<f32>(&f, p, &want, &shape, |v| v.to_bits() as u64, |v| number(v) as f32),
        "int64" => same::<i64>(&f, p, &want, &shape, |v| v as u64, |v| v.as_i64().unwrap()),
        "int32" => same::<i32>(&f, p, &want, &shape, |v| v as u32 as u64, |v| v.as_i64().unwrap() as i32),
        "uint8" => same::<u8>(&f, p, &want, &shape, u64::from, |v| v.as_u64().unwrap() as u8),
        "int8" => same::<i8>(&f, p, &want, &shape, |v| v as u8 as u64, |v| v.as_i64().unwrap() as i8),
        other => Some(format!("no dtype {other} here")),
    }
}

// Opened and read without a crash: a refusal is an Error, with the expected
// rule when the case names one.
fn hostile(path: &str, e: &Json, tmp: &Path) -> Option<String> {
    let opened = gamut::open(path).and_then(|f| {
        f.names("parameters")?;
        for r in e.get("reads").and_then(Json::as_array).into_iter().flatten() {
            let _ = if let Some(label) = r.get("label").and_then(Json::as_str) {
                f.get_label(label, ..).map(drop)
            } else if let Some(row) = r.get("cells").and_then(Json::as_u64) {
                f.get_cells(Some(row as usize)).map(drop)
            } else if let Some(condition) = r.get("select").and_then(Json::as_str) {
                f.select(condition).map(drop)
            } else if let Some(name) = r.get("scalar").and_then(Json::as_str) {
                f.get_scalar(name, ..).map(drop)
            } else if let Some(given) = r.get("evaluate") {
                evaluate(path, &inputs(given), tmp).map(drop)
            } else {
                Ok(())
            };
        }
        Ok(())
    });
    match (opened, e.get("refused").and_then(Json::as_str)) {
        (Ok(()), Some(rule)) => Some(format!("opened; expected refusal {rule}")),
        (Err(x), Some(rule)) if x.rule() != rule => Some(format!("refused with {:?}, expected {rule}: {x}", x.rule())),
        _ => None,
    }
}

#[test]
fn corpus() {
    let Ok(dir) = std::env::var("GAMUT_CORPUS") else {
        eprintln!("GAMUT_CORPUS is not set: the corpus is not checked");
        return;
    };
    let dir = Path::new(&dir);
    let tmp = std::env::temp_dir().join(format!("gamut-corpus-{}", std::process::id()));
    std::fs::create_dir_all(&tmp).unwrap();
    let expected = read_expected(&dir.join("expected.json"));
    let (mut failures, mut counts) = (Vec::new(), [0usize; 3]);
    for (name, e) in expected.as_object().unwrap() {
        let path = dir.join(format!("{name}.gamut"));
        let path = path.to_str().unwrap();
        let group = e["group"].as_str().unwrap();
        counts[["valid", "rules", "hostile"].iter().position(|g| *g == group).unwrap()] += 1;
        let report = match gamut::validate(path) {
            Ok(r) => r,
            Err(x) => {
                failures.push(format!("{name}: validate refused: {x}"));
                continue;
            }
        };
        let findings: Vec<_> = report.errors.iter().chain(&report.warnings).collect();
        let found: BTreeSet<&str> = findings.iter().map(|f| f.rule.as_str()).collect();
        if group == "valid" {
            if !findings.is_empty() {
                failures.push(format!("{name}: a valid file drew {findings:?}"));
            }
            for p in e.get("probes").and_then(Json::as_array).into_iter().flatten() {
                if let Some(why) = probe(path, p, &tmp) {
                    failures.push(format!("{name}: {why}"));
                }
            }
        } else {
            // A rule case breaks exactly its rules; a hostile case may draw more.
            let want: BTreeSet<&str> = e["rules"].as_array().unwrap().iter().map(|r| r.as_str().unwrap()).collect();
            let wrong = if group == "rules" { found != want } else { !want.is_subset(&found) };
            if wrong {
                failures.push(format!("{name}: expected {want:?}, found {found:?}"));
            }
            if group == "hostile" {
                if let Some(why) = hostile(path, e, &tmp) {
                    failures.push(format!("{name}: {why}"));
                }
            }
        }
    }
    std::fs::remove_dir_all(&tmp).ok();
    let failed: BTreeSet<&str> = failures.iter().map(|f| f.split(':').next().unwrap()).collect();
    let total: usize = counts.iter().sum();
    println!("{total} cases ({} valid, {} rule, {} hostile): {} hold", counts[0], counts[1], counts[2],
             total - failed.len());
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}
