#!/usr/bin/env python3
"""manifold3d <-> trimesh bridge + robust extrude / heightmap solid helpers.

Every boolean and polygon extrusion goes through manifold3d, which guarantees
watertight, intersection-free output.
"""
import numpy as np
import trimesh
import manifold3d as m3d


def to_trimesh(man, color=None):
    mesh = man.to_mesh()
    verts = np.asarray(mesh.vert_properties)[:, :3].copy()
    tris = np.asarray(mesh.tri_verts).copy()
    tm = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    if color is not None:
        tm.visual.face_colors = np.tile(np.array(color, np.uint8), (len(tm.faces), 1))
    return tm


def to_manifold(tm):
    mesh = m3d.Mesh(vert_properties=np.asarray(tm.vertices, np.float32),
                    tri_verts=np.asarray(tm.faces, np.uint32))
    return m3d.Manifold(mesh)


def extrude_contours(contours, height, fillrule=m3d.FillRule.EvenOdd):
    cs = m3d.CrossSection([np.asarray(c, float) for c in contours], fillrule)
    return cs.extrude(height)


def prism(contour, height, z0=0.0):
    """Extrude a single closed 2D contour into a prism Manifold."""
    man = extrude_contours([contour], height)
    return man.translate([0, 0, z0]) if z0 else man


def chamfered_prism(contour, height, chamfer, apothem):
    """Prism with a 45-deg bevel on the top outer edge (premium frame look).
    apothem = centre->edge distance of the contour (controls the chamfer scale)."""
    cs = m3d.CrossSection([np.asarray(contour, float)], m3d.FillRule.EvenOdd)
    if chamfer <= 0:
        return cs.extrude(height)
    lo = cs.extrude(height - chamfer)
    sc = (apothem - chamfer) / apothem
    cap = cs.extrude(chamfer, scale_top=(sc, sc)).translate([0, 0, height - chamfer])
    return lo + cap


def union(mans):
    return m3d.Manifold.batch_boolean(list(mans), m3d.OpType.Add)


def heightmap_solid(X, Y, Ztop, zbase=0.0):
    """Closed watertight solid under a heightmap grid (top surface + flat bottom +
    4 side walls, consistent outward winding)."""
    nx, ny = len(X), len(Y)
    XX, YY = np.meshgrid(X, Y)
    top = np.column_stack([XX.ravel(), YY.ravel(), Ztop.ravel()])
    bot = np.column_stack([XX.ravel(), YY.ravel(), np.full(XX.size, zbase)])
    V = np.vstack([top, bot]); N = nx * ny
    ti = lambda i, j: j * nx + i
    bi = lambda i, j: N + j * nx + i
    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a, b, c, d = ti(i, j), ti(i+1, j), ti(i+1, j+1), ti(i, j+1)
            faces += [[a, b, c], [a, c, d]]
            a, b, c, d = bi(i, j), bi(i+1, j), bi(i+1, j+1), bi(i, j+1)
            faces += [[a, c, b], [a, d, c]]
    for i in range(nx - 1):  # south / north
        t0, t1, b0, b1 = ti(i, 0), ti(i+1, 0), bi(i, 0), bi(i+1, 0)
        faces += [[t0, b0, b1], [t0, b1, t1]]
        j = ny - 1
        t0, t1, b0, b1 = ti(i, j), ti(i+1, j), bi(i, j), bi(i+1, j)
        faces += [[t0, t1, b1], [t0, b1, b0]]
    for j in range(ny - 1):  # west / east
        t0, t1, b0, b1 = ti(0, j), ti(0, j+1), bi(0, j), bi(0, j+1)
        faces += [[t0, t1, b1], [t0, b1, b0]]
        i = nx - 1
        t0, t1, b0, b1 = ti(i, j), ti(i, j+1), bi(i, j), bi(i, j+1)
        faces += [[t0, b0, b1], [t0, b1, t1]]
    return trimesh.Trimesh(vertices=V, faces=np.asarray(faces), process=True)


def stats(tm, name=""):
    return (f"{name:10} watertight={tm.is_watertight} vol={tm.volume:.1f} "
            f"euler={tm.euler_number} faces={len(tm.faces)} "
            f"size={np.round(tm.extents,1).tolist()}")
