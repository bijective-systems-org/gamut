//! Gamut files from Rust: the C interface of the Gamut core in Rust terms.
//!
//! A [`Study`] owns an open file and closes it when it is dropped; a refused
//! call returns an [`Error`] with the rule of the specification it concerns,
//! the path of what it concerns and a message. Names follow the Python
//! package (`create`, `open`, `add_run`, `get_field`, `select`, `describe`),
//! positions count from 0, and arrays come back in C order.
//!
//! ```no_run
//! let mut study = gamut::create("polar.gamut", "example sweep", "", "")?;
//! study.declare_parameter("alpha", "condition", "degree")?;
//! study.declare_scalar("cl", "1")?;
//! for alpha in [0.0, 2.0, 4.0] {
//!     study.add_run(&[("alpha", alpha.into()), ("cl", (0.11 * alpha).into())], &[])?;
//! }
//! study.close()?;
//!
//! let study = gamut::open("polar.gamut")?;
//! println!("{:?}", study.get_scalar("cl", ..)?);
//! # Ok::<(), gamut::Error>(())
//! ```
//!
//! The core is a shared library this crate links: set `GAMUT_LIB_DIR` to the
//! `lib` folder of a released core when building, and let the program find
//! it when it runs (an rpath, or the library path).

use std::collections::BTreeMap;
use std::ffi::{CStr, CString};
use std::fmt;
use std::ops::{Index, Range, RangeFull};
use std::os::raw::{c_char, c_int};
use std::ptr;

use gamut_sys as sys;

/// A refused call: the rule of the specification it concerns ("E7", or
/// empty), the path of what it concerns ("node_fields/p", or empty), and a
/// message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Error {
    rule: String,
    path: String,
    message: String,
}

impl Error {
    fn new(rule: &str, message: impl Into<String>) -> Error {
        Error { rule: rule.into(), path: String::new(), message: message.into() }
    }
    fn from_c(e: &sys::gamut_error) -> Error {
        Error { rule: text(&e.rule), path: text(&e.path), message: text(&e.message) }
    }
    pub fn rule(&self) -> &str {
        &self.rule
    }
    pub fn path(&self) -> &str {
        &self.path
    }
    pub fn message(&self) -> &str {
        &self.message
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.rule.is_empty() {
            f.write_str(&self.message)
        } else {
            write!(f, "{}: {}", self.rule, self.message)
        }
    }
}

impl std::error::Error for Error {}

pub type Result<T> = std::result::Result<T, Error>;

fn text(chars: &[c_char]) -> String {
    let bytes: Vec<u8> = chars.iter().take_while(|&&c| c != 0).map(|&c| c as u8).collect();
    String::from_utf8_lossy(&bytes).into_owned()
}

fn blank() -> sys::gamut_error {
    sys::gamut_error { rule: [0; 8], path: [0; 512], message: [0; 2048] }
}

// Calls f with an error record, and turns a refusal into an Error.
fn call(f: impl FnOnce(*mut sys::gamut_error) -> c_int) -> Result<()> {
    let mut e = blank();
    if f(&mut e) == 0 {
        Ok(())
    } else {
        Err(Error::from_c(&e))
    }
}

fn c(s: &str) -> Result<CString> {
    CString::new(s).map_err(|_| Error::new("", format!("{s:?} holds a NUL character")))
}

fn c_all(items: &[impl AsRef<str>]) -> Result<Vec<CString>> {
    items.iter().map(|s| c(s.as_ref())).collect()
}

fn pointers(items: &[CString]) -> Vec<*const c_char> {
    items.iter().map(|s| s.as_ptr()).collect()
}

fn count(n: usize) -> i64 {
    // A slice never holds more than isize::MAX elements.
    n as i64
}

// A count the C interface takes as an int.
fn int(n: usize, what: &str) -> Result<c_int> {
    c_int::try_from(n).map_err(|_| Error::new("", format!("{what} {n} is more than a C int holds")))
}

// Owns a list of strings from the library until it is dropped.
struct Strings(*mut sys::gamut_strings);

impl Strings {
    fn new() -> Strings {
        Strings(ptr::null_mut())
    }
    fn take(&self) -> Vec<String> {
        if self.0.is_null() {
            return Vec::new();
        }
        let n = unsafe { sys::gamut_strings_count(self.0) };
        (0..n)
            .map(|i| unsafe { CStr::from_ptr(sys::gamut_strings_get(self.0, i)) }.to_string_lossy().into_owned())
            .collect()
    }
}

impl Drop for Strings {
    fn drop(&mut self) {
        unsafe { sys::gamut_strings_free(self.0) }
    }
}

/// Rows, nodes or cells to read: every one (`..`), a range (`2..5`), or
/// strictly increasing positions (`vec![0, 4, 9]`, `&[0, 4, 9][..]`; an
/// empty list selects none), or one position.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Selection {
    All,
    Range(usize, usize),
    Positions(Vec<usize>),
}

impl From<RangeFull> for Selection {
    fn from(_: RangeFull) -> Selection {
        Selection::All
    }
}
impl From<Range<usize>> for Selection {
    fn from(r: Range<usize>) -> Selection {
        Selection::Range(r.start, r.end)
    }
}
impl From<usize> for Selection {
    fn from(k: usize) -> Selection {
        Selection::Positions(vec![k])
    }
}
impl From<Vec<usize>> for Selection {
    fn from(v: Vec<usize>) -> Selection {
        Selection::Positions(v)
    }
}
impl From<&Vec<usize>> for Selection {
    fn from(v: &Vec<usize>) -> Selection {
        Selection::Positions(v.clone())
    }
}
impl From<&[usize]> for Selection {
    fn from(v: &[usize]) -> Selection {
        Selection::Positions(v.to_vec())
    }
}
impl<const N: usize> From<[usize; N]> for Selection {
    fn from(v: [usize; N]) -> Selection {
        Selection::Positions(v.to_vec())
    }
}

