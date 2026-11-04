"""Real OpenCV leaf-disease analysis (no fake results).

WHY this design: a viva panel can follow every step — the module is a plain
pipeline of classic computer-vision operations (color segmentation in HSV,
morphology, contours, connected components) plus a *documented* rule-based
classifier. Nothing is a black box: each diagnosis maps to measurable
features (lesion count, mean lesion area, diseased %, yellowness, edge
browning), so "why did it say blight?" always has a numeric answer.

Pipeline (one numbered step per stage, same numbers in the code):
  1. validate_image()  -> extension + <=5 MB guard (fail fast, clear errors)
  2. load + shrink so the longest side is 800 px (speed; detail survives)
  3. Gaussian blur (5x5) to calm sensor noise before color segmentation
  4. leaf mask in HSV: foliage range H 25-85, S>40, V>40 + brown pixels
     touching the leaf (scorch rims live at the margin, outside the green
     hue band) + morphological close + largest contour (must cover >=2% of
     the image, else NoLeafDetectedError)
  5. inside the leaf: brown-lesion mask (H 5-25, S 40-255, V 20-200) and
     yellow/chlorosis mask (H 20-35, S>60), brown applied first so the
     overlapping hue band (20-25) is not double-counted
  6. lesion contours -> count, mean area, mean circularity
  7. edge browning = brown pixels inside the outer 12% band of the leaf /
     total brown pixels
  8. rule-based classifier (priority: blight > leaf_spot > chlorosis >
     leaf_scorch > healthy) + margin-based confidence in [55, 92]
  9. annotated image: leaf outline, lesion contours colored green->red by
     size, label with diagnosis + severity

WHY HSV and not RGB: leaf green vs. lesion brown vs. chlorosis yellow are
separated almost entirely by *hue*; saturation/value only reject the white
background and shadows. RGB thresholds would drift with lighting, HSV does
not (for a viva: "hue is illumination-invariant-ish").

WHY the foliage range starts at H=25 instead of the textbook green 35:
a chlorotic (yellowing) leaf is still a leaf — with H starting at 35 the
yellow half of a sick leaf would be cut out of the mask and chlorosis could
never be measured. Brown lesions live at H 5-25, so nothing necrotic leaks
into the foliage mask.

WHY largest-contour + 2% rule: phone photos contain background. The leaf is
assumed to be the dominant green-yellow object; if it is not, we say so
honestly (NoLeafDetectedError) instead of hallucinating a diagnosis.
"""

import math
import os

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# Public constants / errors
# ---------------------------------------------------------------------------

DIAGNOSIS_IDS = ("healthy", "leaf_spot", "blight", "chlorosis", "leaf_scorch")

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_FILE_BYTES = 5 * 1024 * 1024          # same 5 MB limit as Flask config
MAX_DIM = 800                            # longest side after resize
MIN_LEAF_AREA_FRAC = 0.02                # leaf must cover >=2% of the image
MIN_IMAGE_SIDE = 60                      # px; smaller images carry no detail
MIN_LESION_AREA_PX = 30                  # contour noise floor for lesions


class NoLeafDetectedError(Exception):
    """Raised when no dominant leaf-colored object is found in the photo."""


# ---------------------------------------------------------------------------
# Step 1: input validation (fail fast, before any heavy work)
# ---------------------------------------------------------------------------

def validate_image(path):
    """Check extension + file size.

    WHY separate from analyze_leaf: routes/tests can pre-validate an upload
    without paying for the whole CV pipeline, and the error messages are
    written for the end user, not the developer.

    Raises:
        ValueError: with a plain-language message for a bad upload.
    Returns:
        The verified file size in bytes (handy for logging).
    """
    if not os.path.isfile(path):
        raise ValueError(f"File not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported image format '{ext or '(none)'}'. "
            "Please upload a JPG or PNG photo of the leaf."
        )
    size = os.path.getsize(path)
    if size > MAX_FILE_BYTES:
        raise ValueError(
            f"Image is {size / (1024 * 1024):.1f} MB, over the 5 MB limit. "
            "Please use a smaller photo."
        )
    return size


# ---------------------------------------------------------------------------
# Steps 2-4: load, resize, denoise, find the leaf
# ---------------------------------------------------------------------------

