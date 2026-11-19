import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from backend.app.config import SCREENING_LINE_MIN_CONFIDENCE
from backend.app.models.enums import ScreeningVerdict

logger = logging.getLogger("campus_security.delivery_policy")

# Deterministic delivery screening policy (Phase 7). Keyword lists adapted from the Track C
# lexical baseline (research_track/track_c/src/classifier_interface.py); production code does
# not import research_track. OCR only reads the text; this table alone sets the verdict, and
# the guard makes the decision. Nothing here blocks a delivery.

@dataclass(frozen=True)
class CategoryRule:
    category: str
    label: str
    reason_code: str
    verdict: ScreeningVerdict
    keywords: Tuple[str, ...]

RULES: Tuple[CategoryRule, ...] = (
    CategoryRule("TOBACCO", "Tobacco", "TOBACCO_RESTRICTED", ScreeningVerdict.ALERT, (
        "cigarette", "cigarettes", "cigar", "cigars", "beedi", "bidi", "gutka", "gutkha", "zarda", "khaini",
        "tobacco", "vape", "vapes", "e-cigarette", "e cigarette", "hookah", "hukka", "nicotine", "snus",
        "marlboro", "gold flake", "classic milds",
    )),
    CategoryRule("ALCOHOL", "Alcohol", "ALCOHOL_RESTRICTED", ScreeningVerdict.ALERT, (
        "beer", "beers", "whisky", "whiskey", "vodka", "rum", "gin", "wine", "brandy", "tequila", "liquor",
        "alcohol", "daru", "old monk", "breezer", "champagne",
    )),
    CategoryRule("WEAPON", "Weapon", "WEAPON_RESTRICTED", ScreeningVerdict.ALERT, (
        "knife", "knives", "dagger", "sword", "machete", "gun", "pistol", "revolver", "air gun", "airgun",
        "ammunition", "ammo", "cartridge", "bullets", "pepper spray", "taser", "stun gun", "knuckle duster",
        "blade",
    )),
    CategoryRule("HAZMAT", "Hazardous chemical", "HAZMAT_NEEDS_APPROVAL", ScreeningVerdict.REVIEW, (
        "cleaner", "toilet cleaner", "drain cleaner", "harpic", "lizol", "acid", "bleach", "phenyl", "phenyle",
        "kerosene", "lighter fluid", "thinner", "turpentine", "insecticide", "pesticide", "rat poison",
        "naphthalene", "petrol", "diesel", "butane", "methylated spirit", "hit spray", "mosquito spray",
        "detergent", "surf excel", "ariel", "colin", "comfort", "domex", "all out", "good knight", "baygon",
        "mortein", "odonil", "drano", "gainda",
    )),
    CategoryRule("MEDICINE", "Medicine", "MEDICINE_NEEDS_APPROVAL", ScreeningVerdict.REVIEW, (
        "medicine", "tablet", "tablets", "capsule", "capsules", "syrup", "cough syrup", "paracetamol",
        "crocin", "dolo", "ibuprofen", "antibiotic", "injection", "ointment", "codeine", "tramadol",
        "alprazolam", "diazepam", "sleeping pill", "sleeping pills", "antiseptic", "bandage", "digene",
        "electral", "eno", "moov", "ors", "vicks", "strepsils", "betadine", "boroline", "volini",
    )),
    CategoryRule("FOOD", "Food", "FOOD_OK", ScreeningVerdict.ALLOW, (
        "noodles", "instant noodles", "maggi", "chips", "biscuit", "biscuits", "bread", "rice", "dal", "atta",
        "flour", "sugar", "salt", "milk", "butter", "cheese", "paneer", "egg", "eggs", "eggoz", "fruit", "fruits",
        "apple", "apples", "banana", "bananas", "chocolate", "chocolates", "snack", "snacks", "namkeen",
        "kurkure", "lays", "pizza", "burger", "sandwich", "biryani", "roti", "paratha", "curry", "meal",
        "thali", "momos", "cake", "cookies", "oats", "cereal", "cornflakes", "jam", "sauce", "ketchup",
        "pasta", "soup", "chicken", "mutton", "fish", "ice cream", "curd", "yogurt", "garlic bread",
        "fries", "wrap", "rolls", "dosa", "idli", "samosa", "sweets", "oil", "sunflower oil", "mustard oil",
        "ghee", "besan", "sooji", "rava", "maida", "poha", "dalia", "corn flour", "potato", "onion", "tomato",
        "bhujia", "sev", "peanut", "peanuts", "cashew", "cashews", "almond", "almonds", "walnut", "walnuts",
        "raisin", "raisins", "spices", "turmeric", "chilli", "coriander", "cumin", "garam masala", "honey",
        "nutella", "waffle", "gulab jamun", "rasgulla", "laddu", "kaju katli", "halwa", "jalebi", "barfi",
        "peda", "kheer", "party mix", "mix", "mixture", "trail mix", "makhana", "dry fruit", "dry fruits",
        "roasted", "farmley", "seeds", "fox nuts", "crisps", "wafers", "bbq", "bbq mix", "barbeque",
    )),
    CategoryRule("BEVERAGE", "Beverage", "BEVERAGE_OK", ScreeningVerdict.ALLOW, (
        "cola", "coke", "pepsi", "sprite", "fanta", "soda", "juice", "water", "mineral water", "tea",
        "assam tea", "gold tea", "green tea", "black tea", "coffee", "energy drink", "red bull", "lassi",
        "buttermilk", "soft drink", "shake", "milkshake", "lemonade", "cold brew", "macchiato", "chai", "aamras",
    )),
    CategoryRule("STATIONERY", "Stationery", "STATIONERY_OK", ScreeningVerdict.ALLOW, (
        "notebook", "notebooks", "pen", "pens", "pencil", "pencils", "eraser", "register", "a4", "paper",
        "file", "folder", "marker", "markers", "highlighter", "stapler", "notepad", "diary", "geometry box",
        "glue", "sketch", "sticky notes", "calculator", "book", "textbook",
    )),
    CategoryRule("PERSONAL_CARE", "Personal care", "PERSONAL_CARE_OK", ScreeningVerdict.ALLOW, (
        "soap", "shampoo", "conditioner", "toothpaste", "toothbrush", "deodorant", "lotion", "cream",
        "face wash", "handwash", "hand wash", "sanitizer", "tissue", "tissues", "napkin", "napkins",
        "sanitary pad", "sanitary pads", "comb", "moisturiser", "moisturizer", "sunscreen", "germ protection",
        "colgate", "closeup", "pepsodent", "sensodyne", "oral-b", "dettol soap", "body wash",
    )),
    CategoryRule("ELECTRONICS", "Electronics", "ELECTRONICS_OK", ScreeningVerdict.ALLOW, (
        "charger", "cable", "earphones", "headphones", "earbuds", "power bank", "mouse", "keyboard", "usb",
        "adapter", "pendrive", "pen drive", "bulb", "extension board", "laptop", "phone cover", "batteries",
        "cooling pad",
    )),
    CategoryRule("SERVICE", "Service & logistics fees", "SERVICE_FEE_OK", ScreeningVerdict.ALLOW, (
        "trip", "trip base fare", "base fare", "waiting & access fee", "waiting fee", "access fee",
        "toll charges", "toll", "parking fee", "parking", "platform fee", "handling charge",
        "handling fee", "packaging charge", "packaging fee", "delivery fee", "delivery partner fee",
        "delivery charge", "small cart fee", "late night surcharge", "late night fee", "rain surge fee",
        "surge fee", "surge", "cgst", "sgst", "gst", "service tax", "gst service tax", "rounding adjustment",
        "round off", "convenience fee", "restaurant packaging",
    )),
)

