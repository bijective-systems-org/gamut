"""The ring of quadrilaterals around a cylinder that several examples share."""
import numpy as np


def ring(n_theta=48, n_r=12, radius=1.0, outer=6.0):
    """Points (nodes x 2), cells (types, offsets, connectivity), and the
    polar coordinates of each node, for a ring of quads around a cylinder."""
    theta = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
    r = np.geomspace(radius, outer * radius, n_r)
    t, rr = np.meshgrid(theta, r)
    points = np.column_stack([(rr * np.cos(t)).ravel(), (rr * np.sin(t)).ravel()])
    quads = [[j * n_theta + i, j * n_theta + (i + 1) % n_theta,
              (j + 1) * n_theta + (i + 1) % n_theta, (j + 1) * n_theta + i]
             for j in range(n_r - 1) for i in range(n_theta)]
    cells = (np.full(len(quads), 9, np.uint8),            # VTK quadrilateral
             np.arange(0, 4 * len(quads) + 1, 4),
             np.array(quads).ravel())
    return points, cells, t.ravel(), rr.ravel()


def pressure(t, r, radius=1.0, gamma=0.0):
    """Pressure coefficient of potential flow past a cylinder with
    circulation gamma, free stream speed 1."""
    u_r = np.cos(t) * (1 - radius**2 / r**2)
    u_t = -np.sin(t) * (1 + radius**2 / r**2) + gamma / (2 * np.pi * r)
    return 1 - (u_r**2 + u_t**2)