// A selection in the C interface's terms, valid while it lives.
struct Sel {
    kind: c_int,
    start: i64,
    stop: i64,
    index: Vec<i64>,
}

impl Sel {
    fn of(s: Selection) -> Sel {
        match s {
            Selection::All => Sel { kind: sys::GAMUT_SEL_ALL, start: 0, stop: 0, index: Vec::new() },
            Selection::Range(a, b) => Sel { kind: sys::GAMUT_SEL_RANGE, start: count(a), stop: count(b), index: Vec::new() },
            Selection::Positions(v) => {
                Sel { kind: sys::GAMUT_SEL_INDEX, start: 0, stop: 0, index: v.into_iter().map(count).collect() }
            }
        }
    }
    fn c(&self) -> sys::gamut_sel {
        sys::gamut_sel {
            kind: self.kind,
            start: self.start,
            stop: self.stop,
            index: self.index.as_ptr(),
            count: count(self.index.len()),
        }
    }
}

/// What a read returns: values in C order and their shape (runs x nodes for
/// a field on a shared mesh). `array[[i, j]]` is the value at row i, column j.
#[derive(Debug, Clone, PartialEq)]
pub struct Array<T> {
    pub shape: Vec<usize>,
    pub values: Vec<T>,
}

impl<T> Index<[usize; 2]> for Array<T> {
    type Output = T;
    fn index(&self, [i, j]: [usize; 2]) -> &T {
        assert!(self.shape.len() == 2 && i < self.shape[0] && j < self.shape[1],
                "[{i}, {j}] is outside an array of shape {:?}", self.shape);
        &self.values[i * self.shape[1] + j]
    }
}

impl<T> Index<usize> for Array<T> {
    type Output = T;
    fn index(&self, i: usize) -> &T {
        &self.values[i]
    }
}

/// Cells in VTK's convention: a type per cell, where each cell's nodes start
/// in connectivity (one more entry than cells), and node numbers from 0.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Cells {
    pub types: Vec<u8>,
    pub offsets: Vec<i64>,
    pub connectivity: Vec<i64>,
}

/// A run's own geometry, when it changes from run to run or from one group
/// member to the next: points as nodes x axes in C order, its cells when
/// they change too, and its mesh labels.
#[derive(Debug, Clone, Default)]
pub struct Geometry<'a> {
    pub points: &'a [f64],
    pub cells: Option<&'a Cells>,
    pub labels: &'a [(&'a str, &'a [i64])],
}

/// What describes a result (spec section 6), from [`Study::related`].
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Related {
    /// Its standard deviation.
    pub std: Option<String>,
    /// Its quantiles, by q, in increasing q.
    pub quantiles: Vec<(f64, String)>,
    /// Its derivatives, by what each is taken with respect to;
    /// "coordinates:x" for node position along x.
    pub derivatives: BTreeMap<String, String>,
    /// The parts of its vector, itself among them.
    pub vector: Vec<String>,
}

impl Related {
    /// The name of its q quantile.
    pub fn quantile(&self, q: f64) -> Option<&str> {
        self.quantiles.iter().find(|(k, _)| *k == q).map(|(_, name)| name.as_str())
    }
}

/// A result's relation to another (spec section 6), made by [`std_of`],
/// [`quantile_of`] or [`derivative_of`].
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Relation {
    of: String,
    statistic: String,
    q: Option<f64>,
    with_respect_to: String,
    axis: String,
}

/// The standard deviation of `of`.
pub fn std_of(of: &str) -> Relation {
    Relation { of: of.into(), statistic: "std".into(), ..Relation::default() }
}

/// The q quantile of `of`, 0 < q < 1.
pub fn quantile_of(of: &str, q: f64) -> Relation {
    Relation { of: of.into(), statistic: "quantile".into(), q: Some(q), ..Relation::default() }
}

/// The derivative of `of` with respect to a parameter, or to "coordinates"
/// along an axis (`.axis("x")`).
pub fn derivative_of(of: &str, with_respect_to: &str) -> Relation {
    Relation { of: of.into(), with_respect_to: with_respect_to.into(), ..Relation::default() }
}

impl Relation {
    /// The axis ("x", "y", "z") of a derivative with respect to coordinates.
    pub fn axis(mut self, axis: &str) -> Relation {
        self.axis = axis.into();
        self
    }
}

/// How a parameter is declared beyond its role and units: int64 for whole
/// numbers such as a count or a seed, the bounds its values lie in (a model
/// file's domain), and for a time parameter the label that groups its rows
/// into runs.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Parameter {
    int64: bool,
    bounds: Option<(f64, f64)>,
    run_group: String,
}

impl Parameter {
    pub fn int64(mut self) -> Parameter {
        self.int64 = true;
        self
    }
    pub fn bounds(mut self, lower: f64, upper: f64) -> Parameter {
        self.bounds = Some((lower, upper));
        self
    }
    pub fn run_group(mut self, label: &str) -> Parameter {
        self.run_group = label.into();
        self
    }
}

/// One run's value of a parameter or scalar (integers stay integers), or
/// its label by name.
#[derive(Debug, Clone, PartialEq)]
pub enum Value {
    Float(f64),
    Int(i64),
    Name(String),
}

impl From<f64> for Value {
    fn from(v: f64) -> Value {
        Value::Float(v)
    }
}
impl From<i64> for Value {
    fn from(v: i64) -> Value {
        Value::Int(v)
    }
}
impl From<&str> for Value {
    fn from(v: &str) -> Value {
        Value::Name(v.into())
    }
}
impl From<String> for Value {
    fn from(v: String) -> Value {
        Value::Name(v)
    }
}

/// Many runs' values of one name, one entry per run.
#[derive(Debug, Clone, PartialEq)]
pub enum Column {
    Float(Vec<f64>),
    Int(Vec<i64>),
    Names(Vec<String>),
}

