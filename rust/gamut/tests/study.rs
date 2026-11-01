//! The crate's own behaviour over the core: what it converts, what it
//! refuses before the core, and what reaches the caller as an Error.
use gamut::{quantile_of, std_of, Column, Parameter, Selection};

// A folder of its own per test, removed at the end.
struct Folder(std::path::PathBuf);

impl Folder {
    fn new(name: &str) -> Folder {
        let dir = std::env::temp_dir().join(format!("gamut-rust-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        Folder(dir)
    }
    fn path(&self, file: &str) -> String {
        self.0.join(file).to_str().unwrap().to_string()
    }
}

impl Drop for Folder {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn polar(path: &str) -> Result<(), gamut::Error> {
    let mut s = gamut::create(path, "tests", "", "")?;
    s.declare_parameter_with("alpha", "condition", "degree", Parameter::default().bounds(0.0, 4.0))?;
    s.declare_parameter_with("seed", "design", "1", Parameter::default().int64())?;
    s.declare_label("status", "status", &["converged", "failed"])?;
    s.declare_scalar("cl", "1")?;
    s.declare_scalar_of("cl_std", "1", std_of("cl"))?;
    s.declare_scalar_of("cl_p95", "1", quantile_of("cl", 0.95))?;
    s.set_constant("area", 2.5, "m2")?;
    s.add_runs(&[("alpha", vec![0.0, 2.0, 4.0, 6.0].into()), ("seed", vec![1i64, 2, 3, 1 << 60].into()),
                 ("status", vec!["converged", "converged", "failed", "converged"].into()),
                 ("cl", vec![0.0, 0.22, f64::NAN, 0.66].into()), ("cl_std", vec![0.01; 4].into()),
                 ("cl_p95", vec![0.1; 4].into())], &[])?;
    s.close()
}

#[test]
fn reads_come_back_as_written() {
    let dir = Folder::new("reads");
    let path = dir.path("polar.gamut");
    polar(&path).unwrap();
    let s = gamut::open(&path).unwrap();
    assert_eq!(s.row_count().unwrap(), 4);
    assert_eq!((s.kind().unwrap().as_str(), s.type_().unwrap().as_str()), ("data", "table"));
    assert_eq!(s.names("parameters").unwrap(), ["alpha", "seed"]);
    assert_eq!(s.get_parameter::<i64>("seed", ..).unwrap()[3], 1 << 60);   // past 2^53, exactly
    assert_eq!(s.get_parameter::<f64>("alpha", 1..3).unwrap(), [2.0, 4.0]);
    assert_eq!(s.get_parameter::<f64>("alpha", vec![0, 3]).unwrap(), [0.0, 6.0]);
    assert_eq!(s.get_parameter::<f64>("alpha", Selection::Positions(vec![])).unwrap(), Vec::<f64>::new());
    assert_eq!(s.get_label("status", 2).unwrap(), ["failed"]);
    assert_eq!(s.select("status == converged and alpha > 1").unwrap(), [1, 3]);
    assert_eq!(s.outside("alpha", ..).unwrap(), [0.0, 0.0, 0.0, 2.0]);
    assert_eq!(s.get_constant::<f64>("area").unwrap(), 2.5);
    assert_eq!(s.get_row_ids(..).unwrap(), [0, 1, 2, 3]);
    assert!(s.get_scalar("cl", ..).unwrap()[2].is_nan());
    assert!(s.set_threads(usize::MAX).is_err());   // more than a C int, refused rather than cut
    let related = s.related("cl").unwrap();
    assert_eq!((related.std.as_deref(), related.quantile(0.95)), (Some("cl_std"), Some("cl_p95")));
    assert!(gamut::validate(&path).unwrap().ok);
}

#[test]
fn refusals_carry_the_rule() {
    let dir = Folder::new("refusals");
    let path = dir.path("polar.gamut");
    polar(&path).unwrap();
    // The core's refusals, with their rules.
    let again = gamut::create(&path, "tests", "", "").err().unwrap();   // never replaces a file
    assert!(again.message().contains("never replaced"), "{again}");
    let s = gamut::open(&path).unwrap();
    assert!(s.get_scalar("nothing", ..).is_err());
    // A type that would round or truncate is refused rather than converted.
    let e = s.get_parameter::<f64>("seed", ..).err().unwrap();
    assert_eq!(e.message(), "seed is stored as int64; read it as i64");
    assert!(s.get_parameter::<i64>("alpha", ..).is_err());
    // A file open to read takes no runs; a NUL in a name is refused here.
    let mut s = s;
    assert!(s.add_run(&[("alpha", 1.0.into())], &[]).is_err());
    assert!(s.describe("a\0b").is_err());
    // Columns of different lengths are refused before the core is asked.
    let mut w = gamut::create(&dir.path("short.gamut"), "tests", "", "").unwrap();
    w.declare_parameter("x", "design", "1").unwrap();
    w.declare_scalar("y", "1").unwrap();
    let e = w.add_runs(&[("x", vec![1.0, 2.0].into()), ("y", Column::Float(vec![1.0]))], &[]).err().unwrap();
    assert_eq!(e.rule(), "E5");
    // A shared mesh never set: close says so, and the file stays open to fix.
    let mut m = gamut::create(&dir.path("mesh.gamut"), "tests", "shared", "fixed").unwrap();
    m.declare_coordinates("m", 2).unwrap();
    assert!(m.close().is_err());
    m.abandon(true);
    assert!(!std::path::Path::new(&dir.path("mesh.gamut")).exists());
}

#[test]
fn only_a_model_file_is_evaluated() {
    // examples/rust/nearest.rs evaluates the built-in model under the page check.
    let dir = Folder::new("evaluate");
    let data = dir.path("polar.gamut");
    polar(&data).unwrap();
    let e = gamut::evaluate(&data, &[("alpha", vec![1.0].into())], &dir.path("a.gamut")).err().unwrap();
    assert_eq!(e.rule(), "E16");
    assert!(!std::path::Path::new(&dir.path("a.gamut")).exists());
}

#[test]
#[should_panic(expected = "outside an array of shape [2, 2]")]
fn an_array_index_stays_in_its_row() {
    let a = gamut::Array { shape: vec![2, 2], values: vec![10.0, 20.0, 30.0, 40.0] };
    let _ = a[[0, 2]];
}

// The notice's sink is the process's: tests that set it take turns.
static SINK: std::sync::Mutex<()> = std::sync::Mutex::new(());

// A marked source into an unmarked file is refused (E27) and the file left
// as it was; append_marked states the result's marking. The notice reaches
// the sink once per file, and again once a sink is set; a panicking sink
// does not unwind into the core.
#[test]
fn marked_appends_and_the_notice() -> Result<(), gamut::Error> {
    let _turn = SINK.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
    let dir = Folder::new("marking");
    let (marked, plain) = (dir.path("marked.gamut"), dir.path("plain.gamut"));
    for (path, marking) in [(&marked, "PLACEHOLDER-A"), (&plain, "")] {
        let mut s = gamut::create(path, "tests", "", "")?;
        if !marking.is_empty() {
            s.set_attribute("portion_marking", marking)?;
        }
        s.declare_parameter("x", "design", "1")?;
        s.add_run(&[("x", 1.0.into())], &[])?;
        s.close()?;
    }
    let shown = std::sync::Arc::new(std::sync::Mutex::new(Vec::<(String, String)>::new()));
    let into = shown.clone();
    gamut::set_marking_notice(Some(Box::new(move |path, text| {
        into.lock().unwrap().push((path.to_string(), text.to_string()))
    })));
    let before = std::fs::read(&plain).unwrap();
    assert_eq!(gamut::append(&plain, &marked).unwrap_err().rule(), "E27");
    assert_eq!(std::fs::read(&plain).unwrap(), before);
    {
        let got = shown.lock().unwrap();
        assert_eq!(got.len(), 1);
        assert_eq!(got[0].0, marked);
        assert!(got[0].1.contains("carries a portion marking") && got[0].1.contains("\nPLACEHOLDER-A\n"));
    }
    assert_eq!(gamut::append_marked(&plain, &marked, "PLACEHOLDER-B")?, 1);
    assert_eq!(gamut::open(&plain)?.describe("")?["portion_marking"], "PLACEHOLDER-B");
    assert!(gamut::append_marked(&plain, &marked, "").is_err());
    gamut::open(&marked)?;
    assert_eq!(shown.lock().unwrap().len(), 2);       // plain, now marked; marked was shown
    gamut::set_marking_notice(Some(Box::new(|_, _| panic!("a broken sink"))));
    gamut::open(&marked)?;
    gamut::set_marking_notice(Some(Box::new(|_, _| {})));
    gamut::open(&marked)?;
    gamut::set_marking_notice(None);
    Ok(())
}
