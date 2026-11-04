"""Treatment knowledge base: diagnosis -> agronomic advice (English only).

WHY a plain-Python KB instead of a database table: the content is curated
reference text written once (not user data), it must work with zero setup,
and a viva panel can read it directly. get_treatment() is a pure function —
unknown ids fall back to a generic entry instead of crashing the result page.

Content rule used throughout: every recommendation is standard agronomic
practice (sanitation, resistant varieties, balanced nutrition, correct
fungicide groups, water management). Nothing here replaces a local
agriculture officer's diagnosis for a severe outbreak.
"""

# ---------------------------------------------------------------------------
# Diagnosis entries: {id, name, symptoms[], prevention[], treatment[],
#                     advice, crops_affected[]}
# `advice` is a one-line summary the route stores as Analysis.notes.
# ---------------------------------------------------------------------------

_TREATMENTS = {
    "healthy": {
        "id": "healthy",
        "name": "Healthy",
        "symptoms": [
            "Uniform green color across the leaf blade",
            "No spots, patches, wilting, or curling",
            "Firm leaf texture with normal growth",
        ],
        "prevention": [
            "Keep the current balanced fertilizer schedule",
            "Water at the base of plants, preferably in the morning",
            "Scout the field weekly for early signs of pests or disease",
            "Rotate crops each season to break pest and disease cycles",
        ],
        "treatment": [
            "No treatment needed — the plant is vigorous",
            "Continue regular irrigation and nutrition",
            "Remove weeds around the plants to reduce competition",
        ],
        "advice": "Leaf looks vigorous. Keep the current watering and nutrition schedule.",
        "crops_affected": ["wheat", "rice", "cotton", "sugarcane", "maize",
                           "potato", "tomato", "citrus"],
    },

    "leaf_spot": {
        "id": "leaf_spot",
        "name": "Leaf Spot",
        "symptoms": [
            "Many small, roughly circular brown or black spots on leaves",
            "Spots may have yellow halos around them",
            "Severely spotted leaves turn yellow and drop early",
            "Spots often start on lower, older leaves and move upward",
        ],
        "prevention": [
            "Use certified disease-free seed and resistant varieties",
            "Avoid overhead irrigation — wet leaves invite spot fungi",
            "Give plants proper spacing for air circulation",
            "Rotate with a non-host crop for at least one season",
            "Remove and destroy fallen infected leaves (do not compost)",
        ],
        "treatment": [
            "Prune off badly spotted leaves and destroy them away from the field",
            "Apply a copper-based or mancozeb fungicide as per label dose",
            "Repeat spray after 10–14 days if spots keep spreading",
            "Spray early morning or late evening; never in hot midday sun",
            "Improve drainage — waterlogged soil weakens plant defenses",
        ],
        "advice": "Fungal/bacterial leaf spot likely. Remove affected leaves and apply a copper-based fungicide.",
        "crops_affected": ["wheat", "rice", "cotton", "maize", "potato",
                           "tomato", "citrus"],
    },

    "blight": {
        "id": "blight",
        "name": "Blight",
        "symptoms": [
            "Large, irregular brown/black dead patches on leaves",
            "Patches expand fast, sometimes with a water-soaked margin",
            "Infected leaves wither and die; stems may also rot",
            "Spreads rapidly in warm, humid weather",
        ],
        "prevention": [
            "Plant resistant/tolerant varieties where available",
            "Never work in the field when plants are wet",
            "Ensure good drainage — blight loves waterlogged soil",
            "Rotate crops: avoid planting the same family in the same field yearly",
            "Destroy crop residue after harvest instead of ploughing it in",
        ],
        "treatment": [
            "Act fast: cut and burn/bury severely blighted plants immediately",
            "Apply a systemic fungicide (e.g. metalaxyl + mancozeb) at label dose",
            "Stop overhead watering; irrigate at the base only",
            "Disinfect tools with bleach solution between plants",
            "Do not save seed/tubers from an infected crop",
        ],
        "advice": "Blight spreads fast. Remove affected leaves/plants at once and apply a systemic fungicide.",
        "crops_affected": ["potato", "tomato", "rice", "wheat", "maize"],
    },

    "chlorosis": {
        "id": "chlorosis",
        "name": "Chlorosis (Yellowing)",
        "symptoms": [
            "Leaves turn pale green to yellow while veins may stay green",
            "Yellowing often starts on older leaves (nitrogen) or young leaves (iron)",
            "Growth slows; plants look weak and stunted",
            "No spots or dead patches — the leaf is intact but discolored",
        ],
        "prevention": [
            "Test soil pH and nutrients before each season",
            "Apply balanced NPK fertilizer at the recommended dose",
            "Add organic matter (farmyard manure/compost) to improve uptake",
            "Avoid overwatering, which washes nutrients out of the root zone",
        ],
        "treatment": [
            "Get a soil test to identify the exact deficiency (N, Fe, Mg, Zn)",
            "For nitrogen deficiency: apply urea as per recommendation",
            "For iron deficiency in alkaline soils: foliar spray of chelated iron",
            "Correct soil pH — very alkaline soil locks up iron and zinc",
            "Mulch around plants to keep nutrients and moisture stable",
        ],
        "advice": "Yellowing suggests a nutrient deficiency. Get a soil test and correct NPK/iron as needed.",
        "crops_affected": ["wheat", "rice", "cotton", "sugarcane", "maize",
                           "citrus", "tomato"],
    },

    "leaf_scorch": {
        "id": "leaf_scorch",
        "name": "Leaf Scorch",
        "symptoms": [
            "Leaf edges and tips turn brown and dry, as if burnt",
            "Browning starts at the margin and moves inward",
            "Often appears after heatwaves, strong dry wind, or salty water",
            "No round spots in the leaf interior (unlike leaf spot)",
        ],
        "prevention": [
            "Mulch the soil to keep roots cool and moist",
            "Irrigate deeply before expected heatwaves",
            "Use windbreaks on the exposed side of the field",
            "Test irrigation water — high salt (EC) causes margin burn",
        ],
        "treatment": [
            "Give a deep watering to leach excess salts below the root zone",
            "Trim fully dead leaf margins with clean scissors (optional, cosmetic)",
            "Reduce fertilizer dose temporarily — excess salts worsen scorch",
            "Shade young plants during extreme heat if possible",
            "No fungicide needed: scorch is environmental, not infectious",
        ],
        "advice": "Margin burn is usually heat/wind/salt stress, not infection. Water deeply and mulch the soil.",
        "crops_affected": ["citrus", "cotton", "sugarcane", "maize", "wheat"],
    },
}