impl Column {
    fn len(&self) -> usize {
        match self {
            Column::Float(v) => v.len(),
            Column::Int(v) => v.len(),
            Column::Names(v) => v.len(),
        }
    }
}

impl From<Vec<f64>> for Column {
    fn from(v: Vec<f64>) -> Column {
        Column::Float(v)
    }
}
impl From<&[f64]> for Column {
    fn from(v: &[f64]) -> Column {
        Column::Float(v.to_vec())
    }
}
impl From<Vec<i64>> for Column {
    fn from(v: Vec<i64>) -> Column {
        Column::Int(v)
    }
}
impl From<Vec<String>> for Column {
    fn from(v: Vec<String>) -> Column {
        Column::Names(v)
    }
}
impl From<Vec<&str>> for Column {
    fn from(v: Vec<&str>) -> Column {
        Column::Names(v.into_iter().map(String::from).collect())
    }
}

mod sealed {
    pub trait Sealed {}
    impl Sealed for f64 {}
    impl Sealed for f32 {}
    impl Sealed for i64 {}
    impl Sealed for i32 {}
    impl Sealed for u8 {}
    impl Sealed for i8 {}
}

/// An element type a read can return: f64, f32, i64, i32, u8 or i8.
pub trait Element: sealed::Sealed + Copy + Default {
    #[doc(hidden)]
    const DTYPE: c_int;
}
impl Element for f64 {
    const DTYPE: c_int = sys::GAMUT_FLOAT64;
}
impl Element for f32 {
    const DTYPE: c_int = sys::GAMUT_FLOAT32;
}
impl Element for i64 {
    const DTYPE: c_int = sys::GAMUT_INT64;
}
impl Element for i32 {
    const DTYPE: c_int = sys::GAMUT_INT32;
}
impl Element for u8 {
    const DTYPE: c_int = sys::GAMUT_UINT8;
}
impl Element for i8 {
    const DTYPE: c_int = sys::GAMUT_INT8;
}

/// The type a parameter or constant is read as: f64, or i64 for one
/// declared int64.
pub trait Number: Element {
    #[doc(hidden)]
    const INT64: bool;
}
impl Number for f64 {
    const INT64: bool = false;
}
impl Number for i64 {
    const INT64: bool = true;
}

// The limit of docs/security.md on the rows a selection scans, checked here
// too so that a buffer the core would refuse is not allocated first.
const MAX_ROWS_SELECTED: usize = 1 << 27;

/// A file open to write (from [`create`] or [`open_append`]) or to read
/// (from [`open`]).
pub struct Study {
    f: *mut sys::gamut_file,
    writing: bool,
    group: String, // the label whose members own a geometry (per = "group:<label>")
    axes: c_int,
}

// gamut.h: any function may be called from any thread; calls that reach a
// file take turns.
unsafe impl Send for Study {}
unsafe impl Sync for Study {}

impl Drop for Study {
    /// Closes the file; a writer whose close is refused (a shared mesh never
    /// set) is discarded, and a file it created is removed. Call
    /// [`Study::close`] to see the refusal instead.
    fn drop(&mut self) {
        if !self.f.is_null() {
            let mut e = blank();
            unsafe {
                if sys::gamut_close(self.f, &mut e) != 0 {
                    sys::gamut_abandon(self.f, 1);
                }
            }
            self.f = ptr::null_mut();
        }
    }
}

impl Study {
    fn new(f: *mut sys::gamut_file, writing: bool) -> Study {
        Study { f, writing, group: String::new(), axes: 3 }
    }

    /// Finishes the file. A refused close keeps it open to fix and close
    /// again.
    pub fn close(&mut self) -> Result<()> {
        if self.f.is_null() {
            return Ok(());
        }
        call(|e| unsafe { sys::gamut_close(self.f, e) })?;
        self.f = ptr::null_mut();
        Ok(())
    }

    /// Gives up on the file without finishing it; with remove, deletes a
    /// file this study created (a file opened to append is never deleted).
    pub fn abandon(&mut self, remove: bool) {
        if !self.f.is_null() {
            unsafe { sys::gamut_abandon(self.f, remove as c_int) };
            self.f = ptr::null_mut();
        }
    }

    /// The open file, for the calls of gamut.h this crate does not cover.
    pub fn handle(&self) -> *mut sys::gamut_file {
        self.f
    }

    fn writer(&self) -> Result<*mut sys::gamut_file> {
        if self.f.is_null() {
            return Err(Error::new("", "the file is closed"));
        }
        if !self.writing {
            return Err(Error::new(
                "",
                "the file was opened to read; add runs to a file from gamut::create or gamut::open_append",
            ));
        }
        Ok(self.f)
    }

    fn reader(&self) -> Result<*mut sys::gamut_file> {
        if self.f.is_null() {
            return Err(Error::new("", "the file is closed"));
        }
        if self.writing {
            return Err(Error::new("", "the file is open to write; close it and open it with gamut::open to read"));
        }
        Ok(self.f)
    }

    // --- writing ------------------------------------------------------------

    pub fn declare_coordinates(&mut self, units: &str, axes: usize) -> Result<()> {
        let f = self.writer()?;
        let (units, none) = (c(units)?, c("")?);
        let axes = int(axes, "axes")?;
        call(|e| unsafe {
            sys::gamut_declare_coordinates(f, units.as_ptr(), sys::GAMUT_AS_GIVEN, axes, none.as_ptr(), none.as_ptr(), e)
        })?;
        self.axes = axes;
        Ok(())
    }

    /// A float64 parameter. role: "design", "condition" or "time".
    pub fn declare_parameter(&mut self, name: &str, role: &str, units: &str) -> Result<()> {
        self.declare_parameter_with(name, role, units, Parameter::default())
    }

