#!/usr/bin/env python3
"""4D Geometry Showcase: animated 4D->3D->2D projections and real 3D OBJ meshes.

Creates 4 GIFs, a side-by-side animated GIF, PNG previews, and 3D OBJ/MTL models.
Dependencies: python -m pip install numpy pillow
Usage: python four_d_geometry_showcase.py --output four_d_showcase --frames 48 --size 380

The meshes are 3D perspective projections of 4D wireframes, with every edge
represented by a finite-radius cylindrical rod and each vertex by a small sphere.
They are NOT 4D-native assets and should not be mistaken for solid 4-polytopes.
"""

import argparse
import itertools
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

COLOURS = {
    "5-cell": (255, 164, 88),
    "Tesseract": (76, 227, 255),
    "16-cell": (187, 131, 255),
    "24-cell": (101, 255, 176),
}


def polytopes():
    """Construct exact vertices and adjacency of 4 regular convex 4-polytopes."""
    shapes = {}

    # Regular 4-simplex: five centred unit vectors in a 4D hyperplane of R^5.
    centred = np.eye(5) - np.ones((5, 5)) / 5
    basis, _ = np.linalg.qr(np.column_stack([np.eye(5)[:, k] - np.eye(5)[:, 4] for k in range(4)]))
    v = centred @ basis
    shapes["5-cell"] = (v, list(itertools.combinations(range(5), 2)))

    # 8-cell: every vertex is (+/-1,+/-1,+/-1,+/-1).
    v = np.asarray(list(itertools.product([-1., 1.], repeat=4)))
    e = [(i, j) for i in range(16) for j in range(i+1, 16)
         if np.count_nonzero(v[i] != v[j]) == 1]
    shapes["Tesseract"] = (v, e)

    # 16-cell: vertices +/- unit vectors, with all non-antipodal pairs as edges.
    v = np.vstack([np.eye(4), -np.eye(4)])
    e = [(i, j) for i in range(8) for j in range(i+1, 8)
         if abs(float(np.dot(v[i], v[j]))) < 1e-8]
    shapes["16-cell"] = (v, e)

    # Regular 24-cell: permutations of (+/-1,+/-1,0,0).
    vertices = []
    for axes in itertools.combinations(range(4), 2):
        for signs in itertools.product((-1., 1.), repeat=2):
            p = np.zeros(4)
            p[axes[0]], p[axes[1]] = signs
            vertices.append(p)
    v = np.asarray(vertices)
    e = [(i, j) for i in range(24) for j in range(i+1, 24)
         if abs(float(np.sum((v[i] - v[j])**2)) - 2) < 1e-8]
    shapes["24-cell"] = (v, e)

    # Normalize all circumradii for a consistent visual scale.
    return {name: (v / np.max(np.linalg.norm(v, axis=1)) * 1.67, edges)
            for name, (v, edges) in shapes.items()}


def rotate_nd(points, axis1, axis2, angle):
    """Rotate points in a genuine 4D coordinate plane."""
    c, s = math.cos(angle), math.sin(angle)
    result = points.copy()
    result[:, axis1] = c * points[:, axis1] - s * points[:, axis2]
    result[:, axis2] = s * points[:, axis1] + c * points[:, axis2]
    return result


def in_three_dimensions(points4, phase):
    """A continuous 4D rotation followed by 4D perspective projection into R3."""
    p = points4.copy()
    for a, b, rate, start in [
        (0, 3, 1., 0.29),
        (1, 2, -1., 0.41),
        (1, 3, 2., 0.18),
        (0, 2, 1., -0.23),
    ]:
        p = rotate_nd(p, a, b, phase * rate + start)

    # The 4D camera looks along the W axis; W changes apparent scale in R3.
    camera_w, focal_w = 4.4, 3.7
    return p[:, :3] * (focal_w / (camera_w - p[:, 3]))[:, None]


def camera3d(points3, phase):
    """Fixed oblique camera with a slight azimuthal orbit."""
    p = points3.copy()
    angle = 0.57 + 0.10 * math.sin(phase)
    c, s = math.cos(angle), math.sin(angle)
    x = c * p[:, 0] + s * p[:, 2]
    z = -s * p[:, 0] + c * p[:, 2]
    p[:, 0], p[:, 2] = x, z

    angle = -0.30
    c, s = math.cos(angle), math.sin(angle)
    y = c * p[:, 1] - s * p[:, 2]
    z = s * p[:, 1] + c * p[:, 2]
    p[:, 1], p[:, 2] = y, z
    return p


