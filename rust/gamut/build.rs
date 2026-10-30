// The tests and examples of this crate find the core where bijective-gamut-sys
// linked it (GAMUT_LIB_DIR), with no library path to set.
fn main() {
    let windows = std::env::var("CARGO_CFG_TARGET_OS").is_ok_and(|os| os == "windows");
    if let (Ok(dir), false) = (std::env::var("DEP_GAMUT_LIB_DIR"), windows) {
        println!("cargo:rustc-link-arg=-Wl,-rpath,{dir}");
    }
}