UNKNOWN = CategoryRule("UNKNOWN", "Unknown", "UNKNOWN_CATEGORY", ScreeningVerdict.REVIEW, ())
UNREADABLE_REASON = "UNREADABLE_LINE"

RULE_BY_CAT: Dict[str, CategoryRule] = {r.category: r for r in RULES}

# For a reader of the table: every reason code and the verdict it maps to.
REASON_VERDICTS: Dict[str, ScreeningVerdict] = {
    **{r.reason_code: r.verdict for r in RULES},
    "SERVICE_FEE": ScreeningVerdict.ALLOW,
    "SERVICE_FEE_OK": ScreeningVerdict.ALLOW,
    "SERVICE_OK": ScreeningVerdict.ALLOW,
    "TOXIC_OR_CORROSIVE": ScreeningVerdict.REVIEW,
    "SAFE_FOOD": ScreeningVerdict.ALLOW,
    "SAFE_HYGIENE": ScreeningVerdict.ALLOW,
    "MEDICAL_ITEM": ScreeningVerdict.REVIEW,
    "CONTRABAND_OR_FLAMMABLE": ScreeningVerdict.ALERT,
    "POISONOUS_OR_TOXIC": ScreeningVerdict.ALERT,
    UNKNOWN.reason_code: UNKNOWN.verdict,
    UNREADABLE_REASON: ScreeningVerdict.REVIEW,
}
CATEGORY_LABELS: Dict[str, str] = {**{r.category: r.label for r in RULES}, UNKNOWN.category: UNKNOWN.label}