    /// A parameter declared further: `Parameter::default().int64()`,
    /// `.bounds(lower, upper)`, `.run_group(label)`.
    pub fn declare_parameter_with(&mut self, name: &str, role: &str, units: &str, how: Parameter) -> Result<()> {
        let f = self.writer()?;
        let (name, role, units, group) = (c(name)?, c(role)?, c(units)?, c(&how.run_group)?);
        let dtype = if how.int64 { sys::GAMUT_INT64 } else { sys::GAMUT_FLOAT64 };
        let (has, (lower, upper)) = match how.bounds {
            Some(b) => (1, b),
            None => (0, (0.0, 0.0)),
        };
        call(|e| unsafe {
            sys::gamut_declare_parameter(f, name.as_ptr(), role.as_ptr(), units.as_ptr(), dtype, has, lower, upper,
                                         group.as_ptr(), e)
        })
    }

    /// role: "categorical", "status", "group" or "split"; without categories
    /// the table grows as names appear.
    pub fn declare_label(&mut self, name: &str, role: &str, categories: &[&str]) -> Result<()> {
        let f = self.writer()?;
        let (name, role, cats) = (c(name)?, c(role)?, c_all(categories)?);
        let p = pointers(&cats);
        call(|e| unsafe { sys::gamut_declare_label(f, name.as_ptr(), role.as_ptr(), p.as_ptr(), count(p.len()), e) })
    }

    pub fn declare_scalar(&mut self, name: &str, units: &str) -> Result<()> {
        self.declare_result(name, "scalar", units, &Relation::default())
    }

    /// A scalar that describes another: `gamut::std_of("cl")`, ...
    pub fn declare_scalar_of(&mut self, name: &str, units: &str, relation: Relation) -> Result<()> {
        self.declare_result(name, "scalar", units, &relation)
    }

    /// at: "node" or "cell".
    pub fn declare_field(&mut self, name: &str, at: &str, units: &str) -> Result<()> {
        self.declare_result(name, at, units, &Relation::default())
    }

    /// A field that describes another: `gamut::derivative_of("p", "alpha")`, ...
    pub fn declare_field_of(&mut self, name: &str, at: &str, units: &str, relation: Relation) -> Result<()> {
        self.declare_result(name, at, units, &relation)
    }

    fn declare_result(&mut self, name: &str, at: &str, units: &str, r: &Relation) -> Result<()> {
        let f = self.writer()?;
        let (name, at, units) = (c(name)?, c(at)?, c(units)?);
        let (of, statistic, wrt, axis, none) = (c(&r.of)?, c(&r.statistic)?, c(&r.with_respect_to)?, c(&r.axis)?, c("")?);
        call(|e| unsafe {
            sys::gamut_declare_result(f, name.as_ptr(), at.as_ptr(), units.as_ptr(), sys::GAMUT_AS_GIVEN,
                                      of.as_ptr(), statistic.as_ptr(), r.q.is_some() as c_int, r.q.unwrap_or(0.0),
                                      none.as_ptr(), wrt.as_ptr(), axis.as_ptr(), none.as_ptr(), -1, none.as_ptr(),
                                      none.as_ptr(), e)
        })
    }

    pub fn declare_mesh_label(&mut self, name: &str, at: &str, categories: &[&str]) -> Result<()> {
        let f = self.writer()?;
        let (name, at, cats) = (c(name)?, c(at)?, c_all(categories)?);
        let p = pointers(&cats);
        call(|e| unsafe { sys::gamut_declare_mesh_label(f, name.as_ptr(), at.as_ptr(), p.as_ptr(), count(p.len()), e) })
    }

    pub fn set_constant(&mut self, name: &str, value: f64, units: &str) -> Result<()> {
        let f = self.writer()?;
        let (name, units) = (c(name)?, c(units)?);
        call(|e| unsafe { sys::gamut_set_constant(f, name.as_ptr(), units.as_ptr(), sys::GAMUT_FLOAT64, value, 0, e) })
    }

    /// title, license, references, source or portion_marking.
    pub fn set_attribute(&mut self, name: &str, value: &str) -> Result<()> {
        let f = self.writer()?;
        let (name, value) = (c(name)?, c(value)?);
        call(|e| unsafe { sys::gamut_set_attribute(f, name.as_ptr(), value.as_ptr(), e) })
    }

    pub fn set_generalisation_group(&mut self, label: &str) -> Result<()> {
        let f = self.writer()?;
        let label = c(label)?;
        call(|e| unsafe { sys::gamut_set_generalisation_group(f, label.as_ptr(), e) })
    }

    /// A shared mesh: points (nodes x axes, C order), cells and fixed mesh
    /// labels, when the geometry is fixed.
    pub fn set_mesh(&mut self, points: &[f64], cells: &Cells, labels: &[(&str, &[i64])]) -> Result<()> {
        let f = self.writer()?;
        call(|e| unsafe { sys::gamut_geometry_begin(f, e) })?;
        self.stage(points, Some(cells), labels)?;
        call(|e| unsafe { sys::gamut_set_mesh(f, e) })
    }

    /// A shared mesh whose coordinates come with the runs: its node count.
    pub fn set_mesh_nodes(&mut self, nodes: usize, cells: &Cells, labels: &[(&str, &[i64])]) -> Result<()> {
        let f = self.writer()?;
        let axes = self.axes;
        call(|e| unsafe { sys::gamut_geometry_begin(f, e) })?;
        call(|e| unsafe { sys::gamut_geometry_points(f, sys::GAMUT_FLOAT64, ptr::null(), 0, count(nodes), axes, e) })?;
        self.stage(&[], Some(cells), labels)?;
        call(|e| unsafe { sys::gamut_set_mesh(f, e) })
    }

