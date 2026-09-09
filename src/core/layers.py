"""Laag-detectie / laag-filtering (MODE A: PDF heeft nog CAD-lagen/OCG's)."""

import logging

logger = logging.getLogger(__name__)


def list_layers(doc) -> list[dict]:
    """Geef alle CAD-lagen (OCG's) in de PDF terug als [{"xref": int, "name": str}, ...]."""
    ocgs = doc.get_ocgs()
    if not ocgs:
        return []
    return [
        {"xref": xref, "name": info["name"]}
        for xref, info in sorted(ocgs.items(), key=lambda kv: kv[1]["name"])
    ]


def has_usable_layers(doc, keep_keywords: list[str]) -> bool:
    ocgs = doc.get_ocgs()
    if not ocgs:
        return False
    ui_names = {u["text"] for u in doc.layer_ui_configs()}
    if not ui_names:
        return False
    names = [info["name"] for info in ocgs.values()]
    return any(any(k.lower() in n.lower() for k in keep_keywords) for n in names)


def recommend_layers(doc, keep_keywords: list[str], drop_keywords: list[str]) -> set[str]:
    """Welke laagnamen zou de keywoord-heuristiek aanraden om te behouden?

    Losstaand van het daadwerkelijk aan/uitzetten (zie apply_explicit_layer_selection)
    zodat de webapp dit als VOORSTEL kan tonen in de laag-kiezer, zonder dat de
    gebruiker eerst zoekwoorden hoeft te begrijpen - elke tekenaar noemt lagen
    anders, dus een keywoord-lijst dekt nooit alles (zie bv. 'wanden'/'ramen'
    die niet matchten op de oorspronkelijke "MUUR"/"RAAM"-keywoorden).
    """
    ocgs = doc.get_ocgs()
    ui_names = {u["text"] for u in doc.layer_ui_configs()}
    names = [info["name"] for info in ocgs.values() if info["name"] in ui_names]
    recommended = set()
    for name in names:
        matches_keep = any(k.lower() in name.lower() for k in keep_keywords)
        matches_drop = any(k.lower() in name.lower() for k in drop_keywords)
        if matches_keep and not matches_drop:
            recommended.add(name)
    return recommended


def apply_explicit_layer_selection(
    doc, selected_layers: list[str]
) -> tuple[list[str], list[str]]:
    """Zet lagen aan/uit op basis van een EXPLICIETE lijst gekozen laagnamen
    (bv. rechtstreeks vanuit de laag-kiezer in de webapp) i.p.v. keywoorden.
    Retourneert (kept, dropped) laagnamen."""
    ocgs = doc.get_ocgs()
    ui_names = {u["text"] for u in doc.layer_ui_configs()}
    names = [info["name"] for info in ocgs.values()]
    selected = set(selected_layers)
    kept, dropped = [], []
    for name in names:
        if name not in ui_names:
            continue
        keep = name in selected
        doc.set_layer_ui_config(name, action=0 if keep else 2)
        (kept if keep else dropped).append(name)
    logger.info("Layers ON: %s", ", ".join(kept) if kept else "(none)")
    logger.info("Layers OFF: %d layers", len(dropped))
    return kept, dropped


def apply_layer_filter(
    doc, keep_keywords: list[str], drop_keywords: list[str]
) -> tuple[list[str], list[str]]:
    """Zet lagen aan/uit op basis van keywoorden. Retourneert (kept, dropped) laagnamen."""
    recommended = recommend_layers(doc, keep_keywords, drop_keywords)
    return apply_explicit_layer_selection(doc, sorted(recommended))
