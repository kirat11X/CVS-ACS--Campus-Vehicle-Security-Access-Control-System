import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from backend.app.config import SCREENING_LINE_MIN_CONFIDENCE
from backend.app.models.enums import ScreeningVerdict

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
    )),
    CategoryRule("HAZMAT", "Hazardous chemical", "HAZMAT_NEEDS_APPROVAL", ScreeningVerdict.REVIEW, (
        "cleaner", "toilet cleaner", "drain cleaner", "harpic", "lizol", "acid", "bleach", "phenyl", "phenyle",
        "kerosene", "lighter fluid", "thinner", "turpentine", "insecticide", "pesticide", "rat poison",
        "naphthalene", "petrol", "diesel", "butane", "methylated spirit", "hit spray", "mosquito spray",
    )),
    CategoryRule("MEDICINE", "Medicine", "MEDICINE_NEEDS_APPROVAL", ScreeningVerdict.REVIEW, (
        "medicine", "tablet", "tablets", "capsule", "capsules", "syrup", "cough syrup", "paracetamol",
        "crocin", "dolo", "ibuprofen", "antibiotic", "injection", "ointment", "codeine", "tramadol",
        "alprazolam", "diazepam", "sleeping pill", "sleeping pills",
    )),
    CategoryRule("FOOD", "Food", "FOOD_OK", ScreeningVerdict.ALLOW, (
        "noodles", "instant noodles", "maggi", "chips", "biscuit", "biscuits", "bread", "rice", "dal", "atta",
        "flour", "sugar", "salt", "milk", "butter", "cheese", "paneer", "egg", "eggs", "fruit", "fruits",
        "apple", "apples", "banana", "bananas", "chocolate", "chocolates", "snack", "snacks", "namkeen",
        "kurkure", "lays", "pizza", "burger", "sandwich", "biryani", "roti", "paratha", "curry", "meal",
        "thali", "momos", "cake", "cookies", "oats", "cereal", "cornflakes", "jam", "sauce", "ketchup",
        "pasta", "soup", "chicken", "mutton", "fish", "ice cream", "curd", "yogurt", "garlic bread",
        "fries", "wrap", "rolls", "dosa", "idli", "samosa", "sweets",
    )),
    CategoryRule("BEVERAGE", "Beverage", "BEVERAGE_OK", ScreeningVerdict.ALLOW, (
        "cola", "coke", "pepsi", "sprite", "fanta", "soda", "juice", "water", "mineral water", "tea",
        "coffee", "energy drink", "red bull", "lassi", "buttermilk", "soft drink", "shake", "milkshake",
        "lemonade",
    )),
    CategoryRule("STATIONERY", "Stationery", "STATIONERY_OK", ScreeningVerdict.ALLOW, (
        "notebook", "notebooks", "pen", "pens", "pencil", "pencils", "eraser", "register", "a4", "paper",
        "file", "folder", "marker", "markers", "highlighter", "stapler", "notepad", "diary", "geometry box",
        "glue", "sketch", "sticky notes",
    )),
    CategoryRule("PERSONAL_CARE", "Personal care", "PERSONAL_CARE_OK", ScreeningVerdict.ALLOW, (
        "soap", "shampoo", "conditioner", "toothpaste", "toothbrush", "deodorant", "lotion", "cream",
        "face wash", "handwash", "hand wash", "sanitizer", "tissue", "tissues", "napkin", "napkins",
        "sanitary pad", "sanitary pads", "comb", "moisturiser", "moisturizer", "sunscreen",
    )),
    CategoryRule("ELECTRONICS", "Electronics", "ELECTRONICS_OK", ScreeningVerdict.ALLOW, (
        "charger", "cable", "earphones", "headphones", "earbuds", "power bank", "mouse", "keyboard", "usb",
        "adapter", "pendrive", "pen drive", "bulb", "extension board", "laptop", "phone cover", "batteries",
    )),
)

UNKNOWN = CategoryRule("UNKNOWN", "Unknown", "UNKNOWN_CATEGORY", ScreeningVerdict.REVIEW, ())
UNREADABLE_REASON = "UNREADABLE_LINE"

# For a reader of the table: every reason code and the verdict it maps to.
REASON_VERDICTS: Dict[str, ScreeningVerdict] = {
    **{r.reason_code: r.verdict for r in RULES},
    UNKNOWN.reason_code: UNKNOWN.verdict,
    UNREADABLE_REASON: ScreeningVerdict.REVIEW,
}
CATEGORY_LABELS: Dict[str, str] = {**{r.category: r.label for r in RULES}, UNKNOWN.category: UNKNOWN.label}

_SEVERITY = {ScreeningVerdict.ALLOW: 0, ScreeningVerdict.REVIEW: 1, ScreeningVerdict.ALERT: 2}

def _pattern(keyword: str) -> re.Pattern:
    words = [re.escape(w) for w in re.split(r"[\s-]+", keyword)]
    return re.compile(r"(?<![a-z0-9])" + r"[\s-]*".join(words) + r"(?![a-z0-9])", re.IGNORECASE)

_COMPILED: List[Tuple[CategoryRule, str, re.Pattern]] = [(rule, kw, _pattern(kw)) for rule in RULES for kw in rule.keywords]

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
    Keyword match on the item name. When categories conflict the more severe verdict wins
    (a "chocolate cigarette" line is screened as tobacco); among equally severe ones the
    longest keyword wins ("ice cream" is food, not the personal-care "cream").
    """
    name = name or ""
    # OCR sometimes drops spaces ("NotebookA4ruled"): also try with word breaks restored at
    # lower->upper case and letter<->digit changes ("Notebook A 4 ruled").
    split = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", name)
    best: Optional[Tuple[int, int, CategoryRule, str]] = None
    for rule, keyword, pattern in _COMPILED:
        if pattern.search(name) or pattern.search(split):
            key = (_SEVERITY[rule.verdict], len(keyword))
            if best is None or key > best[:2]:
                best = (key[0], key[1], rule, keyword)
    if best is None:
        return UNKNOWN, None
    return best[2], best[3]

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