    /// Adds one run, all or nothing; returns its id. Fields hold one value
    /// per node or cell.
    pub fn add_run(&mut self, values: &[(&str, Value)], fields: &[(&str, &[f64])]) -> Result<i64> {
        self.add_one(values, fields, None)
    }

    /// Adds one run with its own geometry: the run's, or its group member's.
    pub fn add_run_with_geometry(&mut self, values: &[(&str, Value)], fields: &[(&str, &[f64])],
                                 geometry: &Geometry) -> Result<i64> {
        self.add_one(values, fields, Some(geometry))
    }

    fn add_one(&mut self, values: &[(&str, Value)], fields: &[(&str, &[f64])], geometry: Option<&Geometry>)
               -> Result<i64> {
        let f = self.writer()?;
        call(|e| unsafe { sys::gamut_batch_begin(f, 1, e) })?;
        let mut member = None;
        for (name, value) in values {
            let n = c(name)?;
            match value {
                Value::Float(v) => call(|e| unsafe {
                    sys::gamut_batch_values(f, n.as_ptr(), sys::GAMUT_FLOAT64, v as *const f64 as *const _, 0, 1, e)
                })?,
                Value::Int(v) => call(|e| unsafe {
                    sys::gamut_batch_values(f, n.as_ptr(), sys::GAMUT_INT64, v as *const i64 as *const _, 0, 1, e)
                })?,
                Value::Name(s) => {
                    let label = c(s)?;
                    let p = label.as_ptr();
                    call(|e| unsafe { sys::gamut_batch_names(f, n.as_ptr(), &p, 1, e) })?;
                    if *name == self.group {
                        member = Some(label);
                    }
                }
            }
        }
        self.stage_fields(fields)?;
        if let Some(g) = geometry {
            if !self.group.is_empty() && member.is_none() {
                return Err(Error::new("E2", format!("give {} by name so the geometry belongs to its member", self.group)));
            }
            call(|e| unsafe { sys::gamut_geometry_begin(f, e) })?;
            self.stage(g.points, g.cells, g.labels)?;
            match &member {
                None => call(|e| unsafe { sys::gamut_batch_geometry_for_row(f, e) })?,
                Some(m) => call(|e| unsafe { sys::gamut_batch_geometry_for_member(f, m.as_ptr(), e) })?,
            }
        }
        let mut id = 0;
        call(|e| unsafe { sys::gamut_batch_commit(f, &mut id, e) })?;
        Ok(id)
    }

    /// Adds many runs at once, all or nothing, on a mesh whose geometry is
    /// fixed or set already; returns their ids. Each field holds every run's
    /// values one after another.
    pub fn add_runs(&mut self, columns: &[(&str, Column)], fields: &[(&str, &[f64])]) -> Result<Vec<i64>> {
        let f = self.writer()?;
        let Some((_, first)) = columns.first() else {
            return Err(Error::new("E5", "add_runs needs at least one column"));
        };
        let n = first.len();
        for (name, column) in columns {
            if column.len() != n {
                return Err(Error::new(
                    "E5",
                    format!("every column needs the same number of runs; {name} has {}, not {n}", column.len()),
                ));
            }
        }
        call(|e| unsafe { sys::gamut_batch_begin(f, count(n), e) })?;
        for (name, column) in columns {
            let name = c(name)?;
            match column {
                Column::Float(v) => call(|e| unsafe {
                    sys::gamut_batch_values(f, name.as_ptr(), sys::GAMUT_FLOAT64, v.as_ptr().cast(), 0, count(n), e)
                })?,
                Column::Int(v) => call(|e| unsafe {
                    sys::gamut_batch_values(f, name.as_ptr(), sys::GAMUT_INT64, v.as_ptr().cast(), 0, count(n), e)
                })?,
                Column::Names(v) => {
                    let names = c_all(v)?;
                    let p = pointers(&names);
                    call(|e| unsafe { sys::gamut_batch_names(f, name.as_ptr(), p.as_ptr(), count(n), e) })?;
                }
            }
        }
        self.stage_fields(fields)?;
        let mut first_id = 0;
        call(|e| unsafe { sys::gamut_batch_commit(f, &mut first_id, e) })?;
        Ok((0..count(n)).map(|i| first_id + i).collect())
    }

    fn stage(&self, points: &[f64], cells: Option<&Cells>, labels: &[(&str, &[i64])]) -> Result<()> {
        let f = self.f;
        if !points.is_empty() {
            let (n, axes) = (count(points.len()), self.axes as i64);
            let nodes = if axes > 0 { n / axes } else { 0 };
            call(|e| unsafe {
                sys::gamut_geometry_points(f, sys::GAMUT_FLOAT64, points.as_ptr().cast(), n, nodes, self.axes, e)
            })?;
        }
        if let Some(cells) = cells {
            call(|e| unsafe {
                sys::gamut_geometry_cells(f, cells.types.as_ptr(), count(cells.types.len()), cells.offsets.as_ptr(),
                                          count(cells.offsets.len()), cells.connectivity.as_ptr(),
                                          count(cells.connectivity.len()), e)
            })?;
        }
        for (name, values) in labels {
            let name = c(name)?;
            call(|e| unsafe { sys::gamut_geometry_label(f, name.as_ptr(), values.as_ptr(), count(values.len()), e) })?;
        }
        Ok(())
    }

    fn stage_fields(&self, fields: &[(&str, &[f64])]) -> Result<()> {
        for (name, values) in fields {
            let name = c(name)?;
            call(|e| unsafe {
                sys::gamut_batch_values(self.f, name.as_ptr(), sys::GAMUT_FLOAT64, values.as_ptr().cast(), 0,
                                        count(values.len()), e)
            })?;
        }
        Ok(())
    }

    // --- reading ------------------------------------------------------------

