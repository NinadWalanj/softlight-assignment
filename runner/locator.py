# runner/locator.py
import json
import re
from difflib import SequenceMatcher
from typing import Dict, List, Tuple, Optional

# -------- Normalization / synonyms (boundary-safe) --------
SYNONYMS = {
    "click": ["press", "tap", "select", "choose"],
    "open": ["navigate", "go to"],
    "create": ["new", "add", "+"],
    "delete": ["remove", "trash", "discard"],
    "settings": ["preferences", "options"],
    "name": ["title"],
    "project": ["projects"],  # fold plural
}

STOPWORDS = {
    "the",
    "a",
    "an",
    "to",
    "on",
    "in",
    "of",
    "for",
    "with",
    "and",
    "or",
    "by",
    "is",
    "be",
    "button",
    "option",
    "menu",
    "item",
    "page",
    "view",
    "prompt",
    "dialog",
    "modal",
}

QUOTED_RE = re.compile(r"'([^']{1,200})'|\"([^\"]{1,200})\"")


def _extract_quoted(s: str) -> List[str]:
    return [(m.group(1) or m.group(2)).strip() for m in QUOTED_RE.finditer(s or "")]


def _normalize_intent(intent: str) -> str:
    s = (intent or "").lower()
    for base, words in SYNONYMS.items():
        for w in words:
            s = re.sub(rf"\b{re.escape(w)}\b", base, s)
    return s


def _tokens(s: str) -> List[str]:
    return [
        t for t in re.findall(r"[a-z0-9+]+", (s or "").lower()) if t not in STOPWORDS
    ]


# -------- Similarity helpers --------
def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _fieldwise_fuzzy(intent_norm: str, fields: List[str]) -> float:
    best = 0.0
    for f in fields:
        if not f:
            continue
        r = _ratio(intent_norm, f.lower())
        if r > best:
            best = r
    return best


def _token_overlap(intent_tokens: List[str], el_tokens: List[str]) -> float:
    if not intent_tokens:
        return 0.0
    return len(set(intent_tokens) & set(el_tokens)) / max(1, len(set(intent_tokens)))


# -------- Dialog geometry helpers --------
def _find_dialog_bounds(
    perceived: List[Dict],
) -> Optional[Tuple[float, float, float, float]]:
    # pick the largest role=dialog (by area)
    best = None
    best_area = 0.0
    for el in perceived:
        if (el.get("role") or "").lower() == "dialog":
            x, y = float(el.get("x") or 0), float(el.get("y") or 0)
            w, h = float(el.get("width") or 0), float(el.get("height") or 0)
            area = max(0.0, w) * max(0.0, h)
            if area > best_area and w > 10 and h > 10:
                best_area = area
                best = (x, y, w, h)
    return best


def _inside(bounds: Tuple[float, float, float, float], el: Dict) -> bool:
    x, y, w, h = bounds
    ex, ey = float(el.get("x") or 0), float(el.get("y") or 0)
    ew, eh = float(el.get("width") or 0), float(el.get("height") or 0)
    return ex >= x and ey >= y and (ex + ew) <= (x + w) and (ey + eh) <= (y + h)