def _load_and_resize(path):
    """Read with cv2.imread; shrink (never upscale) so max side == MAX_DIM.

    WHY shrink-only: upscaling invents pixels and slows everything down;
    800 px keeps even small spots measurable (a 5-px lesion stays ~5 px).
    """
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        # WHY ValueError not "return None": the file passed validate_image's
        # extension check but is not decodable (e.g. renamed .txt) — the
        # caller must know the photo is unusable, not get a silent None.
        raise ValueError(
            "That file could not be decoded as an image. "
            "Please upload a real JPG/PNG photo."
        )
    h, w = img.shape[:2]
    if min(h, w) < MIN_IMAGE_SIDE:
        raise ValueError(
            f"Image is only {w}x{h} px — too small to analyze. "
            "Please upload a clearer, closer photo of the leaf."
        )
    scale = MAX_DIM / max(h, w)
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    return img


def _find_leaf_mask(hsv, img_shape):
    """Segment the leaf: foliage hue range + margin browning + close.

    Returns (leaf_mask, leaf_contour). Raises NoLeafDetectedError when the
    largest leaf-colored blob covers less than MIN_LEAF_AREA_FRAC of the
    image — i.e. "there is no leaf here", stated honestly.

    WHY brown pixels are merged into the leaf: scorch/margin burn sits at
    the leaf rim in the brown hue band (H 5-25), *outside* the green foliage
    range. Without this step the detector would see only the surviving
    green interior and the burnt margin would vanish from every metric.
    Only brown within 12% of the leaf's equivalent radius of the foliage
    edge is absorbed — WHY the cap: a brown wooden table touching the leaf
    must not become "leaf". The 12% mirrors the edge-browning band below.
    """
    h, w = img_shape
    # Foliage = green-to-yellow. S>40 rejects the white background and gray
    # shadows; V>40 rejects near-black noise. (H starts at 25, not 35 — see
    # the module docstring: chlorotic yellowing must stay inside the leaf.)
    foliage = cv2.inRange(hsv, np.array([25, 40, 40], dtype=np.uint8),
                          np.array([85, 255, 255], dtype=np.uint8))
    # Morphological close (7x7 ellipse): fills small holes (veins, glare
    # specks) and joins a leaf that the hue threshold split in two — WHY
    # close and not open: we want to *fill gaps inside* the leaf, not erase
    # thin leaf parts.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    foliage = cv2.morphologyEx(foliage, cv2.MORPH_CLOSE, kernel)

    fol_area = cv2.countNonZero(foliage)
    if fol_area == 0:
        raise NoLeafDetectedError(
            "No leaf detected in this photo — no green/yellow leaf-colored "
            "region was found. Try a closer photo with the leaf filling "
            "most of the frame."
        )
    # Absorb near-margin browning into the leaf region.
    brown_raw = cv2.inRange(hsv, np.array([5, 40, 20], dtype=np.uint8),
                            np.array([25, 255, 200], dtype=np.uint8))
    dist_from_foliage = cv2.distanceTransform(cv2.bitwise_not(foliage),
                                              cv2.DIST_L2, 3)
    equiv_radius = math.sqrt(fol_area / math.pi)
    near_leaf = (dist_from_foliage <= 0.12 * equiv_radius).astype(np.uint8)
    near_leaf *= 255
    brown_adjacent = cv2.bitwise_and(brown_raw, brown_raw, mask=near_leaf)

    region = cv2.bitwise_or(foliage, brown_adjacent)
    region = cv2.morphologyEx(region, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise NoLeafDetectedError(
            "No leaf detected in this photo — no green/yellow leaf-colored "
            "region was found. Try a closer photo with the leaf filling "
            "most of the frame."
        )
    leaf_contour = max(contours, key=cv2.contourArea)
    leaf_area = cv2.contourArea(leaf_contour)
    if leaf_area < MIN_LEAF_AREA_FRAC * h * w:
        raise NoLeafDetectedError(
            "No leaf detected in this photo — the largest leaf-colored "
            "region is too small. Move closer so the leaf fills the frame."
        )
    leaf_mask = np.zeros((h, w), dtype=np.uint8)
    cv2.drawContours(leaf_mask, [leaf_contour], -1, 255, thickness=cv2.FILLED)
    return leaf_mask, leaf_contour


# ---------------------------------------------------------------------------
# Steps 5-7: lesions, yellowness, edge browning
# ---------------------------------------------------------------------------

def _segment_damage(hsv, leaf_mask):
    """Split the leaf interior into brown lesions and yellow chlorosis.

    Brown (necrotic) lesions: H 5-25 — dead tissue loses green hue and drops
    in value while staying saturated; tuned so healthy green (H 35-85) and
    yellow chlorosis (H 20-35, high S) do not leak in.
    Yellow (chlorosis): H 20-35, S>60 — pale yellowing keeps value high.
    WHY brown first: the H 20-25 band overlaps both ranges; necrotic brown
    is subtracted before yellowness is measured so one pixel is never
    counted as both diseases.
    """
    # Work on a lightly blurred HSV so single-pixel hue noise does not
    # shatter lesions into confetti.
    brown = cv2.inRange(hsv, np.array([5, 40, 20], dtype=np.uint8),
                        np.array([25, 255, 200], dtype=np.uint8))
    brown = cv2.bitwise_and(brown, brown, mask=leaf_mask)

    yellow_raw = cv2.inRange(hsv, np.array([20, 60, 40], dtype=np.uint8),
                             np.array([35, 255, 255], dtype=np.uint8))
    yellow_raw = cv2.bitwise_and(yellow_raw, yellow_raw, mask=leaf_mask)
    # Brown wins the overlap band (see docstring above).
    yellow = cv2.bitwise_and(yellow_raw, yellow_raw,
                             mask=cv2.bitwise_not(brown))
    return brown, yellow


def _lesion_stats(brown_mask):
    """Connected lesion contours -> count, mean area, mean circularity.

    WHY contours instead of connectedComponents: a contour gives a
    perimeter, and circularity = 4*pi*area/perimeter^2 separates round
    fungal spots (~0.8-1.0) from irregular blight patches (~0.3-0.6).
    Contours below MIN_LESION_AREA_PX are sensor noise, not disease.
    """
    contours, _ = cv2.findContours(brown_mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    areas, circularities = [], []
    for c in contours:
        area = cv2.contourArea(c)
        if area < MIN_LESION_AREA_PX:
            continue
        perim = cv2.arcLength(c, True)
        if perim <= 0:
            continue
        areas.append(area)
        circularities.append(4.0 * math.pi * area / (perim * perim))
    count = len(areas)
    mean_area = float(np.mean(areas)) if areas else 0.0
    mean_circ = float(np.mean(circularities)) if circularities else 0.0
    return count, mean_area, mean_circ, contours


def _edge_browning_ratio(leaf_mask, brown_mask):
    """Fraction of brown pixels living in the leaf's outer 12% band.

    WHY: leaf scorch starts at the margins (salt/heat/wind burn creeps
    inward), while spots and blight strike the blade interior. A high ratio
    therefore points at scorch, not at spot diseases.
    The band is built by eroding the leaf mask by 12% of the leaf's
    equivalent radius and subtracting — pure morphology, no magic.
    """
    leaf_area = cv2.countNonZero(leaf_mask)
    brown_total = cv2.countNonZero(brown_mask)
    if brown_total == 0:
        return 0.0
    equiv_radius = math.sqrt(leaf_area / math.pi)
    erode_px = max(1, int(round(0.12 * equiv_radius)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                       (2 * erode_px + 1, 2 * erode_px + 1))
    inner = cv2.erode(leaf_mask, kernel)
    band = cv2.subtract(leaf_mask, inner)
    brown_in_band = cv2.countNonZero(cv2.bitwise_and(brown_mask, brown_mask,
                                                     mask=band))
    return brown_in_band / brown_total


# ---------------------------------------------------------------------------
# Step 8: rule-based classifier (every rule is a comment a viva can quote)
# ---------------------------------------------------------------------------

def _classify(diseased_pct, lesion_count, mean_lesion_area, mean_circularity,
              yellowness_pct, edge_ratio):
    """Return (diagnosis_id, margin) — margin in [0,1] feeds confidence.

    Priority order (WHY this order):
      blight > leaf_spot > chlorosis > leaf_scorch > healthy
    A leaf can show two symptoms at once (spots on a yellowing leaf). The
    order encodes *treatment urgency*: blight destroys tissue fast and needs
    immediate fungicide + sanitation, so it outranks everything; many small
    round spots are the classic fungal leaf-spot signature; chlorosis is a
    slower nutrient problem; scorch is environmental; healthy is the default
    only when no rule fires.
    """
    # BLIGHT: big destructive patches. diseased_pct>=8 means a large share
    # of the blade is already necrotic; mean lesion area>=600 px separates
    # "a few merged spots" from true patches at 800-px working resolution.
    # WHY the edge_ratio guard: browning dominated by the margin band is
    # scorch (environmental), not blight — blight strikes the blade
    # interior. Without the guard a fully scorched rim would misfire here.
    if diseased_pct >= 8.0 and mean_lesion_area >= 600.0 and edge_ratio < 0.5:
        margin = min(max((diseased_pct - 8.0) / 10.0, 0.0), 1.0)
        return "blight", margin

    # LEAF SPOT: many (>=8) small, round lesions — the textbook signature of
    # fungal/bacterial spot diseases (e.g. Cercospora, bacterial leaf spot).
    # Circularity >=0.55 keeps irregular blight fragments out of this bucket.
    if lesion_count >= 8 and mean_circularity >= 0.55:
        margin = min(max((lesion_count - 8) / 24.0, 0.0), 1.0)
        return "leaf_spot", margin

    # CHLOROSIS: >15% of the blade yellowed. Below 15% is natural variegation
    # / lighting; above it signals nitrogen/iron deficiency or virus.
    if yellowness_pct > 15.0:
        margin = min(max((yellowness_pct - 15.0) / 25.0, 0.0), 1.0)
        return "chlorosis", margin

    # LEAF SCORCH: most browning sits on the margin band — salt, heat or
    # wind burn rather than a pathogen in the blade interior.
    if edge_ratio > 0.5 and diseased_pct >= 2.0:
        margin = min(max((edge_ratio - 0.5) / 0.4, 0.0), 1.0)
        return "leaf_scorch", margin

    # HEALTHY: <2% diseased area is dust, glare or a healed wound — not
    # disease. WHY not 0%: a real photo always has a few stray brown pixels.
    margin = min(max((2.0 - diseased_pct) / 2.0, 0.0), 1.0)
    return "healthy", margin


def _confidence(margin):
    """Honest confidence: 55 + margin*37, hard-capped at 92.

    WHY this shape: 55 is the floor — even a clear-cut case is a heuristic
    on one photo, so we never claim certainty. The bonus grows with the
    *distance of the winning feature past its decision threshold* (a leaf
    with 40 spots is a surer leaf_spot than one with 9). The 92 cap is
    deliberate: this is image heuristics, not a lab test — 99/100 would be
    a lie, and the viva panel will ask exactly this.
    """
    margin = min(max(margin, 0.0), 1.0)
    return round(min(92.0, 55.0 + 37.0 * margin), 1)


def _severity(diseased_pct, diagnosis_id):
    """Severity from diseased % of blade: <5 Low, 5-15 Moderate, >15 High.

    WHY these bands: under 5% a plant outgrows the damage; 5-15% needs
    treatment soon; over 15% the leaf's photosynthesis is seriously
    compromised. A healthy leaf reports 'Low' (vigor good).
    """
    if diseased_pct < 5.0:
        return "Low"
    if diseased_pct <= 15.0:
        return "Moderate"
    return "High"


# ---------------------------------------------------------------------------
# Step 9: annotated output image
# ---------------------------------------------------------------------------

def _annotate(img, leaf_contour, brown_mask, diagnosis_id, severity,
              diseased_pct, out_path):
    """Draw leaf outline + lesion contours (green->red by size) + label.

    WHY green->red by size: in a viva/demo the viewer instantly sees which
    lesions drove the diagnosis — the biggest (reddest) patches matter most.
    """
    annotated = img.copy()
    # Leaf outline in cyan.
    cv2.drawContours(annotated, [leaf_contour], -1, (255, 255, 0), 3)

    contours, _ = cv2.findContours(brown_mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    big = [c for c in contours if cv2.contourArea(c) >= MIN_LESION_AREA_PX]
    max_area = max((cv2.contourArea(c) for c in big), default=1.0)
    for c in big:
        # t=0 (tiny) -> green, t=1 (largest) -> red. BGR lerp.
        t = cv2.contourArea(c) / max_area
        color = (0, int(255 * (1 - t)), int(255 * t))
        cv2.drawContours(annotated, [c], -1, color, 2)

    label = f"{diagnosis_id} | {severity} | diseased {diseased_pct:.1f}%"
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
    cv2.rectangle(annotated, (8, 8), (8 + tw + 16, 8 + th + 16), (0, 0, 0),
                  cv2.FILLED)
    cv2.putText(annotated, label, (16, 8 + th + 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
                cv2.LINE_AA)
    cv2.imwrite(out_path, annotated)
    return out_path


def _diagnosis_name(diagnosis_id):
    """English display name without importing the knowledge module.

    WHY duplicated here instead of importing knowledge.get_treatment: vision
    must stay importable even if the knowledge file is mid-edit by a
    teammate; the name is display-only, the KB remains the source of truth.
    """
    names = {
        "healthy": "Healthy",
        "leaf_spot": "Leaf Spot",
        "blight": "Blight",
        "chlorosis": "Chlorosis (Yellowing)",
        "leaf_scorch": "Leaf Scorch",
    }
    return names.get(diagnosis_id, diagnosis_id)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_leaf(image_path, save_annotated_path=None):
    """Analyze one leaf photo and return a diagnosis dict.

    Args:
        image_path: path to a JPG/PNG leaf photo.
        save_annotated_path: where to write the annotated image; when None
            a "<name>_annotated.<ext>" file is written next to the input.

    Returns:
        dict with keys: diagnosis_id, diagnosis_en, severity
        ('Low'|'Moderate'|'High'), confidence (55-92), diseased_pct,
        lesion_count, mean_lesion_area_px, yellowness_pct,
        edge_browning_ratio, greenness_score, annotated_path, note.
        (English only; diagnosis_en is kept because the disease route
        stores it in Analysis.diagnosis_en.)

    Raises:
        ValueError: bad file (missing, wrong extension, >5 MB, undecodable,
            too small).
        NoLeafDetectedError: no dominant leaf-colored region in the photo.

    WHY no module-level mutable state: the function is pure pipeline — safe
    for many sequential calls (upload after upload) with no cross-talk.
    """
    validate_image(image_path)                       # step 1
    img = _load_and_resize(image_path)               # step 2
    # Step 3: blur once, reuse the HSV image for leaf finding AND damage
    # segmentation — WHY once: the hue field must be identical in both
    # stages or a pixel could count as leaf in one and damage in the other.
    hsv = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0),
                       cv2.COLOR_BGR2HSV)
    leaf_mask, leaf_contour = _find_leaf_mask(hsv, img.shape[:2])  # step 4
    brown_mask, yellow_mask = _segment_damage(hsv, leaf_mask)      # step 5

    leaf_px = cv2.countNonZero(leaf_mask)
    brown_px = cv2.countNonZero(brown_mask)
    yellow_px = cv2.countNonZero(yellow_mask)
    diseased_pct = 100.0 * brown_px / leaf_px
    yellowness_pct = 100.0 * yellow_px / leaf_px
    # Greenness = "vigor index": blade area that is neither necrotic nor
    # chlorotic. A healthy leaf scores near 100.
    greenness_score = round(100.0 * (leaf_px - brown_px - yellow_px)
                            / leaf_px, 1)

    lesion_count, mean_area, mean_circ, _ = _lesion_stats(brown_mask)  # 6
    edge_ratio = _edge_browning_ratio(leaf_mask, brown_mask)           # 7

    diagnosis_id, margin = _classify(diseased_pct, lesion_count, mean_area,
                                     mean_circ, yellowness_pct, edge_ratio)
    confidence = _confidence(margin)                                  # 8
    severity = _severity(diseased_pct, diagnosis_id)

    if save_annotated_path is None:
        stem, ext = os.path.splitext(image_path)
        save_annotated_path = f"{stem}_annotated{ext}"
    annotated_path = _annotate(img, leaf_contour, brown_mask, diagnosis_id,
                               severity, diseased_pct, save_annotated_path)

    name_en = _diagnosis_name(diagnosis_id)
    notes = {
        "healthy": "Leaf looks vigorous. Keep the current watering and "
                   "nutrition schedule.",
        "leaf_spot": "Many small spots suggest a fungal/bacterial spot "
                     "disease — check the treatment tab.",
        "blight": "Large dead patches need quick action — remove affected "
                  "leaves and treat without delay.",
        "chlorosis": "Yellowing points to a nutrient deficiency (often "
                     "nitrogen or iron) — soil test recommended.",
        "leaf_scorch": "Margin burn is usually environmental (heat, wind, "
                       "salty water) rather than infection.",
    }
    return {
        "diagnosis_id": diagnosis_id,
        "diagnosis_en": name_en,
        "severity": severity,
        "confidence": confidence,
        "diseased_pct": round(diseased_pct, 2),
        "lesion_count": lesion_count,
        "mean_lesion_area_px": round(mean_area, 1),
        "yellowness_pct": round(yellowness_pct, 2),
        "edge_browning_ratio": round(edge_ratio, 3),
        "greenness_score": greenness_score,
        "annotated_path": annotated_path,
        "note": notes.get(diagnosis_id, ""),
    }