_SEVERITY = {ScreeningVerdict.ALLOW: 0, ScreeningVerdict.REVIEW: 1, ScreeningVerdict.ALERT: 2}

def _pattern(keyword: str) -> re.Pattern:
    words = [re.escape(w) for w in re.split(r"[\s-]+", keyword)]
    return re.compile(r"(?<![a-z0-9])" + r"[\s-]*".join(words) + r"(?![a-z0-9])", re.IGNORECASE)

_COMPILED: List[Tuple[CategoryRule, str, re.Pattern]] = [(rule, kw, _pattern(kw)) for rule in RULES for kw in rule.keywords]

_PACK_WEIGHT_RE = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*(?:kg|g|gm|gms|l|ltr|litre|litres|ml|m|cm|mm|oz|lb|lbs)\b"
    r"|pack\s+of\s+\d+\b|\d+\s*(?:pk|pcs|pc|pack|sachets?|bags?|strips?|cans?|bottles?|pouches?)\b"
    r"|\b\d+[-/]\s*pack\b|\b\d+[-/]\s*pk\b|\b\d+[-/]\s*pc\b|\b\d+[-/]\s*s\b|\b\d+\s*x\s*\d+\b)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------- Quick-Commerce Taxonomy Integration
_TAXONOMY_EXACT: Dict[str, Tuple[CategoryRule, str]] = {}
_TAXONOMY_ROOTS: Dict[str, Tuple[CategoryRule, str]] = {}
_KNOWN_BRANDS = set()

