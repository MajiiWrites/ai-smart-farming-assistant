"""Generate deterministic synthetic leaf photos for tests and demos.

WHY synthetic: unit tests must run offline with zero fixtures to download,
and they must be *stable* — seeded RNG means every run produces pixel-
identical images, so the vision assertions never flake.

Five images (600x600, white background):
  healthy_leaf.jpg   green ellipse leaf + veins + subtle noise
  spotted_leaf.jpg   healthy + 25 small brown circular spots  -> leaf_spot
  blight_leaf.jpg    healthy + 3 large irregular brown patches -> blight
  chlorotic_leaf.jpg yellow-green gradient leaf               -> chlorosis
  non_leaf.jpg       saturated red/blue/magenta rectangles on light gray
                     (no foliage hues at all)                 -> must raise
                     NoLeafDetectedError

The brown spot color BGR(42,80,150) sits at HSV H~10 (inside the vision
module's brown range H 5-25); the yellow BGR(80,200,220) sits at H~26
(inside the chlorosis range H 20-35 and the foliage range H 25-85).
"""

import os
import random

import cv2
import numpy as np

SEED = 42
SIZE = 600
CENTER = (300, 300)
AXES = (250, 180)  # leaf ellipse radii -> area ~ pi*250*180 ~= 141k px
LEAF_GREEN = (60, 180, 70)      # BGR; HSV H~57 (foliage)
VEIN_GREEN = (40, 140, 50)      # BGR; darker, still foliage hue
SPOT_BROWN = (42, 80, 150)      # BGR; HSV H~10 (lesion range)
PATCH_BROWN = (45, 85, 150)     # BGR; slightly different, still H~10
LEAF_YELLOW = (80, 200, 220)    # BGR; HSV H~26 (chlorosis range)

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")


def _rngs():
    """Fresh seeded generators — WHY fresh per image: each image is then
    independent of generation order, so adding a new sample later cannot
    shift the pixels of the existing ones."""
    return random.Random(SEED), np.random.default_rng(SEED)


def _blank():
    return np.full((SIZE, SIZE, 3), 255, dtype=np.uint8)


def _leaf_mask_canvas():
    mask = np.zeros((SIZE, SIZE), dtype=np.uint8)
    cv2.ellipse(mask, CENTER, AXES, 0, 0, 360, 255, -1)
    return mask


def _inside_leaf(x, y, margin=0.92):
    # WHY margin 0.92: keeps spots/patches fully on the blade, away from
    # the rim, so edge-browning stays ~0 for the spot/blight samples.
    return ((x - CENTER[0]) / (AXES[0] * margin)) ** 2 + \
           ((y - CENTER[1]) / (AXES[1] * margin)) ** 2 < 1.0


def _draw_leaf(img):
    """Base leaf: filled ellipse + central vein + side veins."""
    cv2.ellipse(img, CENTER, AXES, 0, 0, 360, LEAF_GREEN, -1)
    cx, cy = CENTER
    cv2.line(img, (cx - 230, cy), (cx + 230, cy), VEIN_GREEN, 4)
    for dx in range(-180, 200, 60):  # side veins, angled toward the tip
        cv2.line(img, (cx + dx, cy), (cx + dx + 70, cy - 70), VEIN_GREEN, 2)
        cv2.line(img, (cx + dx, cy), (cx + dx + 70, cy + 70), VEIN_GREEN, 2)


def _add_noise(img, sigma=6.0):
    """Subtle sensor-like noise clipped to the leaf — WHY only the leaf:
    noise on the white background could create stray saturated pixels."""
    rng = np.random.default_rng(SEED)
    mask = _leaf_mask_canvas()
    noise = rng.normal(0, sigma, img.shape).astype(np.float32)
    noisy = img.astype(np.float32) + noise
    noisy = np.clip(noisy, 0, 255).astype(np.uint8)
    img[mask > 0] = noisy[mask > 0]
    return img


def make_healthy(path):
    _, _ = _rngs()
    img = _blank()
    _draw_leaf(img)
    _add_noise(img)
    cv2.imwrite(path, img)


def make_spotted(path):
    """25 small round brown spots -> must classify as leaf_spot.

    Math check: 25 spots x pi*7^2 ~= 3850 px / 141372 px leaf ~= 2.7%
    diseased — under the 8% blight gate, over the 2% healthy gate;
    count 25 >= 8 with high circularity -> leaf_spot.
    """
    rnd, _ = _rngs()
    img = _blank()
    _draw_leaf(img)
    placed = 0
    while placed < 25:
        x = rnd.randint(60, 540)
        y = rnd.randint(140, 460)
        if not _inside_leaf(x, y):
            continue
        r = rnd.randint(5, 9)
        # WHY slight color jitter: real spots are not perfectly uniform,
        # but the hue must stay inside the brown H 5-25 band.
        j = rnd.randint(-8, 8)
        color = (SPOT_BROWN[0] + j, SPOT_BROWN[1] + j, SPOT_BROWN[2] - j)
        cv2.circle(img, (x, y), r, color, -1)
        placed += 1
    _add_noise(img)
    cv2.imwrite(path, img)


