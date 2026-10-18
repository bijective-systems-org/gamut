/* Fields on one mesh shared by every run, from C.
 *
 * The study of examples/02_one_mesh.py: potential flow past a cylinder at
 * nine values of circulation, on one ring of quadrilaterals, written run by
 * run as a solver would, then read back by condition and by node. Every
 * call returns 0, or fills the error record and returns nonzero.
 *
 *   cc one_mesh.c -I<prefix>/include -L<prefix>/lib -lmestra -lm -o one_mesh
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include <mestra/mestra.h>

static mes_error err;

/* Stops at the first failure and says what it was. */
#define CHECK(call)                                                                \
  do {                                                                             \
    if ((call) != 0) {                                                             \
      fprintf(stderr, "%s%s%s\n", err.rule, *err.rule ? ": " : "", err.message);   \
      exit(1);                                                                     \
    }                                                                              \
  } while (0)

enum { N_THETA = 48, N_R = 12, N_NODES = N_THETA * N_R, N_CELLS = N_THETA * (N_R - 1) };

int main(void) {
  const double pi = 3.14159265358979323846;
  static double points[N_NODES][2], t[N_NODES], r[N_NODES], cp[N_NODES];
  static int64_t surface[N_NODES], offsets[N_CELLS + 1], connectivity[4 * N_CELLS];
  static uint8_t types[N_CELLS];
  for (int k = 0; k < N_NODES; ++k) {                /* around each ring first */
    t[k] = 2 * pi * (k % N_THETA) / N_THETA;
    r[k] = pow(6.0, (double)(k / N_THETA) / (N_R - 1));
    points[k][0] = r[k] * cos(t[k]);
    points[k][1] = r[k] * sin(t[k]);
    surface[k] = k < N_THETA;                        /* wall: the first ring */
  }
  for (int c = 0; c < N_CELLS; ++c) {
    const int64_t a = c, b = c - c % N_THETA + (c + 1) % N_THETA;
    const int64_t quad[4] = {a, b, b + N_THETA, a + N_THETA};
    types[c] = 9;                                    /* VTK quadrilateral */
    offsets[c + 1] = 4 * (c + 1);
    for (int v = 0; v < 4; ++v) connectivity[4 * c + v] = quad[v];
  }

  mes_file* f = NULL;
  const char* categories[] = {"field", "wall"};
  CHECK(mes_create("cylinder.mes", "example sweep", "shared", "fixed", &f, &err));
  CHECK(mes_declare_coordinates(f, "m", MES_FLOAT64, 2, "", "", &err));
  CHECK(mes_declare_parameter(f, "gamma", "design", "m2 s-1", MES_FLOAT64, 0, 0, 0, "", &err));
  CHECK(mes_declare_mesh_label(f, "surface", "node", categories, 2, &err));
  CHECK(mes_declare_result(f, "cp", "node", "1", MES_FLOAT64, "", "", 0, 0, "", "", "", "", -1,
                           "", "", &err));
  CHECK(mes_geometry_begin(f, &err));
  CHECK(mes_geometry_points(f, MES_FLOAT64, points, N_NODES, 2, &err));
  CHECK(mes_geometry_cells(f, types, N_CELLS, offsets, connectivity, 4 * N_CELLS, &err));
  CHECK(mes_geometry_label(f, "surface", surface, N_NODES, &err));
  CHECK(mes_set_mesh(f, &err));
  for (int run = 0; run < 9; ++run) {
    const double gamma = 0.5 * run;
    for (int k = 0; k < N_NODES; ++k) {
      const double u_t = -sin(t[k]) * (1 + 1 / (r[k] * r[k])) + gamma / (2 * pi * r[k]);
      const double u_r = cos(t[k]) * (1 - 1 / (r[k] * r[k]));
      cp[k] = 1 - (u_r * u_r + u_t * u_t);
    }
    CHECK(mes_batch_begin(f, 1, &err));             /* one run, all or nothing */
    CHECK(mes_batch_values(f, "gamma", MES_FLOAT64, &gamma, 1, &err));
    CHECK(mes_batch_values(f, "cp", MES_FLOAT64, cp, N_NODES, &err));
    CHECK(mes_batch_commit(f, NULL, &err));
  }
  CHECK(mes_close(f, &err));

  CHECK(mes_open("cylinder.mes", &f, &err));
  int64_t rows[9], n = 0, node = 12;
  CHECK(mes_select(f, "gamma > 2", rows, 9, &n, &err));
  const mes_sel chosen = {MES_SEL_INDEX, 0, 0, rows, n};
  const mes_sel one_node = {MES_SEL_INDEX, 0, 0, &node, 1};
  double values[9];
  CHECK(mes_read(f, "cp", &chosen, &one_node, MES_FLOAT64, values, sizeof values, &err));
  printf("cp at node %lld where gamma > 2:", (long long)node);
  for (int64_t i = 0; i < n; ++i) printf(" %.2f", values[i]);
  printf("\n");
  CHECK(mes_close(f, &err));
  return 0;
}