    fn info(&self, key: &str) -> Result<String> {
        let f = self.reader()?;
        let key = c(key)?;
        let mut s = Strings::new();
        call(|e| unsafe { sys::gamut_info(f, key.as_ptr(), &mut s.0, e) })?;
        Ok(s.take().into_iter().next().unwrap_or_default())
    }

    pub fn row_count(&self) -> Result<usize> {
        self.info("row_count")?.parse().map_err(|_| Error::new("", "the core gave no row count"))
    }

    /// "data" (runs) or "model" (a fitted model).
    pub fn kind(&self) -> Result<String> {
        self.info("kind")
    }

    /// "table" (no mesh), "shared" or "changing": Python's `study.type`.
    pub fn type_(&self) -> Result<String> {
        self.info("type")
    }

    /// What the file holds beyond its type: "time", "uncertainty", "gradients".
    pub fn addons(&self) -> Result<Vec<String>> {
        let f = self.reader()?;
        let key = c("addons")?;
        let mut s = Strings::new();
        call(|e| unsafe { sys::gamut_info(f, key.as_ptr(), &mut s.0, e) })?;
        Ok(s.take())
    }

    /// group: "parameters", "labels", "scalars", "constants", "node_fields",
    /// "cell_fields", "node_labels", "cell_labels" (or "models").
    pub fn names(&self, group: &str) -> Result<Vec<String>> {
        let f = self.reader()?;
        let group = c(group)?;
        let mut s = Strings::new();
        call(|e| unsafe { sys::gamut_names(f, group.as_ptr(), &mut s.0, e) })?;
        Ok(s.take())
    }

    /// What the file says about a name, or with "" about itself.
    pub fn describe(&self, name: &str) -> Result<BTreeMap<String, String>> {
        let f = self.reader()?;
        let name = c(name)?;
        let (mut k, mut v) = (Strings::new(), Strings::new());
        call(|e| unsafe { sys::gamut_describe(f, name.as_ptr(), &mut k.0, &mut v.0, e) })?;
        Ok(k.take().into_iter().zip(v.take()).collect())
    }

    /// What describes a result: its std, quantiles, derivatives and vector.
    pub fn related(&self, name: &str) -> Result<Related> {
        let f = self.reader()?;
        let name = c(name)?;
        let (mut t, mut k, mut n) = (Strings::new(), Strings::new(), Strings::new());
        call(|e| unsafe { sys::gamut_related(f, name.as_ptr(), &mut t.0, &mut k.0, &mut n.0, e) })?;
        let mut out = Related::default();
        for ((kind, key), name) in t.take().into_iter().zip(k.take()).zip(n.take()) {
            match kind.as_str() {
                "std" => out.std = Some(name),
                "quantile" => {
                    let q = key.parse().map_err(|_| Error::new("", format!("the core gave the quantile key {key:?}")))?;
                    out.quantiles.push((q, name));
                }
                "derivative" => {
                    out.derivatives.insert(key, name);
                }
                "vector" => out.vector.push(name),
                _ => {}
            }
        }
        out.quantiles.sort_by(|a, b| a.0.total_cmp(&b.0));
        Ok(out)
    }

    /// The category table of a label or mesh label: code c names entry c.
    pub fn categories(&self, name: &str) -> Result<Vec<String>> {
        let table = self.describe(name)?.remove("category").unwrap_or_default();
        if table.is_empty() {
            return Err(Error::new("", format!("{name} has no category table; its codes are its values")));
        }
        let table = c(&table)?;
        let mut s = Strings::new();
        call(|e| unsafe { sys::gamut_table(self.f, table.as_ptr(), &mut s.0, e) })?;
        Ok(s.take())
    }

    /// The positions of the rows a condition selects ("mach > 0.7 and
    /// status == converged"), in increasing order.
    pub fn select(&self, condition: &str) -> Result<Vec<usize>> {
        // Room for every row up to the core's cap; past it the core refuses
        // (E26) before writing any, so no buffer is sized from the file's count.
        let rows = self.row_count()?;
        let mut out = vec![0i64; if rows > 0 && rows <= MAX_ROWS_SELECTED { rows } else { 1 }];
        let condition = c(condition)?;
        let mut n = 0;
        call(|e| unsafe { sys::gamut_select(self.f, condition.as_ptr(), out.as_mut_ptr(), count(out.len()), &mut n, e) })?;
        out.truncate(n as usize);
        Ok(out.into_iter().map(|k| k as usize).collect())
    }

    /// A field as rows x nodes (or cells); a changing mesh's, one row at a time.
    pub fn get_field(&self, name: &str, rows: impl Into<Selection>, sites: impl Into<Selection>) -> Result<Array<f64>> {
        self.read(name, rows, sites)
    }

    /// A parameter in the type it is stored as: f64 for a float64 one, i64
    /// for one declared int64. Another type is refused rather than
    /// converted, which would round or truncate.
    pub fn get_parameter<T: Number>(&self, name: &str, rows: impl Into<Selection>) -> Result<Vec<T>> {
        self.stored_as::<T>(name)?;
        Ok(self.read(name, rows, ..)?.values)
    }

    pub fn get_scalar(&self, name: &str, rows: impl Into<Selection>) -> Result<Vec<f64>> {
        Ok(self.read(name, rows, ..)?.values)
    }

    pub fn get_label(&self, name: &str, rows: impl Into<Selection>) -> Result<Vec<String>> {
        let f = self.reader()?;
        let name = c(name)?;
        let r = Sel::of(rows.into());
        let mut s = Strings::new();
        call(|e| unsafe { sys::gamut_label_names(f, name.as_ptr(), &r.c(), &mut s.0, e) })?;
        Ok(s.take())
    }

