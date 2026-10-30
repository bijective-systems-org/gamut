// Links the Gamut core: the shared library in GAMUT_LIB_DIR (the lib folder
// of a released core, or a build directory), else wherever the linker looks.
// Crates that use this one read the folder as DEP_GAMUT_LIB_DIR.
fn main() {
    println!("cargo:rerun-if-env-changed=GAMUT_LIB_DIR");
    if let Ok(dir) = std::env::var("GAMUT_LIB_DIR") {
        println!("cargo:rustc-link-search=native={dir}");
        println!("cargo:lib_dir={dir}");
    }
}
