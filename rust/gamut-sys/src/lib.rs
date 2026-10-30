// Generated from include/gamut/gamut.h by generate.py; do not edit.
//
// The C interface of the Gamut core, one declaration per function of
// gamut.h, which documents each.  bijective-gamut is the safe interface.

#![allow(non_camel_case_types)]

use std::os::raw::{c_char, c_int, c_void};

pub const GAMUT_AS_GIVEN: c_int = 0;
pub const GAMUT_UINT8: c_int = 1;
pub const GAMUT_INT8: c_int = 2;
pub const GAMUT_INT32: c_int = 3;
pub const GAMUT_INT64: c_int = 4;
pub const GAMUT_FLOAT32: c_int = 5;
pub const GAMUT_FLOAT64: c_int = 6;
pub const GAMUT_SEL_ALL: c_int = 0;
pub const GAMUT_SEL_RANGE: c_int = 1;
pub const GAMUT_SEL_INDEX: c_int = 2;
pub const GAMUT_TREE_NULL: c_int = 0;
pub const GAMUT_TREE_BOOL: c_int = 1;
pub const GAMUT_TREE_INT: c_int = 2;
pub const GAMUT_TREE_FLOAT: c_int = 3;
pub const GAMUT_TREE_STRING: c_int = 4;
pub const GAMUT_TREE_NUMBERS: c_int = 5;
pub const GAMUT_TREE_STRINGS: c_int = 6;
pub const GAMUT_TREE_DICT: c_int = 7;
pub const GAMUT_TREE_ABSENT: c_int = -1;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct gamut_error {
    pub rule: [c_char; 8],
    pub path: [c_char; 512],
    pub message: [c_char; 2048],
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct gamut_sel {
    pub kind: c_int,
    pub start: i64,
    pub stop: i64,
    pub index: *const i64,
    pub count: i64,
}

#[repr(C)]
pub struct gamut_file {
    _private: [u8; 0],
}

#[repr(C)]
pub struct gamut_strings {
    _private: [u8; 0],
}

#[repr(C)]
pub struct gamut_tree {
    _private: [u8; 0],
}

#[repr(C)]
pub struct gamut_evaluation {
    _private: [u8; 0],
}

#[repr(C)]
pub struct gamut_report {
    _private: [u8; 0],
}

#[link(name = "gamut")]
extern "C" {
    pub fn gamut_version() -> *const c_char;
    pub fn gamut_format() -> *const c_char;
    pub fn gamut_units_valid(units: *const c_char) -> c_int;
    pub fn gamut_create(path: *const c_char, writer: *const c_char, mesh_kind: *const c_char, per: *const c_char, out: *mut *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_open_append(path: *const c_char, out: *mut *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_create_model(path: *const c_char, writer: *const c_char, mesh_kind: *const c_char, per: *const c_char, out: *mut *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_attribute(f: *mut gamut_file, name: *const c_char, value: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_declare_parameter(f: *mut gamut_file, name: *const c_char, role: *const c_char, units: *const c_char, dtype: c_int, has_bounds: c_int, lower: f64, upper: f64, run_group: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_declare_label(f: *mut gamut_file, name: *const c_char, role: *const c_char, categories: *const *const c_char, n_categories: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_declare_result(f: *mut gamut_file, name: *const c_char, where_: *const c_char, units: *const c_char, dtype: c_int, of: *const c_char, statistic: *const c_char, has_q: c_int, q: f64, method: *const c_char, with_respect_to: *const c_char, axis: *const c_char, vector: *const c_char, round_bits: c_int, model: *const c_char, output: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_declare_mesh_label(f: *mut gamut_file, name: *const c_char, where_: *const c_char, categories: *const *const c_char, n_categories: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_declare_coordinates(f: *mut gamut_file, units: *const c_char, dtype: c_int, axes: c_int, model: *const c_char, output: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_constant(f: *mut gamut_file, name: *const c_char, units: *const c_char, dtype: c_int, float_value: f64, integer_value: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_generalisation_group(f: *mut gamut_file, label: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_compression(f: *mut gamut_file, gzip_level: c_int, shuffle: c_int, err: *mut gamut_error) -> c_int;
    pub fn gamut_geometry_begin(f: *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_geometry_points(f: *mut gamut_file, dtype: c_int, points: *const c_void, count: i64, n_nodes: i64, axes: c_int, err: *mut gamut_error) -> c_int;
    pub fn gamut_geometry_cells(f: *mut gamut_file, types: *const u8, n_cells: i64, offsets: *const i64, n_offsets: i64, connectivity: *const i64, n_connectivity: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_geometry_label(f: *mut gamut_file, name: *const c_char, values: *const i64, n: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_mesh(f: *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_batch_begin(f: *mut gamut_file, n_rows: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_batch_values(f: *mut gamut_file, name: *const c_char, dtype: c_int, values: *const c_void, first_axis: i64, count: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_batch_names(f: *mut gamut_file, label: *const c_char, names: *const *const c_char, count: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_batch_geometry_for_row(f: *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_batch_geometry_for_member(f: *mut gamut_file, member: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_batch_commit(f: *mut gamut_file, first_id: *mut i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_flush(f: *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_note_text(f: *mut gamut_file, key: *const c_char, value: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_note_int(f: *mut gamut_file, key: *const c_char, value: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_note_float(f: *mut gamut_file, key: *const c_char, value: f64, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_private(f: *mut gamut_file, name: *const c_char, bytes: *const c_void, n: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_close(f: *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_abandon(f: *mut gamut_file, remove_file: c_int);
    pub fn gamut_open(path: *const c_char, out: *mut *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_set_threads(f: *mut gamut_file, threads: c_int, err: *mut gamut_error) -> c_int;
    pub fn gamut_info(f: *const gamut_file, key: *const c_char, out: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_names(f: *const gamut_file, group: *const c_char, out: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_describe(f: *const gamut_file, name: *const c_char, keys: *mut *mut gamut_strings, values: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_related(f: *const gamut_file, name: *const c_char, kinds: *mut *mut gamut_strings, keys: *mut *mut gamut_strings, names: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_shape(f: *const gamut_file, name: *const c_char, rows: *const gamut_sel, sites: *const gamut_sel, rank: *mut c_int, shape: *mut i64, capacity: c_int, err: *mut gamut_error) -> c_int;
    pub fn gamut_read(f: *const gamut_file, name: *const c_char, rows: *const gamut_sel, sites: *const gamut_sel, dtype: c_int, out: *mut c_void, out_bytes: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_label_names(f: *const gamut_file, label: *const c_char, rows: *const gamut_sel, out: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_outside(f: *const gamut_file, name: *const c_char, rows: *const gamut_sel, out: *mut f64, out_bytes: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_table(f: *const gamut_file, table: *const c_char, out: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_select(f: *const gamut_file, where_: *const c_char, out: *mut i64, capacity: i64, n: *mut i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_new(out: *mut *mut gamut_tree, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_free(t: *mut gamut_tree);
    pub fn gamut_tree_set_null(t: *mut gamut_tree, key: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_set_bool(t: *mut gamut_tree, key: *const c_char, value: c_int, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_set_int(t: *mut gamut_tree, key: *const c_char, value: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_set_float(t: *mut gamut_tree, key: *const c_char, value: f64, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_set_string(t: *mut gamut_tree, key: *const c_char, value: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_set_array(t: *mut gamut_tree, key: *const c_char, dtype: c_int, data: *const c_void, count: i64, rank: c_int, shape: *const i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_set_strings(t: *mut gamut_tree, key: *const c_char, items: *const *const c_char, n: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_set_dict(t: *mut gamut_tree, key: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_keys(t: *const gamut_tree, key: *const c_char, out: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_kind(t: *const gamut_tree, key: *const c_char, kind: *mut c_int, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_scalar(t: *const gamut_tree, key: *const c_char, integer: *mut i64, real: *mut f64, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_strings(t: *const gamut_tree, key: *const c_char, out: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_array_info(t: *const gamut_tree, key: *const c_char, dtype: *mut c_int, rank: *mut c_int, shape: *mut i64, capacity: c_int, err: *mut gamut_error) -> c_int;
    pub fn gamut_tree_array(t: *const gamut_tree, key: *const c_char, out: *mut c_void, out_bytes: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_add_model(f: *mut gamut_file, id: *const c_char, type_: *const c_char, inputs: *const *const c_char, n_inputs: i64, numbers: *const gamut_tree, repr: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_model_numbers(f: *const gamut_file, id: *const c_char, out: *mut *mut gamut_tree, err: *mut gamut_error) -> c_int;
    pub fn gamut_nearest_check(numbers: *const gamut_tree, err: *mut gamut_error) -> c_int;
    pub fn gamut_nearest_output_size(numbers: *const gamut_tree, output: *const c_char, per_row: *mut i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_nearest_call(numbers: *const gamut_tree, input_names: *const *const c_char, columns: *const *const f64, column_lengths: *const i64, n_inputs: c_int, n_rows: i64, output: *const c_char, out: *mut f64, out_count: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluate_begin(model: *const gamut_file, out_path: *const c_char, out: *mut *mut gamut_file, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_begin(model: *const gamut_file, rows: i64, out_path: *const c_char, out: *mut *mut gamut_evaluation, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_values(ev: *mut gamut_evaluation, name: *const c_char, dtype: c_int, values: *const c_void, count: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_names(ev: *mut gamut_evaluation, name: *const c_char, names: *const *const c_char, count: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_coordinates(ev: *mut gamut_evaluation, dtype: c_int, values: *const c_void, count: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_ready(ev: *mut gamut_evaluation, warnings: *mut *mut gamut_strings, models: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_requests(ev: *const gamut_evaluation, model_id: *const c_char, outputs: *mut *mut gamut_strings, kinds: *mut *mut gamut_strings, keys: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_input_info(ev: *const gamut_evaluation, name: *const c_char, dtype: *mut c_int, rank: *mut c_int, shape: *mut i64, capacity: c_int, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_input(ev: *const gamut_evaluation, name: *const c_char, out: *mut c_void, out_bytes: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_answer(ev: *mut gamut_evaluation, model_id: *const c_char, output: *const c_char, kind: *const c_char, key: *const c_char, dtype: c_int, values: *const c_void, count: i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_finish(ev: *mut gamut_evaluation, err: *mut gamut_error) -> c_int;
    pub fn gamut_evaluation_free(ev: *mut gamut_evaluation);
    pub fn gamut_append(dst_path: *const c_char, src_path: *const c_char, rows_added: *mut i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_extract(src_path: *const c_char, dst_path: *const c_char, rows: *const gamut_sel, err: *mut gamut_error) -> c_int;
    pub fn gamut_write_copy(src_path: *const c_char, dst_path: *const c_char, err: *mut gamut_error) -> c_int;
    pub fn gamut_validate(path: *const c_char, out: *mut *mut gamut_report, err: *mut gamut_error) -> c_int;
    pub fn gamut_report_count(r: *const gamut_report) -> i64;
    pub fn gamut_report_get(r: *const gamut_report, i: i64, rule: *mut *const c_char, severity: *mut *const c_char, path: *mut *const c_char, message: *mut *const c_char) -> c_int;
    pub fn gamut_report_free(r: *mut gamut_report);
    pub fn gamut_notes(f: *const gamut_file, keys: *mut *mut gamut_strings, kinds: *mut *mut gamut_strings, values: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_private_names(f: *const gamut_file, out: *mut *mut gamut_strings, err: *mut gamut_error) -> c_int;
    pub fn gamut_get_private(f: *const gamut_file, name: *const c_char, out: *mut c_void, capacity: i64, n: *mut i64, err: *mut gamut_error) -> c_int;
    pub fn gamut_strings_count(s: *const gamut_strings) -> i64;
    pub fn gamut_strings_get(s: *const gamut_strings, i: i64) -> *const c_char;
    pub fn gamut_strings_free(s: *mut gamut_strings);
}