    /// How far each row's value of a parameter lies outside the bounds the
    /// file declares for it, in its units: 0 inside or on a bound, value -
    /// lower below, value - upper above, NaN where the value is missing. A
    /// parameter without bounds is refused.
    pub fn outside(&self, name: &str, rows: impl Into<Selection>) -> Result<Vec<f64>> {
        let f = self.reader()?;
        let name = c(name)?;
        let r = Sel::of(rows.into());
        let (mut shape, mut rank) = ([0i64; 4], 0);
        call(|e| unsafe { sys::gamut_shape(f, name.as_ptr(), &r.c(), ptr::null(), &mut rank, shape.as_mut_ptr(), 4, e) })?;
        let mut out = vec![0.0; if rank == 1 { shape[0] as usize } else { 0 }];
        let bytes = count(out.len() * std::mem::size_of::<f64>());
        call(|e| unsafe { sys::gamut_outside(f, name.as_ptr(), &r.c(), out.as_mut_ptr(), bytes, e) })?;
        Ok(out)
    }

    /// A constant in its type, as get_parameter: f64 (float32 widens
    /// exactly) or i64.
    pub fn get_constant<T: Number>(&self, name: &str) -> Result<T> {
        self.stored_as::<T>(name)?;
        self.read::<T>(name, .., ..)?.values.first().copied().ok_or_else(|| Error::new("", format!("{name} holds no value")))
    }

    pub fn get_row_ids(&self, rows: impl Into<Selection>) -> Result<Vec<i64>> {
        Ok(self.read("row", rows, ..)?.values)
    }

    /// The points a run used (nodes x axes); no row for a fixed geometry.
    pub fn get_points(&self, row: Option<usize>) -> Result<Array<f64>> {
        let per = self.info("per")?;
        if row.is_none() && per != "fixed" && !per.is_empty() {
            return Err(Error::new("", "this mesh's geometry changes; give the row"));
        }
        let mut a = self.read::<f64>("coordinates", one(row), ..)?;
        if row.is_some() && a.shape.len() == 3 {
            a.shape.remove(0); // the one row asked for
        }
        Ok(a)
    }

    pub fn get_cells(&self, row: Option<usize>) -> Result<Cells> {
        Ok(Cells {
            types: self.read("cells/types", one(row), ..)?.values,
            offsets: self.read("cells/offsets", one(row), ..)?.values,
            connectivity: self.read("cells/connectivity", one(row), ..)?.values,
        })
    }

    pub fn get_mesh_label(&self, name: &str, row: Option<usize>) -> Result<Vec<i64>> {
        Ok(self.read(name, one(row), ..)?.values)
    }

    /// Any name, as any element type: the general read the others use.
    pub fn read<T: Element>(&self, name: &str, rows: impl Into<Selection>, sites: impl Into<Selection>)
                            -> Result<Array<T>> {
        let f = self.reader()?;
        let name = c(name)?;
        let (r, s) = (Sel::of(rows.into()), Sel::of(sites.into()));
        let (mut shape, mut rank) = ([0i64; 4], 0);
        call(|e| unsafe { sys::gamut_shape(f, name.as_ptr(), &r.c(), &s.c(), &mut rank, shape.as_mut_ptr(), 4, e) })?;
        let shape: Vec<usize> = shape[..rank as usize].iter().map(|&d| d as usize).collect();
        let mut values = vec![T::default(); shape.iter().product()];
        let bytes = count(values.len() * std::mem::size_of::<T>());
        call(|e| unsafe {
            sys::gamut_read(f, name.as_ptr(), &r.c(), &s.c(), T::DTYPE, values.as_mut_ptr().cast(), bytes, e)
        })?;
        Ok(Array { shape, values })
    }

    /// Decompresses field reads in that many threads.
    pub fn set_threads(&self, threads: usize) -> Result<()> {
        let f = self.reader()?;
        let threads = int(threads, "threads")?;
        call(|e| unsafe { sys::gamut_set_threads(f, threads, e) })
    }

    // Refuses to read `name` as T unless T holds its stored type exactly.
    fn stored_as<T: Number>(&self, name: &str) -> Result<()> {
        let stored = self.describe(name)?.remove("dtype").unwrap_or_else(|| "float64".into());
        if T::INT64 != (stored == "int64") {
            let want = if stored == "int64" { "i64" } else { "f64" };
            return Err(Error::new("", format!("{name} is stored as {stored}; read it as {want}")));
        }
        Ok(())
    }
}

fn one(row: Option<usize>) -> Selection {
    row.map_or(Selection::All, Selection::from)
}

/// A new data file. mesh: "" (a table), "shared" or "changing"; per:
/// "fixed", "run" or `"group:<label>"` ("" for a table). Declarations come
/// next, then the mesh, then runs. The path must not exist.
pub fn create(path: &str, writer: &str, mesh: &str, per: &str) -> Result<Study> {
    let (path, writer, mesh_c, per_c) = (c(path)?, c(writer)?, c(mesh)?, c(per)?);
    let or_null = |s: &CString, given: &str| if given.is_empty() { ptr::null() } else { s.as_ptr() };
    let mut f = ptr::null_mut();
    call(|e| unsafe {
        sys::gamut_create(path.as_ptr(), writer.as_ptr(), or_null(&mesh_c, mesh), or_null(&per_c, per), &mut f, e)
    })?;
    let mut s = Study::new(f, true);
    s.group = per.strip_prefix("group:").unwrap_or_default().into();
    Ok(s)
}

/// Opens a file to read.
pub fn open(path: &str) -> Result<Study> {
    let path = c(path)?;
    let mut f = ptr::null_mut();
    call(|e| unsafe { sys::gamut_open(path.as_ptr(), &mut f, e) })?;
    Ok(Study::new(f, false))
}

