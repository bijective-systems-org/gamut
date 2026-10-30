"""Writes src/lib.rs, the Rust declarations of include/gamut/gamut.h, one
for one.  Run it after changing gamut.h; with --check it changes nothing
and fails when src/lib.rs is not what it would write (CI runs that).

    python3 rust/gamut-sys/generate.py [--check]

gamut.h is plain C: opaque handles, two structs, enums of constants, and
functions with no callbacks.  This reads that much as a grammar, and every
declaration is read whole with C's meaning or generation stops: nothing is
skipped, and a header that grows past the grammar is refused, not misread."""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
HEADER = HERE.parents[1] / "include" / "gamut" / "gamut.h"
BASE = {"char": "c_char", "int": "c_int", "int64_t": "i64", "uint8_t": "u8", "double": "f64",
        "size_t": "usize", "void": "c_void"}
# The preprocessor lines gamut.h has: its guard, its includes, GAMUT_API and
# extern "C".  Any other directive could change what the C means.
DIRECTIVES = {"#ifndef GAMUT_H", "#define GAMUT_H", "#include <stddef.h>", "#include <stdint.h>",
              "#if defined(_WIN32)", "#if defined(GAMUT_BUILDING)",
              "#define GAMUT_API __declspec(dllexport)", "#else",
              "#define GAMUT_API __declspec(dllimport)", "#endif",
              '#define GAMUT_API __attribute__((visibility("default")))', "#ifdef __cplusplus"}
# C parameter names that are Rust keywords.
KEYWORDS = {"type", "where", "in", "fn", "ref", "mod", "use", "match", "move", "self", "loop", "impl"}
NAME = r"[A-Za-z_]\w*"
DECIMAL = r"-?(?:0|[1-9]\d*)"   # 010 is octal in C


def refuse(what: str) -> None:
    sys.exit(f"generate.py: {what}; gamut.h has grown past what this reads")


def rust_type(base: str, const: bool, stars: str) -> str:
    """A C base type, its const and its pointer levels (each "*" or "*const")
    as Rust's: const char* const* is *const *const c_char."""
    t = BASE.get(base) or (base if base.startswith("gamut_") else None)
    if t is None:
        refuse(f"no Rust type for {base!r}")
    for star in re.findall(r"\*\s*(const\b)?", stars):
        t = f"*{'const' if const else 'mut'} {t}"
        const = bool(star)
    return t


def declarator(spec: str, item: str, where: str) -> tuple[str, str]:
    """(name, Rust type) of one declarator, `item`, of a declaration whose
    type specifier is `spec` ("const char"): the stars are the item's own."""
    m = re.fullmatch(r"(const\s+)?(" + NAME + r")", spec.strip())
    n = re.fullmatch(r"((?:\*\s*(?:const\b\s*)?)*)(" + NAME + r")(?:\s*\[\s*(0|[1-9]\d*)\s*\])?", item.strip())
    if not m or not n or n.group(2) in BASE or n.group(2) == "const":
        refuse(f"cannot read {spec.strip()} {item.strip()!r} in {where}")
    t = rust_type(m.group(2), m.group(1) is not None, n.group(1))
    return n.group(2), f"[{t}; {n.group(3)}]" if n.group(3) else t


def split_type(decl: str, where: str) -> tuple[str, str]:
    """A declaration's type specifier and the rest: "const char" and "* const* x"."""
    m = re.fullmatch(r"\s*((?:const\s+)?" + NAME + r")\s*(\*.*|\s" + NAME + r".*)", decl, re.S)
    if not m:
        refuse(f"cannot read {decl.strip()!r} in {where}")
    return m.group(1), m.group(2)