def screen_projection(points3, size):
    """Perspective project the visible 3D object onto a 2D canvas."""
    focal, distance = 5.5, 6.9
    scale = focal / (distance - points3[:, 2])
    xy = points3[:, :2] * scale[:, None]
    xy[:, 1] *= -1
    return xy * (size * .345) + size / 2


def tint(colour, factor):
    return tuple(max(0, min(255, int(x * factor))) for x in colour)


def font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def background(size, colour):
    im = Image.new("RGB", (size, size), (4, 8, 19))
    d = ImageDraw.Draw(im, "RGB")
    cx, cy = size/2, size/2
    # Rings and axes provide depth cues, separate from the projected geometry.
    for radius in (.23, .35, .45):
        r = size * radius
        d.ellipse((cx-r, cy-r, cx+r, cy+r), outline=(13, 24, 43), width=1)
    for k in range(5):
        a = k * math.pi / 5
        r = size * .44
        d.line((cx-r*math.cos(a), cy-r*math.sin(a),
                cx+r*math.cos(a), cy+r*math.sin(a)), fill=(11, 21, 37), width=1)
    # Soft ambient centre for contrast.
    light = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ld = ImageDraw.Draw(light)
    r = int(size * .22)
    ld.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(*colour, 24))
    light = light.filter(ImageFilter.GaussianBlur(size / 7))
    return Image.alpha_composite(im.convert("RGBA"), light)


