"""Writes src/lib.rs, the Rust declarations of include/gamut/gamut.h, one
for one.  Run it after changing gamut.h; with --check it changes nothing
and fails when src/lib.rs is not what it would write (CI runs that).

    python3 rust/gamut-sys/generate.py [--check]

gamut.h is plain C: opaque handles, two structs, enums of constants, and
functions with no callbacks.  That is all this reads, and anything else in
the header is refused rather than skipped."""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HEADER = HERE.parents[1] / "include" / "gamut" / "gamut.h"
BASE = {"char": "c_char", "int": "c_int", "int64_t": "i64", "uint8_t": "u8", "double": "f64",
        "size_t": "usize", "void": "c_void"}


def rust_type(c: str) -> str:
    """A C type (const char* const*) as Rust's (*const *const c_char)."""
    m = re.fullmatch(r"\s*(const\s+)?(\w+)\s*((?:\*\s*(?:const\s*)?)*)", c)
    if not m:
        sys.exit(f"generate.py: cannot read the C type {c!r}")
    base = m.group(2)
    t = BASE.get(base) or (base if base.startswith("gamut_") else None)
    if t is None:
        sys.exit(f"generate.py: no Rust type for {base!r}")
    pointee_const = m.group(1) is not None
    for star in re.findall(r"\*\s*(const)?", m.group(3)):
        t = f"*{'const' if pointee_const else 'mut'} {t}"
        pointee_const = star == "const"
    return t


# C parameter names that are Rust keywords.
KEYWORDS = {"type", "where", "in", "fn", "ref", "mod", "use", "match", "move", "self", "loop", "impl"}


def parameter(p: str) -> str:
    m = re.fullmatch(r"(.*?)(\w+)\s*", p)
    if not m or not m.group(1).strip():
        sys.exit(f"generate.py: cannot read the parameter {p!r}")
    name = m.group(2) + ("_" if m.group(2) in KEYWORDS else "")
    return f"{name}: {rust_type(m.group(1))}"


def main() -> None:
    text = re.sub(r"/\*.*?\*/", "", HEADER.read_text(), flags=re.S)
    text = re.sub(r"^\s*#.*$", "", text, flags=re.M)
    text = text.replace('extern "C" {', "")
    out = ["// Generated from include/gamut/gamut.h by generate.py; do not edit.",
           "//",
           "// The C interface of the Gamut core, one declaration per function of",
           "// gamut.h, which documents each.  The gamut crate is the safe interface.",
           "",
           "#![allow(non_camel_case_types)]",
           "",
           "use std::os::raw::{c_char, c_int, c_void};",
           ""]
    consts, structs, opaque, functions = [], [], [], []
    for enum in re.findall(r"enum\s*\{(.*?)\}\s*;", text, flags=re.S):
        for item in filter(None, (i.strip() for i in enum.split(","))):
            m = re.fullmatch(r"(\w+)\s*=\s*(-?\d+)", item)
            if not m:
                sys.exit(f"generate.py: an enumerator needs a literal value: {item!r}")
            consts.append(f"pub const {m.group(1)}: c_int = {m.group(2)};")
    text = re.sub(r"enum\s*\{.*?\}\s*;", "", text, flags=re.S)
    for body, name in re.findall(r"typedef\s+struct\s*\{(.*?)\}\s*(\w+)\s*;", text, flags=re.S):
        fields = []
        for decl in body.split(";"):
            decl = decl.strip()
            if not decl:
                continue
            m = re.fullmatch(r"(.*?)(\w+)\s*\[(\d+)\]", decl)
            if m:
                fields.append(f"    pub {m.group(2)}: [{rust_type(m.group(1))}; {m.group(3)}],")
                continue
            m = re.fullmatch(r"((?:const\s+)?\w+\s*\**)\s*(.*)", decl)
            for field in m.group(2).split(","):
                stars, field = re.fullmatch(r"\s*(\**)\s*(\w+)\s*", field).groups()
                fields.append(f"    pub {field}: {rust_type(m.group(1) + stars)},")
        structs += ["#[repr(C)]", "#[derive(Clone, Copy)]", f"pub struct {name} {{", *fields, "}", ""]
    text = re.sub(r"typedef\s+struct\s*\{.*?\}\s*\w+\s*;", "", text, flags=re.S)
    for name in re.findall(r"typedef\s+struct\s+(\w+)\s+\1\s*;", text):
        opaque += ["#[repr(C)]", f"pub struct {name} {{", "    _private: [u8; 0],", "}", ""]
    text = re.sub(r"typedef\s+struct\s+(\w+)\s+\1\s*;", "", text)
    for ret, name, params in re.findall(r"GAMUT_API\s+(.*?)\b(gamut_\w+)\s*\((.*?)\)\s*;", text, flags=re.S):
        params = " ".join(params.split())
        args = [] if params == "void" else [parameter(p) for p in params.split(",")]
        r = "" if ret.strip() == "void" else f" -> {rust_type(ret)}"
        functions.append(f"    pub fn {name}({', '.join(args)}){r};")
    text = re.sub(r"GAMUT_API\s+.*?\)\s*;", "", text, flags=re.S)
    rest = text.replace("}", "").strip()
    if rest:
        sys.exit(f"generate.py: gamut.h holds something this does not read:\n{rest[:400]}")
    out += consts + [""] + structs + opaque
    out += ['#[link(name = "gamut")]', 'extern "C" {', *functions, "}", ""]
    target, text = HERE / "src" / "lib.rs", "\n".join(out)
    if "--check" in sys.argv[1:]:
        if not target.is_file() or target.read_text() != text:
            sys.exit("rust/gamut-sys/src/lib.rs is not what gamut.h declares: run rust/gamut-sys/generate.py")
        return
    target.write_text(text)


main()
