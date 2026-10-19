"""Runs the study the README picture reads, and writes it as one file.

    python docs/assets/hero_sweep.py XFOIL WORK_DIR

XFOIL is an XFOIL 6.99 binary (web.mit.edu/drela/Public/web/xfoil). It runs
a NACA 4412 section at alpha -6 to 18 degrees by 0.2 and Reynolds numbers
2e5, 1e6 and 6e6, Mach 0, Ncrit 9, on XFOIL's default paneling of 160
nodes, which is the same for every run. WORK_DIR receives XFOIL's outputs
and WORK_DIR/naca4412.gamut. A run is converged when XFOIL accumulated it
into its polar; the others are written with status failed and no field
values. The same sweep at Ncrit 7 and 11 gives cl_std, the sample
standard deviation of cl over the three transition criteria, stored beside
cl (cl itself is the Ncrit 9 value): a transition sensitivity, not a
confidence interval. A published train/test split holds out a seeded draw
of about a fifth of the runs, for testing within this sweep. The sweeps
take about a minute.
"""
import glob
import os
import subprocess
import sys

import numpy as np

import gamut

RE = [2e5, 1e6, 6e6]
ALPHA = np.round(np.arange(-6.0, 18.0 + 1e-9, 0.2), 1)
NCRIT = 9                       # the study's transition criterion
SPREAD = (7, 9, 11)             # the criteria cl_std is taken over
TEST, SEED = 0.2, 0             # the published split


def branch(xfoil, work, re, alphas, tag, ncrit=NCRIT):
    """One XFOIL session marching through alphas, so each point starts from
    the previous solution. XFOIL runs in WORK_DIR with short relative file
    names, since it truncates long ones."""
    d = f"re{re:.0e}" if ncrit == NCRIT else f"n{ncrit}/re{re:.0e}"
    os.makedirs(os.path.join(work, d), exist_ok=True)
    polar = os.path.join(d, f"polar_{tag}.txt")
    for path in (polar, "nodes.dat"):    # XFOIL asks before overwriting
        if os.path.exists(os.path.join(work, path)):
            os.remove(os.path.join(work, path))
    cmd = ["PLOP", "G F", "", "NACA 4412", "PANE", "PSAV nodes.dat",
           "OPER", "MACH 0", "VPAR", f"N {ncrit}", "", f"VISC {re:.0f}", "ITER 300", "PACC", polar, ""]
    for a in alphas:
        stem = os.path.join(d, f"a{a:+05.1f}")
        cmd += [f"ALFA {a}", f"CPWR {stem}.cp", f"DUMP {stem}.bl"]
    cmd += ["PACC", "", "QUIT"]
    log = subprocess.run([os.path.abspath(xfoil)], input="\n".join(cmd) + "\n", text=True, capture_output=True,
                         cwd=work, timeout=1800, check=True)
    with open(os.path.join(work, d, f"log_{tag}.txt"), "w") as fh:
        fh.write(log.stdout + log.stderr)


def polar(path):
    """alpha -> (cl, cd, cm, upper and lower transition) of the converged runs."""
    rows, data = {}, False
    for line in open(path):
        if line.lstrip().startswith("------"):
            data = True
        elif data and line.strip():
            a, cl, cd, cdp, cm, xtr_upper, xtr_lower = map(float, line.split()[:7])
            rows[round(a, 1)] = (cl, cd, cm, xtr_upper, xtr_lower)
    return rows


def write(work):
    nodes = np.loadtxt(os.path.join(work, "nodes.dat"))      # x/c, y/c: upper trailing edge, nose, lower
    n = len(nodes)
    cells = (np.full(n - 1, 3, np.uint8),                     # VTK line, node to node
             np.arange(0, 2 * (n - 1) + 1, 2),
             np.c_[np.arange(n - 1), np.arange(1, n)].ravel())
    le = int(np.argmin(nodes[:, 0]))
    side = np.r_[np.zeros(le + 1, int), np.ones(n - le - 1, int)]
    with gamut.create(os.path.join(work, "naca4412.gamut"), writer="XFOIL 6.99 sweep, NACA 4412",
                      mesh="shared", per="fixed",
                      title="NACA 4412 in XFOIL 6.99, alpha and Reynolds number sweep",
                      coordinates={"units": "m", "axes": 2},
                      parameters={"reynolds": {"units": "1", "role": "condition"},
                                  "alpha": {"units": "degree", "role": "condition"}},
                      labels={"status": {"role": "status", "categories": ["converged", "failed"]},
                              "split": {"role": "split", "categories": ["train", "test"]}},
                      scalars={"cl": "1", "cd": "1", "cm": "1", "xtr_upper": "1", "xtr_lower": "1",
                               "cl_std": {"units": "1", "of": "cl", "statistic": "std",
                                          "method": "sample std (ddof 1) of cl over XFOIL Ncrit 7, 9 and 11; "
                                                    "missing unless all three converged"}},
                      constants={"chord": (1.0, "m"), "mach": (0.0, "1"), "ncrit": (9.0, "1")},
                      mesh_labels={"side": {"at": "node", "categories": ["upper", "lower"]}},
                      fields={"cp": {"units": "1", "at": "node"},
                              "cf": {"units": "1", "at": "node"}}) as study:
        study.set_mesh(nodes, cells, labels={"side": side})
        rng = np.random.default_rng(SEED)
        test = rng.random(len(RE) * len(ALPHA)) < TEST
        row = 0
        for re in RE:
            polars = {}
            for ncrit in SPREAD:
                d = os.path.join(work, f"re{re:.0e}" if ncrit == NCRIT else f"n{ncrit}/re{re:.0e}")
                polars[ncrit] = {**polar(os.path.join(d, "polar_down.txt")), **polar(os.path.join(d, "polar_up.txt"))}
            d = os.path.join(work, f"re{re:.0e}")
            done = polars[NCRIT]
            for alpha in ALPHA:
                stem = os.path.join(d, f"a{alpha:+05.1f}")
                spread = [polars[n][alpha][0] if alpha in polars[n] else np.nan for n in SPREAD]
                run = {"reynolds": re, "alpha": float(alpha), "split": "test" if test[row] else "train",
                       "cl_std": float(np.std(spread, ddof=1))}
                row += 1
                if alpha in done:
                    cl, cd, cm, xu, xl = done[alpha]
                    cp = np.loadtxt(stem + ".cp", comments="#")[:, 1]
                    cf = np.loadtxt(stem + ".bl", comments="#", usecols=6)[:n]    # surface, then wake
                    study.add_run({**run, "status": "converged", "cl": cl, "cd": cd, "cm": cm,
                                   "xtr_upper": xu, "xtr_lower": xl}, fields={"cp": cp, "cf": cf})
                else:
                    study.add_run({**run, "status": "failed", "cl": np.nan, "cd": np.nan, "cm": np.nan,
                                   "xtr_upper": np.nan, "xtr_lower": np.nan})


def main(xfoil, work):
    for ncrit in SPREAD:
        os.makedirs(os.path.join(work, f"n{ncrit}"), exist_ok=True)
        for re in RE:
            branch(xfoil, work, re, ALPHA[ALPHA >= 0], "up", ncrit)
            branch(xfoil, work, re, ALPHA[ALPHA < 0][::-1], "down", ncrit)
    write(work)


if __name__ == "__main__":
    main(*sys.argv[1:3])
