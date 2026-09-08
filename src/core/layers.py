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


def apply_layer_filter(
    doc, keep_keywords: list[str], drop_keywords: list[str]
) -> tuple[list[str], list[str]]:
    """Zet lagen aan/uit op basis van keywoorden. Retourneert (kept, dropped) laagnamen."""
    ocgs = doc.get_ocgs()
    ui_names = {u["text"] for u in doc.layer_ui_configs()}
    names = [info["name"] for info in ocgs.values()]
    kept, dropped = [], []
    for name in names:
        if name not in ui_names:
            continue
        matches_keep = any(k.lower() in name.lower() for k in keep_keywords)
        matches_drop = any(k.lower() in name.lower() for k in drop_keywords)
        keep = matches_keep and not matches_drop
        doc.set_layer_ui_config(name, action=0 if keep else 2)
        (kept if keep else dropped).append(name)
    logger.info("Lagen AAN: %s", ", ".join(kept) if kept else "(geen)")
    logger.info("Lagen UIT: %d lagen", len(dropped))
    return kept, dropped
