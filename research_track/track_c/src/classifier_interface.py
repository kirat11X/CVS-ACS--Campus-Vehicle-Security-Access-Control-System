"""
Track C: Model-Independent Item Classifier Interface.

Defines the abstract interface for machine learning or heuristic item classifiers,
and provides a transparent, deterministic lexical baseline classifier for testing.

Invariants:
- The classifier ONLY proposes a category and optional confidence. It NEVER evaluates policy
  or emits final screening outcomes (ALLOW/REVIEW/ALERT).
- Missing confidence remains strictly None; never artificially imputed as 0.0 or 1.0.
- Unrecognized or ambiguous text resolves to ItemCategoryCode.UNKNOWN with is_uncertain=True.
"""

from abc import ABC, abstractmethod
import csv
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .category_normalization import CategoryNormalizer
from .types import AlternativeCategory, ClassificationInput, ClassificationOutput, ItemCategoryCode


class ItemClassifier(ABC):
    """
    Abstract Base Class for invoice line-item classifiers.
    Decoupled from the deterministic policy engine.
    """

    def __init__(self, name: str, version: str):
        self.name = name
        self.version = version

    @abstractmethod
    def classify(self, item: ClassificationInput) -> ClassificationOutput:
        """
        Proposes a category classification and confidence for a line item.
        """
        raise NotImplementedError


class LexicalMappingClassifier(ItemClassifier):
    """
    Transparent, deterministic rule-based classifier using substring and keyword matching
    derived from the synthetic item taxonomy seed.
    Does NOT pretend to be an ML model; confidence is None by default.
    """

    def __init__(
        self,
        keyword_map: Optional[Dict[str, ItemCategoryCode]] = None,
        default_confidence: Optional[float] = None,
    ):
        super().__init__(name="lexical_baseline_v1", version="1.0.0")
        self.keyword_map = keyword_map or {}
        self.default_confidence = default_confidence

    @classmethod
    def from_csv(cls, csv_path: str, default_confidence: Optional[float] = None) -> "LexicalMappingClassifier":
        """Factory constructor building keyword map from item taxonomy seed CSV."""
        keyword_map: Dict[str, ItemCategoryCode] = {}
        if os.path.exists(csv_path):
            with open(csv_path, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    text = (row.get("item_text") or "").strip().lower()
                    cat_str = (row.get("category") or "").strip()
                    if text and cat_str:
                        keyword_map[text] = CategoryNormalizer.normalize(cat_str)
        return cls(keyword_map=keyword_map, default_confidence=default_confidence)

    def classify(self, item: ClassificationInput) -> ClassificationOutput:
        """
        Classifies an item description using deterministic substring/keyword matching.
        """
        raw_text = (item.raw_item_description or "").strip().lower()

        if not raw_text:
            return ClassificationOutput(
                line_item_id=item.line_item_id,
                predicted_category=ItemCategoryCode.UNKNOWN,
                confidence=None,
                classifier_name=self.name,
                classifier_version=self.version,
                is_uncertain=True,
                alternative_categories=[],
                prediction_timestamp=None,
                explanation="Item description is blank or empty.",
            )

        # 1. Exact match in keyword taxonomy
        if raw_text in self.keyword_map:
            cat = self.keyword_map[raw_text]
            return ClassificationOutput(
                line_item_id=item.line_item_id,
                predicted_category=cat,
                confidence=self.default_confidence,
                classifier_name=self.name,
                classifier_version=self.version,
                is_uncertain=(cat == ItemCategoryCode.UNKNOWN),
                alternative_categories=[],
                prediction_timestamp=None,
                explanation=f"Exact taxonomy match for '{raw_text}'.",
            )

        # 2. Substring matching against known items
        for keyword, category in self.keyword_map.items():
            # Check whole word or significant substring (>3 chars)
            if len(keyword) >= 4 and keyword in raw_text:
                return ClassificationOutput(
                    line_item_id=item.line_item_id,
                    predicted_category=category,
                    confidence=self.default_confidence,
                    classifier_name=self.name,
                    classifier_version=self.version,
                    is_uncertain=(category == ItemCategoryCode.UNKNOWN),
                    alternative_categories=[],
                    prediction_timestamp=None,
                    explanation=f"Lexical substring match on keyword '{keyword}'.",
                )

        # 3. Transparent heuristic rules for common prefixes/tokens
        heuristic_rules: List[Tuple[List[str], ItemCategoryCode]] = [
            (["cigarette", "bidi", "beedi", "gutka", "zarda", "vape", "hookah", "hukka", "nicotex", "sutta", "gold flake", "marlboro"], ItemCategoryCode.TOBACCO_NICOTINE),
            (["beer", "whisky", "whiskey", "vodka", "rum", "daru", "wine", "alcohol", "old monk", "blenders pride", "royal stag"], ItemCategoryCode.ALCOHOL),
            (["codeine", "tramadol", "alprazolam", "diazepam", "sleeping pill", "steroid", "clonazepam", "cough syrup with codeine"], ItemCategoryCode.RX_SCHEDULED_DRUG),
            (["crocin", "dolo", "vicks", "strepsils", "burnol", "digene", "volini", "paracetamol", "aspirin", "band-aid", "bandage"], ItemCategoryCode.OTC_MEDICINE),
            (["acid", "bleach", "kerosene", "phenyl", "rat poison", "insecticide", "thinner", "harpic", "drain cleaner", "hit spray"], ItemCategoryCode.HAZARDOUS_CHEMICAL),
            (["knife", "blade", "scissor", "scissors", "cutter", "box cutter", "chaaku", "razor"], ItemCategoryCode.SHARP_OBJECT),
            (["chips", "biscuit", "bread", "milk", "butter", "cheese", "kurkure", "lays", "maggi", "noodles", "pen", "notebook", "water"], ItemCategoryCode.NORMAL),
        ]

        for tokens, cat in heuristic_rules:
            for token in tokens:
                if re.search(r"\b" + re.escape(token) + r"\b", raw_text, re.IGNORECASE):
                    return ClassificationOutput(
                        line_item_id=item.line_item_id,
                        predicted_category=cat,
                        confidence=self.default_confidence,
                        classifier_name=self.name,
                        classifier_version=self.version,
                        is_uncertain=False,
                        alternative_categories=[],
                        prediction_timestamp=None,
                        explanation=f"Deterministic token match on '{token}'.",
                    )

        # 4. Fallback: UNKNOWN (never guess NORMAL!)
        return ClassificationOutput(
            line_item_id=item.line_item_id,
            predicted_category=ItemCategoryCode.UNKNOWN,
            confidence=None,
            classifier_name=self.name,
            classifier_version=self.version,
            is_uncertain=True,
            alternative_categories=[],
            prediction_timestamp=None,
            explanation=f"No lexical match for '{raw_text}'. Category remains UNKNOWN.",
        )