def render_frame(name, original, edges, frame_no, frames, size):
    phase = 2*math.pi * frame_no/frames
    colour = COLOURS[name]
    p3 = camera3d(in_three_dimensions(original, phase), phase)
    pixels = screen_projection(p3, size)

    im = background(size, colour)
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    lines = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lines)

    depth_edges = sorted(edges, key=lambda edge: (p3[edge[0], 2] + p3[edge[1], 2])/2)
    for i, j in depth_edges:
        avg_z = float((p3[i, 2] + p3[j, 2]) / 2)
        depth = max(0., min(1., (avg_z + 2.6)/5.2))
        c = tint(colour, .36 + .72 * depth)
        xy = (tuple(pixels[i]), tuple(pixels[j]))
        thick = max(1, round(size / 205 * (0.8 + depth)))
        gd.line(xy, fill=(*colour, 100), width=thick+6)
        ld.line(xy, fill=(*c, 220), width=thick)
        # Tiny white specular highlight on near edges.
        if depth > .67:
            ld.line(xy, fill=(*tint(c, 1.13), 145), width=1)

    im = Image.alpha_composite(im, glow.filter(ImageFilter.GaussianBlur(size / 75)))
    im = Image.alpha_composite(im, lines)
    d = ImageDraw.Draw(im, "RGBA")

    for i in np.argsort(p3[:, 2]):
        x, y = pixels[i]
        depth = max(0., min(1., (p3[i, 2] + 2.6) / 5.2))
        r = size * (.0074 + .004*depth)
        d.ellipse((x-r-1, y-r-1, x+r+1, y+r+1), fill=(0, 0, 0, 190))
        d.ellipse((x-r, y-r, x+r, y+r), fill=(*tint(colour, .67+.4*depth), 255))
        d.ellipse((x-r*.45, y-r*.6, x+r*.02, y-r*.1), fill=(255, 255, 255, 190))

    title_font = font(max(16, size // 19))
    meta_font = font(max(10, size // 34))
    d.text((size*.055, size*.045), name.upper(), fill=(241, 250, 255, 255), font=title_font)
    d.text((size*.055, size*.115), "4D ROTATION  /  3D PROJECTION", fill=(*colour, 240), font=meta_font)
    d.text((size*.055, size*.925), f"{len(original)} VERTICES  /  {len(edges)} EDGES", fill=(165, 179, 204, 255), font=meta_font)
    return im.convert("RGB")


def add_tube(verts, faces, start, end, radius, sides=9):
    vec = end - start
    norm = np.linalg.norm(vec)
    if norm < 1e-8:
        return
    tangent = vec / norm
    ref = np.array([0., 0., 1.]) if abs(tangent[2]) < .9 else np.array([0., 1., 0.])
    u = np.cross(tangent, ref)
    u /= np.linalg.norm(u)
    v = np.cross(tangent, u)
    base = len(verts) + 1
    for pos in (start, end):
        for k in range(sides):
            a = 2*math.pi*k/sides
            verts.append(pos + radius * (math.cos(a)*u + math.sin(a)*v))
    faces.append(tuple(base+k for k in reversed(range(sides))))
    for k in range(sides):
        kn = (k+1) % sides
        faces.append((base+k, base+kn, base+sides+kn, base+sides+k))
    faces.append(tuple(base+sides+k for k in range(sides)))


def add_sphere(verts, faces, centre, radius, longitudes=10, latitudes=6):
    top = len(verts)+1
    verts.append(centre + np.array([0., 0., radius]))
    rings = []
    for latitude in range(1, latitudes):
        theta = math.pi * latitude/latitudes
        ring = []
        for longitude in range(longitudes):
            phi = 2*math.pi * longitude/longitudes
            ring.append(len(verts)+1)
            verts.append(centre + radius*np.array([
                math.sin(theta)*math.cos(phi),
                math.sin(theta)*math.sin(phi),
                math.cos(theta)]))
        rings.append(ring)
    bottom = len(verts)+1
    verts.append(centre + np.array([0., 0., -radius]))
    for k in range(longitudes):
        kn = (k+1)%longitudes
        faces.append((top, rings[0][k], rings[0][kn]))
        for a, b in zip(rings[:-1], rings[1:]):
            faces.append((a[k], b[k], b[kn], a[kn]))
        faces.append((rings[-1][k], bottom, rings[-1][kn]))


def export_obj(path, name, original, edges):
    # A static, nondegenerate projection: actual 3D tube/sphere mesh geometry.
    xyz = camera3d(in_three_dimensions(original, .72), .72)
    verts, faces = [], []
    radius = .023 if len(edges) < 60 else .0145
    for i, j in edges:
        add_tube(verts, faces, xyz[i], xyz[j], radius)
    for point in xyz:
        add_sphere(verts, faces, point, radius*1.65)
    colour = COLOURS[name]
    material_name = "4d_" + name.lower().replace("-", "_")
    mtl_path = path.with_suffix(".mtl")
    with open(mtl_path, "w", encoding="utf-8") as f:
        f.write(f"newmtl {material_name}\n")
        f.write("Kd " + " ".join(f"{x/255:.5f}" for x in colour) + "\n")
        f.write("Ka 0.12 0.12 0.12\nKs 0.6 0.6 0.6\nNs 70\nillum 2\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 3D wireframe mesh projected from a regular 4D polytope\n")
        f.write(f"mtllib {mtl_path.name}\no {name.replace('-', '_')}\n")
        f.write(f"usemtl {material_name}\n")
        for v in verts:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for poly in faces:
            f.write("f " + " ".join(map(str, poly)) + "\n")


def save_gif(frames, path, fps):
    # Global RGB->P conversion: every frame remains colourful, GIF loops forever.
    quantized = [im.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
                 for im in frames]
    quantized[0].save(path, save_all=True, append_images=quantized[1:],
                      duration=round(1000/fps), loop=0, disposal=2, optimize=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="four_d_showcase", type=Path)
    parser.add_argument("--size", default=360, type=int, help="Pixels per shape")
    parser.add_argument("--frames", default=40, type=int, help="Frames per GIF")
    parser.add_argument("--fps", default=20, type=int)
    args = parser.parse_args()
    if args.size < 180 or args.frames < 8 or args.fps < 1 or args.fps > 50:
        parser.error("Use --size >= 180, --frames >= 8, and 1 <= --fps <= 50")
    args.output.mkdir(parents=True, exist_ok=True)
    shapes = polytopes()
    rendered = []
    previews = []
    for name, (vertices, edges) in shapes.items():
        print(f"Generating {name}: {len(vertices)} vertices, {len(edges)} edges", flush=True)
        frames = [render_frame(name, vertices, edges, k, args.frames, args.size)
                  for k in range(args.frames)]
        stub = name.lower().replace("-", "_")
        save_gif(frames, args.output / f"{stub}_4d.gif", args.fps)
        frames[args.frames//5].save(args.output / f"{stub}_preview.png")
        export_obj(args.output / f"{stub}_3d.obj", name, vertices, edges)
        previews.append(frames[args.frames//5])
        rendered.append(frames)

    spacing = max(4, args.size//60)
    canvas_size = 2*args.size + 3*spacing
    combined = []
    for k in range(args.frames):
        canvas = Image.new("RGB", (canvas_size, canvas_size), (5, 9, 20))
        for idx in range(4):
            x = spacing + (idx%2)*(args.size+spacing)
            y = spacing + (idx//2)*(args.size+spacing)
            canvas.paste(rendered[idx][k], (x, y))
        combined.append(canvas)
    save_gif(combined, args.output / "all_4d_shapes_animated.gif", args.fps)
    combined[args.frames//5].save(args.output / "all_4d_shapes_preview.png")
    print(f"Finished. Files saved in {args.output.resolve()}", flush=True)


if __name__ == "__main__":
    main()
