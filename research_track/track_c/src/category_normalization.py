"""
Track C: Category Taxonomy & Deterministic Normalization Module.

Manages the standardized campus screening category taxonomy and normalizes raw
category strings into typed ItemCategoryCode enums.

Invariants:
- Unrecognized, blank, or invalid category strings normalize strictly to ItemCategoryCode.UNKNOWN.
- UNKNOWN must NEVER silently become NORMAL.
- Category normalization is deterministic and separate from ML perception.
"""

from typing import Dict, List, Optional
from .types import CategoryDefinition, CategorySeverity, ItemCategoryCode, ScreeningOutcome


# Definitive registry of campus screening categories
STANDARD_CATEGORY_DEFINITIONS: Dict[ItemCategoryCode, CategoryDefinition] = {
    ItemCategoryCode.TOBACCO_NICOTINE: CategoryDefinition(
        code=ItemCategoryCode.TOBACCO_NICOTINE,
        display_name="Tobacco / Nicotine",
        description="Cigarettes, beedis, gutka, pan masala with tobacco, vapes, e-cigarettes, snus, hookah tobacco.",
        default_action=ScreeningOutcome.ALERT,
        severity=CategorySeverity.HIGH,
        active=True,
    ),
    ItemCategoryCode.ALCOHOL: CategoryDefinition(
        code=ItemCategoryCode.ALCOHOL,
        display_name="Alcoholic Beverage",
        description="Beer, whisky, rum, vodka, wine, desi daru, craft beer, and other alcoholic drinks.",
        default_action=ScreeningOutcome.ALERT,
        severity=CategorySeverity.HIGH,
        active=True,
    ),
    ItemCategoryCode.RX_SCHEDULED_DRUG: CategoryDefinition(
        code=ItemCategoryCode.RX_SCHEDULED_DRUG,
        display_name="Prescription / Scheduled Drug",
        description="Regulated pharmaceuticals, Schedule H/X medicines, codeine syrups, controlled painkillers, sleeping pills.",
        default_action=ScreeningOutcome.ALERT,
        severity=CategorySeverity.CRITICAL,
        active=True,
    ),
    ItemCategoryCode.OTC_MEDICINE: CategoryDefinition(
        code=ItemCategoryCode.OTC_MEDICINE,
        display_name="Over-the-Counter Medicine",
        description="Non-prescription remedies, antacids, paracetamol, cough lozenges, band-aids, topical pain balms.",
        default_action=ScreeningOutcome.ALLOW,
        severity=CategorySeverity.LOW,
        active=True,
    ),
    ItemCategoryCode.HAZARDOUS_CHEMICAL: CategoryDefinition(
        code=ItemCategoryCode.HAZARDOUS_CHEMICAL,
        display_name="Hazardous Chemical",
        description="Flammable solvents, drain acids, bleach, kerosene, insecticides, rat poison, industrial thinners.",
        default_action=ScreeningOutcome.REVIEW,
        severity=CategorySeverity.MEDIUM,
        active=True,
    ),
    ItemCategoryCode.SHARP_OBJECT: CategoryDefinition(
        code=ItemCategoryCode.SHARP_OBJECT,
        display_name="Sharp Object",
        description="Kitchen knives, box cutters, razor blades, scissors, hunting blades, craft scalpel sets.",
        default_action=ScreeningOutcome.REVIEW,
        severity=CategorySeverity.MEDIUM,
        active=True,
    ),
    ItemCategoryCode.NORMAL: CategoryDefinition(
        code=ItemCategoryCode.NORMAL,
        display_name="Normal Item",
        description="Standard groceries, stationery, snacks, dairy, fruits, electronics, toiletries, and non-sensitive supplies.",
        default_action=ScreeningOutcome.ALLOW,
        severity=CategorySeverity.NONE,
        active=True,
    ),
    ItemCategoryCode.UNKNOWN: CategoryDefinition(
        code=ItemCategoryCode.UNKNOWN,
        display_name="Unknown / Unrecognized",
        description="Unrecognized, ambiguous, insufficiently described, or truncated item descriptions requiring review.",
        default_action=ScreeningOutcome.REVIEW,
        severity=CategorySeverity.LOW,
        active=True,
    ),
}