def make_blight(path):
    """3 large irregular brown patches -> must classify as blight.

    Math check: each blob ~7-8k px, total ~22k px / 141372 ~= 15%
    diseased (>= 8) with mean lesion area >> 600 px -> blight.
    """
    rnd, _ = _rngs()
    img = _blank()
    _draw_leaf(img)
    for _ in range(3):
        # Random interior center.
        while True:
            cx = rnd.randint(150, 450)
            cy = rnd.randint(180, 420)
            if _inside_leaf(cx, cy, margin=0.7):
                break
        # Irregular polygon: 10 vertices, radius 40-62 with angular jitter.
        # WHY a polygon and not a circle: blight patches are irregular —
        # low circularity is part of the real-world signature.
        pts = []
        n = 10
        for i in range(n):
            ang = 2 * np.pi * i / n + rnd.uniform(-0.25, 0.25)
            rad = rnd.randint(40, 62)
            px = int(cx + rad * np.cos(ang))
            py = int(cy + rad * np.sin(ang) * 0.8)
            pts.append([px, py])
        cv2.fillPoly(img, [np.array(pts, dtype=np.int32)], PATCH_BROWN)
    _add_noise(img)
    cv2.imwrite(path, img)


def make_chlorotic(path):
    """Green -> yellow horizontal gradient leaf -> must classify as chlorosis.

    The right ~half of the blade crosses into the yellow HSV band, so
    yellowness lands around 35-45% (rule needs > 15%); brown stays ~0.
    """
    _, _ = _rngs()
    img = _blank()
    mask = _leaf_mask_canvas()
    # Per-column blend factor t: 0 (green) at the left rim -> 1 (yellow)
    # at the right rim.
    gradient = np.zeros_like(img)
    for x in range(SIZE):
        t = (x - (CENTER[0] - AXES[0])) / (2.0 * AXES[0])
        t = min(1.0, max(0.0, t))
        # Ease the transition so most of the right half is clearly yellow.
        t = t ** 0.8
        b = int(LEAF_GREEN[0] * (1 - t) + LEAF_YELLOW[0] * t)
        g = int(LEAF_GREEN[1] * (1 - t) + LEAF_YELLOW[1] * t)
        r = int(LEAF_GREEN[2] * (1 - t) + LEAF_YELLOW[2] * t)
        gradient[:, x] = (b, g, r)
    img[mask > 0] = gradient[mask > 0]
    # A faint central vein keeps it leaf-like.
    cx, cy = CENTER
    vein = np.zeros((SIZE, SIZE), dtype=np.uint8)
    cv2.line(vein, (cx - 230, cy), (cx + 230, cy), 255, 3)
    img[vein > 0] = VEIN_GREEN
    _add_noise(img)
    cv2.imwrite(path, img)


def make_non_leaf(path):
    """Colored rectangles with NO foliage hues -> must raise NoLeafDetected.

    WHY a restricted palette (red/blue/magenta on light gray) instead of
    fully random colors: a truly random rectangle could land in the green
    H 25-85 band and legitimately look like a leaf — the rejection test
    would then be testing luck, not the detector.
    """
    rnd, _ = _rngs()
    img = np.full((SIZE, SIZE, 3), 200, dtype=np.uint8)  # light gray, S=0
    palette = [(50, 50, 200),    # red,   H~0
               (200, 50, 50),    # blue,  H~120
               (200, 50, 180)]   # magenta, H~150
    for i in range(6):
        w, h = rnd.randint(120, 260), rnd.randint(90, 220)
        x, y = rnd.randint(0, SIZE - w), rnd.randint(0, SIZE - h)
        cv2.rectangle(img, (x, y), (x + w, y + h), palette[i % 3], -1)
    cv2.imwrite(path, img)


def main(out_dir=OUT_DIR):
    """Generate all five samples. Idempotent: overwrites deterministically."""
    os.makedirs(out_dir, exist_ok=True)
    make_healthy(os.path.join(out_dir, "healthy_leaf.jpg"))
    make_spotted(os.path.join(out_dir, "spotted_leaf.jpg"))
    make_blight(os.path.join(out_dir, "blight_leaf.jpg"))
    make_chlorotic(os.path.join(out_dir, "chlorotic_leaf.jpg"))
    make_non_leaf(os.path.join(out_dir, "non_leaf.jpg"))
    print(f"wrote 5 samples to {out_dir}")


if __name__ == "__main__":
    main()