def main() -> None:
    text = re.sub(r"/\*.*?\*/", " ", HEADER.read_text(), flags=re.S)
    if "//" in text:
        refuse("a // comment")
    body = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#"):
            directive = "#" + " ".join(line.strip()[1:].split())
            if directive not in DIRECTIVES:
                refuse(f"the directive {line.strip()!r}")
        else:
            body.append(line)
    text = "\n".join(body)
    if text.count('extern "C" {') != 1:
        refuse('extern "C" other than once')
    text = text.replace('extern "C" {', "", 1)
    last = text.rstrip().rfind("}")                 # extern "C"'s closing brace
    if last < 0 or text[last + 1:].strip():
        refuse('extern "C" without its closing brace last')
    text = text[:last]

    # Top-level declarations end with ";" outside braces.
    decls, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += ch == "{"
        depth -= ch == "}"
        if depth < 0:
            refuse("an unmatched }")
        if ch == ";" and depth == 0:
            decls.append(text[start:i].strip())
            start = i + 1
    if text[start:].strip():
        refuse(f"text after the last declaration: {text[start:].strip()[:80]!r}")

    consts, structs, opaque, functions = [], [], [], []
    for d in decls:
        if m := re.fullmatch(r"enum\s*\{(.*)\}", d, re.S):
            for item in m.group(1).split(","):
                if not item.strip():
                    continue
                e = re.fullmatch(r"\s*(" + NAME + r")\s*=\s*(" + DECIMAL + r")\s*", item)
                if not e or not -2**31 <= int(e.group(2)) < 2**31:
                    refuse(f"the enumerator {item.strip()!r} (a decimal int is read)")
                consts.append(f"pub const {e.group(1)}: c_int = {e.group(2)};")
        elif m := re.fullmatch(r"typedef\s+struct\s*\{(.*)\}\s*(" + NAME + r")", d, re.S):
            name, fields = m.group(2), []
            for field in filter(str.strip, m.group(1).split(";")):
                spec, rest = split_type(field, name)
                for item in rest.split(","):
                    fname, t = declarator(spec, item, name)
                    fields.append(f"    pub {fname}: {t},")
            structs += ["#[repr(C)]", "#[derive(Clone, Copy)]", f"pub struct {name} {{", *fields, "}", ""]
        elif m := re.fullmatch(r"typedef\s+struct\s+(" + NAME + r")\s+(" + NAME + r")", d):
            if m.group(1) != m.group(2):
                refuse(f"the typedef {d!r}")
            opaque += ["#[repr(C)]", f"pub struct {m.group(1)} {{", "    _private: [u8; 0],", "}", ""]
        elif m := re.fullmatch(r"GAMUT_API\s+(.*?)\b(gamut_\w+)\s*\(([^()]*)\)", d, re.S):
            ret = m.group(1).strip()
            params = " ".join(m.group(3).split())
            args = []
            if params != "void":
                for p in params.split(","):
                    spec, rest = split_type(p, m.group(2))
                    pname, t = declarator(spec, rest, m.group(2))
                    args.append(f"{pname + '_' if pname in KEYWORDS else pname}: {t}")
            if ret == "void":
                r = ""
            else:
                rm = re.fullmatch(r"((?:const\s+)?)(" + NAME + r")\s*((?:\*\s*(?:const\b\s*)?)*)", ret)
                if not rm:
                    refuse(f"the return type of {m.group(2)}")
                r = f" -> {rust_type(rm.group(2), bool(rm.group(1)), rm.group(3))}"
            functions.append(f"    pub fn {m.group(2)}({', '.join(args)}){r};")
        else:
            refuse(f"the declaration {' '.join(d.split())[:100]!r}")

    out = ["// Generated from include/gamut/gamut.h by generate.py; do not edit.",
           "//",
           "// The C interface of the Gamut core, one declaration per function of",
           "// gamut.h, which documents each.  The gamut crate is the safe interface.",
           "",
           "#![allow(non_camel_case_types)]",
           "",
           "use std::os::raw::{c_char, c_int, c_void};",
           ""]
    out += consts + [""] + structs + opaque
    out += ['#[link(name = "gamut")]', 'extern "C" {', *functions, "}", ""]
    target, text = HERE / "src" / "lib.rs", "\n".join(out)
    if "--check" in sys.argv[1:]:
        if not target.is_file() or target.read_text() != text:
            sys.exit("rust/gamut-sys/src/lib.rs is not what gamut.h declares: run rust/gamut-sys/generate.py")
        return
    target.write_text(text)


main()
