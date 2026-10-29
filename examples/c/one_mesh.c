/* A sweep on one mesh: eight runs written, a ninth added, then read.
 *
 * Potential flow past a cylinder at nine values of circulation, on one ring
 * of quadrilaterals. The MATLAB, Julia and C++ examples of this name are
 * the same program and print the same line. Every call
 * returns 0, or fills the error record and returns nonzero.
 *
 *   cc one_mesh.c -I<prefix>/include -L<prefix>/lib -lgamut -lm -o one_mesh
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include <gamut/gamut.h>

static gamut_error err;

/* Stops at the first failure and says what it was. */
#define CHECK(call)                                                                \
  do {                                                                             \
    if ((call) != 0) {                                                             \
      fprintf(stderr, "%s%s%s\n", err.rule, *err.rule ? ": " : "", err.message);   \
      exit(1);                                                                     \
    }                                                                              \
  } while (0)

enum { N_THETA = 48, N_R = 12, N_NODES = N_THETA * N_R, N_CELLS = N_THETA * (N_R - 1) };

static const double pi = 3.14159265358979323846;
static double t[N_NODES], r[N_NODES];

/* Stands for the solver: cp at every node for one value of circulation. */
static void solve(double gamma, double* cp) {
  for (int k = 0; k < N_NODES; ++k) {
    const double u_t = -sin(t[k]) * (1 + 1 / (r[k] * r[k])) + gamma / (2 * pi * r[k]);
    const double u_r = cos(t[k]) * (1 - 1 / (r[k] * r[k]));
    cp[k] = 1 - (u_r * u_r + u_t * u_t);
  }
}

/* Adds one run, all or nothing. */
static void add_run(gamut_file* f, double gamma) {
  static double cp[N_NODES];
  solve(gamma, cp);
  CHECK(gamut_batch_begin(f, 1, &err));
  CHECK(gamut_batch_values(f, "gamma", GAMUT_FLOAT64, &gamma, 0, 1, &err));
  CHECK(gamut_batch_values(f, "cp", GAMUT_FLOAT64, cp, 0, N_NODES, &err));
  CHECK(gamut_batch_commit(f, NULL, &err));
}

int main(void) {
  static double points[N_NODES][2];
  static int64_t offsets[N_CELLS + 1], connectivity[4 * N_CELLS];
  static uint8_t types[N_CELLS];
  for (int k = 0; k < N_NODES; ++k) {                /* around each ring first */
    t[k] = 2 * pi * (k % N_THETA) / N_THETA;
    r[k] = pow(6.0, (double)(k / N_THETA) / (N_R - 1));
    points[k][0] = r[k] * cos(t[k]);
    points[k][1] = r[k] * sin(t[k]);
  }
  for (int c = 0; c < N_CELLS; ++c) {
    const int64_t a = c, b = c - c % N_THETA + (c + 1) % N_THETA;
    const int64_t quad[4] = {a, b, b + N_THETA, a + N_THETA};
    types[c] = 9;                                    /* VTK quadrilateral */
    offsets[c + 1] = 4 * (c + 1);
    for (int v = 0; v < 4; ++v) connectivity[4 * c + v] = quad[v];
  }

  gamut_file* f = NULL;
  CHECK(gamut_create("cylinder.gamut", "example sweep", "shared", "fixed", &f, &err));
  CHECK(gamut_declare_coordinates(f, "m", GAMUT_FLOAT64, 2, "", "", &err));
  CHECK(gamut_declare_parameter(f, "gamma", "design", "m2 s-1", GAMUT_FLOAT64, 0, 0, 0, "", &err));
  CHECK(gamut_declare_result(f, "cp", "node", "1", GAMUT_FLOAT64, "", "", 0, 0, "", "", "", "", -1,
                           "", "", &err));
  CHECK(gamut_geometry_begin(f, &err));
  CHECK(gamut_geometry_points(f, GAMUT_FLOAT64, points, N_NODES, 2, &err));
  CHECK(gamut_geometry_cells(f, types, N_CELLS, offsets, connectivity, 4 * N_CELLS, &err));
  CHECK(gamut_set_mesh(f, &err));
  for (int run = 0; run < 8; ++run) add_run(f, 0.5 * run);
  CHECK(gamut_close(f, &err));

  CHECK(gamut_open_append("cylinder.gamut", &f, &err));
  add_run(f, 4.0);
  CHECK(gamut_close(f, &err));

  CHECK(gamut_open("cylinder.gamut", &f, &err));
  int64_t node = 12;
  const gamut_sel one_node = {GAMUT_SEL_INDEX, 0, 0, &node, 1};
  double cp[9];                                          /* runs x nodes */
  CHECK(gamut_read(f, "cp", NULL, &one_node, GAMUT_FLOAT64, cp, sizeof cp, &err));
  CHECK(gamut_close(f, &err));
  printf("cp at the top of the cylinder, run by run:");
  for (int i = 0; i < 9; ++i) printf(" %.2f", cp[i]);
  printf("\n");
  return 0;
}