# Generic fallback for any diagnosis id we do not recognize. WHY a fallback
# instead of KeyError: the result page must never crash because a new
# diagnosis id was added to vision.py before its KB entry was written.
_FALLBACK = {
    "id": "unknown",
    "name": "Unknown condition",
    "symptoms": ["The analysis could not match a known disease pattern."],
    "prevention": [
        "Keep field hygiene and balanced nutrition",
        "Consult your local agriculture officer with a clear photo",
    ],
    "treatment": [
        "Monitor the plant for 2–3 days and re-analyze",
        "Do not spray chemicals without identifying the problem",
    ],
    "advice": "Condition not recognized. Monitor the plant and consult an agriculture officer.",
    "crops_affected": [],
}

# ---------------------------------------------------------------------------
# Crop catalogue (id -> English name), English only.
# ---------------------------------------------------------------------------

CROP_INFO = {
    "wheat": {"id": "wheat", "name": "Wheat"},
    "rice": {"id": "rice", "name": "Rice"},
    "cotton": {"id": "cotton", "name": "Cotton"},
    "sugarcane": {"id": "sugarcane", "name": "Sugarcane"},
    "maize": {"id": "maize", "name": "Maize"},
    "potato": {"id": "potato", "name": "Potato"},
    "tomato": {"id": "tomato", "name": "Tomato"},
    "citrus": {"id": "citrus", "name": "Citrus"},
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_treatment(diagnosis_id):
    """Return the treatment entry for a diagnosis id (English only).

    Always returns a dict with keys: id, name, symptoms[], prevention[],
    treatment[], advice, crops_affected[]. Unknown ids (and None/"") return
    the generic fallback entry — never raise, the result page depends on it.
    """
    key = (diagnosis_id or "").strip().lower()
    entry = _TREATMENTS.get(key, _FALLBACK)
    # WHY a shallow copy: callers (routes/templates) must not be able to
    # mutate the module-level KB for the next request.
    return dict(entry)


def get_crop_info(crop_id):
    """Return {id, name} for a crop, or None when unknown."""
    if not crop_id:
        return None
    return CROP_INFO.get(str(crop_id).strip().lower())


def list_diagnoses():
    """All known diagnosis ids (useful for admin pages / tests)."""
    return list(_TREATMENTS.keys())