# -------- Scoring --------
def _score_element(
    intent_norm: str,
    intent_tokens: List[str],
    quoted: List[str],
    el: Dict,
    dialog_bounds: Optional[Tuple[float, float, float, float]],
) -> float:
    text = (el.get("text") or "").strip()
    aria = (el.get("aria_label") or "").strip()
    title = (el.get("title") or "").strip()
    tip = (el.get("tooltip") or "").strip()
    role = (el.get("role") or "").lower() if el.get("role") else ""
    tag = (el.get("tag") or "").lower() if el.get("tag") else ""

    # Skip elements that have no label-ish content at all
    if not any([text, aria, title, tip]):
        return -1.0

    fields = [text, aria, title, tip]
    fuzzy = _fieldwise_fuzzy(intent_norm, fields)

    el_tokens = _tokens(" ".join(fields))
    overlap = _token_overlap(intent_tokens, el_tokens)

    score = 0.55 * fuzzy + 0.35 * overlap

    # Role-aware boosts
    if any(k in intent_norm for k in ("click", "open", "create", "delete", "submit")):
        if role in ("button", "menuitem", "link"):
            score += 0.06
        if tag in ("button", "a"):
            score += 0.03
    if "fill" in intent_norm or "input" in intent_norm or "type" in intent_norm:
        if role in ("textbox", "combobox") or tag in ("input", "textarea"):
            score += 0.10

    # Dialog-aware adjustment
    if dialog_bounds:
        if _inside(dialog_bounds, el):
            score += 0.08  # prefer elements inside an open dialog
        else:
            score -= 0.04  # softly penalize outside

    # Quoted label super-boost (exact match on any field)
    if quoted:
        q = quoted[0].lower()
        if q and any(q == (f or "").strip().lower() for f in fields):
            score += 0.30

    # Penalize very long blobs (likely containers)
    long_text = len(text) > 120 or len(" ".join(fields)) > 160
    if long_text:
        score -= 0.05

    return score


# -------- Public API --------
def locate_element_for_intent(
    intent: str, perception_path: str, top_k: int = 3, verbose: bool = True
) -> Optional[Dict]:
    """
    Returns the best element dict from perception for the given intent.
    - intent: natural-language instruction for this step
    - perception_path: path to JSON saved by perception with element dicts
    """
    try:
        with open(perception_path, "r", encoding="utf-8") as f:
            perceived = json.load(f)
    except Exception as e:
        if verbose:
            print(f"Locator: failed to read perception at {perception_path}: {e}")
        return None

    intent_norm = _normalize_intent(intent)
    intent_tokens = _tokens(intent_norm)
    quoted = _extract_quoted(intent)

    dialog_bounds = _find_dialog_bounds(perceived)

    scored: List[Tuple[float, Dict]] = []
    for el in perceived:
        try:
            s = _score_element(intent_norm, intent_tokens, quoted, el, dialog_bounds)
            if s > -1.0:
                scored.append((s, el))
        except Exception:
            continue

    if not scored:
        if verbose:
            print("Locator: no candidates after scoring.")
        return None

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_el = scored[0]

    if verbose:
        print(f"Found match for intent: '{intent}' (score={best_score:.3f})")
        text_preview = (
            best_el.get("text")
            or best_el.get("aria_label")
            or best_el.get("title")
            or ""
        ).strip()
        print(f"→ Element text: {text_preview[:120]}")
        print(f"→ Role: {best_el.get('role')}, Tag: {best_el.get('tag')}")
        # Show top-K for debugging
        if len(scored) > 1 and top_k > 1:
            print("… Top alternatives:")
            for i, (s, el) in enumerate(scored[1:top_k], start=2):
                t = (
                    el.get("text") or el.get("aria_label") or el.get("title") or ""
                ).strip()
                print(
                    f"   {i}. {s:.3f} | {t[:100]}  [{el.get('role')}/{el.get('tag')}]"
                )

    return best_el


# For Recovery engine
def locate_top_candidates(intent: str, perception_path: str, k: int = 5) -> List[Dict]:
    """
    Return top-k element dicts (best-first) using the same scoring as locate_element_for_intent.
    """
    try:
        with open(perception_path, "r", encoding="utf-8") as f:
            perceived = json.load(f)
    except Exception:
        return []

    intent_norm = _normalize_intent(intent)
    intent_tokens = _tokens(intent_norm)
    quoted = _extract_quoted(intent)
    dialog_bounds = _find_dialog_bounds(perceived)

    scored = []
    for el in perceived:
        try:
            s = _score_element(intent_norm, intent_tokens, quoted, el, dialog_bounds)
            if s > -1.0:
                scored.append((s, el))
        except Exception:
            continue

    if not scored:
        return []
    scored.sort(key=lambda x: x[0], reverse=True)
    return [el for _, el in scored[: max(1, k)]]