# Deterministic alias mapping for model output synonyms
CATEGORY_SYNONYM_MAP: Dict[str, ItemCategoryCode] = {
    "TOBACCO": ItemCategoryCode.TOBACCO_NICOTINE,
    "NICOTINE": ItemCategoryCode.TOBACCO_NICOTINE,
    "CIGARETTE": ItemCategoryCode.TOBACCO_NICOTINE,
    "CIGARETTES": ItemCategoryCode.TOBACCO_NICOTINE,
    "VAPE": ItemCategoryCode.TOBACCO_NICOTINE,
    "VAPING": ItemCategoryCode.TOBACCO_NICOTINE,
    "GUTKA": ItemCategoryCode.TOBACCO_NICOTINE,
    "BEEDI": ItemCategoryCode.TOBACCO_NICOTINE,
    "BIDI": ItemCategoryCode.TOBACCO_NICOTINE,
    "ALCOHOLIC_BEVERAGE": ItemCategoryCode.ALCOHOL,
    "BEER": ItemCategoryCode.ALCOHOL,
    "LIQUOR": ItemCategoryCode.ALCOHOL,
    "WINE": ItemCategoryCode.ALCOHOL,
    "WHISKY": ItemCategoryCode.ALCOHOL,
    "PRESCRIPTION_DRUG": ItemCategoryCode.RX_SCHEDULED_DRUG,
    "SCHEDULED_DRUG": ItemCategoryCode.RX_SCHEDULED_DRUG,
    "RX_DRUG": ItemCategoryCode.RX_SCHEDULED_DRUG,
    "SCHEDULE_H": ItemCategoryCode.RX_SCHEDULED_DRUG,
    "CONTROLLED_SUBSTANCE": ItemCategoryCode.RX_SCHEDULED_DRUG,
    "OTC": ItemCategoryCode.OTC_MEDICINE,
    "OVER_THE_COUNTER": ItemCategoryCode.OTC_MEDICINE,
    "FIRST_AID": ItemCategoryCode.OTC_MEDICINE,
    "HAZARDOUS": ItemCategoryCode.HAZARDOUS_CHEMICAL,
    "CHEMICAL": ItemCategoryCode.HAZARDOUS_CHEMICAL,
    "FLAMMABLE": ItemCategoryCode.HAZARDOUS_CHEMICAL,
    "CORROSIVE": ItemCategoryCode.HAZARDOUS_CHEMICAL,
    "ACID": ItemCategoryCode.HAZARDOUS_CHEMICAL,
    "SHARP": ItemCategoryCode.SHARP_OBJECT,
    "KNIFE": ItemCategoryCode.SHARP_OBJECT,
    "BLADE": ItemCategoryCode.SHARP_OBJECT,
    "WEAPON": ItemCategoryCode.SHARP_OBJECT,
    "GROCERY": ItemCategoryCode.NORMAL,
    "HOUSEHOLD": ItemCategoryCode.NORMAL,
    "FOOD": ItemCategoryCode.NORMAL,
    "STATIONERY": ItemCategoryCode.NORMAL,
    "GENERAL": ItemCategoryCode.NORMAL,
    "UNIDENTIFIED": ItemCategoryCode.UNKNOWN,
    "UNCERTAIN": ItemCategoryCode.UNKNOWN,
    "AMBIGUOUS": ItemCategoryCode.UNKNOWN,
}


class CategoryNormalizer:
    """
    Deterministic normalizer that maps category tokens into ItemCategoryCode enums.
    """

    @classmethod
    def normalize(cls, raw_category: Optional[str]) -> ItemCategoryCode:
        """
        Normalizes a raw category string into an ItemCategoryCode enum.
        Guarantees that unknown, invalid, or null strings resolve to ItemCategoryCode.UNKNOWN.
        """
        if not raw_category or not str(raw_category).strip():
            return ItemCategoryCode.UNKNOWN

        clean = str(raw_category).strip().upper().replace(" ", "_").replace("-", "_")

        # 1. Direct enum match
        try:
            return ItemCategoryCode(clean)
        except ValueError:
            pass

        # 2. Synonym match
        if clean in CATEGORY_SYNONYM_MAP:
            return CATEGORY_SYNONYM_MAP[clean]

        # 3. Safe fallback: never silently guess NORMAL!
        return ItemCategoryCode.UNKNOWN

    @classmethod
    def get_definition(cls, code: ItemCategoryCode) -> CategoryDefinition:
        """Retrieves metadata definition for a category code."""
        return STANDARD_CATEGORY_DEFINITIONS.get(
            code,
            STANDARD_CATEGORY_DEFINITIONS[ItemCategoryCode.UNKNOWN]
        )

    @classmethod
    def list_all_definitions(cls) -> List[CategoryDefinition]:
        """Returns all recognized category definitions in order."""
        return list(STANDARD_CATEGORY_DEFINITIONS.values())