/// Opens a data file to add runs in place: Python's `gamut.open(path, mode="a")`.
pub fn open_append(path: &str) -> Result<Study> {
    let (per, axes) = {
        let reader = open(path)?;
        let per = reader.info("per")?;
        let axes = if reader.info("mesh_kind")?.is_empty() {
            3
        } else {
            reader.describe("coordinates")?.get("axes").and_then(|a| a.parse().ok()).unwrap_or(3)
        };
        (per, axes)
    };
    let path = c(path)?;
    let mut f = ptr::null_mut();
    call(|e| unsafe { sys::gamut_open_append(path.as_ptr(), &mut f, e) })?;
    let mut s = Study::new(f, true);
    s.group = per.strip_prefix("group:").unwrap_or_default().into();
    s.axes = axes;
    Ok(s)
}

/// Adds src's runs to dst in place; returns how many.
pub fn append(dst: &str, src: &str) -> Result<usize> {
    let (dst, src) = (c(dst)?, c(src)?);
    let mut n = 0;
    call(|e| unsafe { sys::gamut_append(dst.as_ptr(), src.as_ptr(), &mut n, e) })?;
    Ok(n as usize)
}

/// Writes the chosen runs of src as a new file, their ids kept.
pub fn extract(src: &str, dst: &str, rows: impl Into<Selection>) -> Result<()> {
    let (src, dst) = (c(src)?, c(dst)?);
    let r = Sel::of(rows.into());
    call(|e| unsafe { sys::gamut_extract(src.as_ptr(), dst.as_ptr(), &r.c(), e) })
}

/// Rewrites a file with the default layout, keeping its identity.
pub fn write_copy(src: &str, dst: &str) -> Result<()> {
    let (src, dst) = (c(src)?, c(dst)?);
    call(|e| unsafe { sys::gamut_write_copy(src.as_ptr(), dst.as_ptr(), e) })
}

/// One finding of [`validate`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Finding {
    pub rule: String,
    pub severity: String,
    pub path: String,
    pub message: String,
}

/// What [`validate`] found: ok when there is no error.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Report {
    pub ok: bool,
    pub errors: Vec<Finding>,
    pub warnings: Vec<Finding>,
}

/// Checks a file against the rules of the specification.
pub fn validate(path: &str) -> Result<Report> {
    struct Free(*mut sys::gamut_report);
    impl Drop for Free {
        fn drop(&mut self) {
            unsafe { sys::gamut_report_free(self.0) }
        }
    }
    let path = c(path)?;
    let mut r = Free(ptr::null_mut());
    call(|e| unsafe { sys::gamut_validate(path.as_ptr(), &mut r.0, e) })?;
    let s = |p: *const c_char| if p.is_null() { String::new() } else { unsafe { CStr::from_ptr(p) }.to_string_lossy().into_owned() };
    let mut out = Report::default();
    for i in 0..unsafe { sys::gamut_report_count(r.0) } {
        let (mut rule, mut severity, mut at, mut message) = (ptr::null(), ptr::null(), ptr::null(), ptr::null());
        unsafe { sys::gamut_report_get(r.0, i, &mut rule, &mut severity, &mut at, &mut message) };
        let finding = Finding { rule: s(rule), severity: s(severity), path: s(at), message: s(message) };
        if finding.severity == "error" { out.errors.push(finding) } else { out.warnings.push(finding) }
    }
    out.ok = out.errors.is_empty();
    Ok(out)
}

/// Evaluates a model file on a column of inputs per parameter and label (a
/// label's by name), all of one length, into a new data file at `path`,
/// returned open to read with the W4 findings (inputs outside a
/// parameter's bounds, which are evaluated). The core runs the built-in
/// models; a model of another type is refused with its type's name, since
/// its software is not registered in Rust.
pub fn evaluate(model_path: &str, inputs: &[(&str, Column)], path: &str) -> Result<(Study, Vec<String>)> {
    struct Free(*mut sys::gamut_evaluation);
    impl Drop for Free {
        fn drop(&mut self) {
            unsafe { sys::gamut_evaluation_free(self.0) } // not finished: removes its file
        }
    }
    let model = open(model_path)?;
    let rows = inputs.first().map_or(0, |(_, column)| column.len());
    let out = c(path)?;
    let mut ev = Free(ptr::null_mut());
    call(|e| unsafe { sys::gamut_evaluation_begin(model.f, count(rows), out.as_ptr(), &mut ev.0, e) })?;
    for (name, column) in inputs {
        let name = c(name)?;
        match column {
            Column::Float(v) => call(|e| unsafe {
                sys::gamut_evaluation_values(ev.0, name.as_ptr(), sys::GAMUT_FLOAT64, v.as_ptr().cast(), count(v.len()), e)
            })?,
            Column::Int(v) => call(|e| unsafe {
                sys::gamut_evaluation_values(ev.0, name.as_ptr(), sys::GAMUT_INT64, v.as_ptr().cast(), count(v.len()), e)
            })?,
            Column::Names(v) => {
                let names = c_all(v)?;
                let p = pointers(&names);
                call(|e| unsafe { sys::gamut_evaluation_names(ev.0, name.as_ptr(), p.as_ptr(), count(p.len()), e) })?;
            }
        }
    }
    let (mut warnings, mut models) = (Strings::new(), Strings::new());
    call(|e| unsafe { sys::gamut_evaluation_ready(ev.0, &mut warnings.0, &mut models.0, e) })?;
    if let Some(id) = models.take().first() {
        let kind = model.describe(&format!("models/{id}"))?.remove("type").unwrap_or_default();
        return Err(Error::new("", format!("the model {id} is of type {kind:?}, whose software is not registered here")));
    }
    call(|e| unsafe { sys::gamut_evaluation_finish(ev.0, e) })?;
    drop(ev);
    Ok((open(path)?, warnings.take()))
}

/// The library's version ("2.0.0").
pub fn version() -> String {
    unsafe { CStr::from_ptr(sys::gamut_version()) }.to_string_lossy().into_owned()
}

/// The format string it writes ("gamut/1").
pub fn format() -> String {
    unsafe { CStr::from_ptr(sys::gamut_format()) }.to_string_lossy().into_owned()
}