def _init_taxonomy() -> None:
    csv_paths = [
        Path(__file__).resolve().parent.parent.parent.parent / "research_track" / "datasets" / "indian_grocery_taxonomy_seed.csv",
        Path("research_track/datasets/indian_grocery_taxonomy_seed.csv"),
    ]
    target_csv = next((p for p in csv_paths if p.is_file()), None)
    if not target_csv:
        logger.warning("indian_grocery_taxonomy_seed.csv not found; running with compiled institutional rules.")
        return

    try:
        with open(target_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cat_csv = row.get("category", "")
                verdict_csv = row.get("verdict", "")
                root = (row.get("canonical_root") or "").strip().lower()
                brand = (row.get("brand") or "").strip()
                item = (row.get("item_name") or "").strip()
                if brand:
                    _KNOWN_BRANDS.add(brand.lower())

                # Map taxonomy rows to CategoryRule
                if verdict_csv == "ALERT":
                    if cat_csv == "PROHIBITED_CONTRABAND":
                        if any(t in root for t in ("cigarette", "cigar", "vape", "tobacco", "hookah", "beedi", "gutka")):
                            rule = RULE_BY_CAT["TOBACCO"]
                        elif any(a in root for a in ("beer", "whisky", "whiskey", "vodka", "rum", "gin", "wine", "liquor", "alcohol")):
                            rule = RULE_BY_CAT["ALCOHOL"]
                        else:
                            rule = RULE_BY_CAT["WEAPON"]
                    else:
                        rule = RULE_BY_CAT["HAZMAT"]
                elif verdict_csv == "REVIEW":
                    if cat_csv in ("HOUSEHOLD_CLEANER", "POISONOUS_CHEMICAL"):
                        rule = RULE_BY_CAT["HAZMAT"]
                    elif cat_csv == "PHARMACY_OTC":
                        rule = RULE_BY_CAT["MEDICINE"]
                    else:
                        rule = RULE_BY_CAT["HAZMAT"]
                else:  # ALLOW
                    if cat_csv == "SERVICE":
                        rule = RULE_BY_CAT["SERVICE"]
                    elif cat_csv == "BEVERAGES_TEA_COFFEE":
                        rule = RULE_BY_CAT["BEVERAGE"]
                    elif cat_csv == "PERSONAL_CARE":
                        rule = RULE_BY_CAT["PERSONAL_CARE"]
                    else:
                        rule = RULE_BY_CAT["FOOD"]

                norm_item = re.sub(r"[^a-z0-9]+", " ", item.lower()).strip()
                if norm_item:
                    _TAXONOMY_EXACT[norm_item] = (rule, root or item)
                # Register root only if genuine noun (not matching its brand name) and not already in RULES keywords
                if root and root != brand.lower() and not any(root in r.keywords for r in RULES):
                    _TAXONOMY_ROOTS[root] = (rule, root)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to load indian_grocery_taxonomy_seed.csv: %s", exc)

_init_taxonomy()

_BRAND_SORTED = sorted(_KNOWN_BRANDS, key=len, reverse=True)
_BRAND_PATTERN = re.compile(r"^(?:" + "|".join(re.escape(b) for b in _BRAND_SORTED if len(b) > 2) + r")\b", re.IGNORECASE) if _BRAND_SORTED else None

@dataclass(frozen=True)
class LineScreening:
    category: str
    category_label: str
    reason_code: str
    verdict: ScreeningVerdict
    matched_keyword: Optional[str]

def worst(verdicts: Iterable[ScreeningVerdict]) -> ScreeningVerdict:
    result = ScreeningVerdict.ALLOW
    for v in verdicts:
        if _SEVERITY[v] > _SEVERITY[result]:
            result = v
    return result

def classify_item(name: str) -> Tuple[CategoryRule, Optional[str]]:
    """
    3-tier item matcher:
    (a) Exact/normalized item match against expanded 3,120+ taxonomy.
    (b) Canonical root-noun extraction with weight/pack and brand stripping.
    (c) Track C / Unmapped fallback returning UNKNOWN -> REVIEW.
    When categories conflict the more severe verdict wins (ALERT > REVIEW > ALLOW);
    among equally severe ones the longest keyword wins.
    """
    name = name or ""
    norm = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()

    # Tier 1: exact / normalized match
    tier1_match = _TAXONOMY_EXACT.get(norm)
    if tier1_match and tier1_match[0].verdict == ScreeningVerdict.ALERT:
        return tier1_match

    # Tier 2: canonical root-noun extraction and keyword matching
    split = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", name)
    no_weights = _PACK_WEIGHT_RE.sub(" ", name.lower())
    no_brands = _BRAND_PATTERN.sub("", no_weights).strip(" -:,()") if _BRAND_PATTERN else no_weights

    candidates: List[Tuple[int, int, CategoryRule, str]] = []

    for rule, keyword, pattern in _COMPILED:
        if pattern.search(name) or pattern.search(split) or pattern.search(no_weights) or pattern.search(no_brands):
            candidates.append((_SEVERITY[rule.verdict], len(keyword), rule, keyword))

    for root, (rule, kw) in _TAXONOMY_ROOTS.items():
        root_pat = _pattern(root)
        if root_pat.search(no_brands) or root_pat.search(no_weights) or root_pat.search(name):
            candidates.append((_SEVERITY[rule.verdict], len(root), rule, kw))

    if candidates:
        # Prune sub-phrase matches only when a longer compound keyword matched of equal or higher severity
        # Never prune a higher-severity match (ALERT > REVIEW > ALLOW)
        pruned = [
            c for c in candidates
            if not any(
                c[3] != other[3]
                and c[3] in other[3]
                and other[0] >= c[0]
                for other in candidates
            )
        ]
        candidates = pruned or candidates
        best = max(candidates, key=lambda c: (c[0], c[1]))

        # Always evaluate ALERT/REVIEW rules before accepting a Tier-1 ALLOW match
        if tier1_match:
            if best[0] > _SEVERITY[tier1_match[0].verdict]:
                return best[2], best[3]
            return tier1_match

        return best[2], best[3]

    if tier1_match:
        return tier1_match

    # Tier 2b: Safe canonical food/grocery root fast-pass
    norm_tokens = set(norm.split())
    for safe_kw in (
        "paneer", "egg", "eggs", "eggoz", "milk", "curd", "dahi", "butter", "cheese", "bread",
        "atta", "rice", "dal", "oil", "ghee", "pizza", "burger", "biryani", "dosa", "momos",
        "chai", "coffee", "chips", "biscuit", "noodles", "chocolate", "juice", "fruit",
        "vegetable", "potato", "onion", "tomato",
    ):
        if safe_kw in norm_tokens or re.search(r"\b" + re.escape(safe_kw) + r"\b", norm):
            return RULE_BY_CAT["FOOD"], safe_kw

    # Tier 3: Unmapped fallback
    return UNKNOWN, None

def screen_line(name: str, ocr_confidence: Optional[float] = None, readable: bool = True) -> LineScreening:
    """Category -> reason code -> verdict from the table above. Deterministic."""
    rule, keyword = classify_item(name) if readable else (UNKNOWN, None)
    reason, verdict = rule.reason_code, rule.verdict
    low_confidence = ocr_confidence is not None and ocr_confidence < SCREENING_LINE_MIN_CONFIDENCE
    # An uncertain read is never allowed silently (context.md rule 5); restricted stays ALERT.
    if (not readable or low_confidence) and verdict == ScreeningVerdict.ALLOW:
        reason, verdict = UNREADABLE_REASON, ScreeningVerdict.REVIEW
    elif not readable:
        reason = UNREADABLE_REASON
    return LineScreening(rule.category, rule.label, reason, verdict, keyword)
