"""Tests voor de laag-kiezer-bouwstenen: recommend_layers() (voorstel voor
de checkboxen in de UI) en apply_explicit_layer_selection() (daadwerkelijk
een expliciete, door de gebruiker gekozen laagset toepassen i.p.v. gokken
op keywoorden - elke tekenaar noemt lagen immers anders)."""

import fitz

from src.core.constants import DEFAULT_DROP_KEYWORDS, DEFAULT_KEEP_KEYWORDS
from src.core.layers import (
    apply_explicit_layer_selection,
    apply_layer_filter,
    list_layers,
    recommend_layers,
)
from src.core.pipeline import run_clean

from conftest import SIMPLE_FLOORPLAN_PDF


def _open():
    return fitz.open(str(SIMPLE_FLOORPLAN_PDF))


def test_list_layers_returns_all_three_fixture_layers():
    doc = _open()
    names = sorted(layer["name"] for layer in list_layers(doc))
    assert names == ["A-DOOR", "A-WALL", "AREA-FILL"]


def test_recommend_layers_matches_keep_keywords_and_excludes_drop_keywords():
    doc = _open()
    recommended = recommend_layers(doc, DEFAULT_KEEP_KEYWORDS, DEFAULT_DROP_KEYWORDS)
    # A-WALL/A-DOOR staan letterlijk in DEFAULT_KEEP_KEYWORDS; AREA-FILL matcht
    # geen enkel keep-keyword EN bevat "AREA" (een drop-keyword) - hoort dus
    # nooit aanbevolen te worden.
    assert recommended == {"A-WALL", "A-DOOR"}


def test_apply_explicit_layer_selection_only_keeps_the_chosen_layers():
    doc = _open()
    kept, dropped = apply_explicit_layer_selection(doc, ["AREA-FILL"])
    assert kept == ["AREA-FILL"]
    assert sorted(dropped) == ["A-DOOR", "A-WALL"]


def test_apply_layer_filter_still_works_via_recommend_layers():
    doc = _open()
    kept, dropped = apply_layer_filter(doc, DEFAULT_KEEP_KEYWORDS, DEFAULT_DROP_KEYWORDS)
    assert sorted(kept) == ["A-DOOR", "A-WALL"]
    assert dropped == ["AREA-FILL"]


def test_run_clean_with_selected_layers_uses_exact_choice_not_keywords():
    doc = _open()
    page = doc[0]
    # Kies bewust een set die van de keywoord-heuristiek afwijkt: alleen
    # AREA-FILL (dat normaal juist wordt UITgezet).
    result = run_clean(doc, page, scale=2.0, selected_layers=["AREA-FILL"])
    assert result.mode_a is True
    assert result.kept_layers == ["AREA-FILL"]
    assert sorted(result.dropped_layers) == ["A-DOOR", "A-WALL"]


def test_run_clean_without_selected_layers_keeps_old_keyword_behaviour():
    doc = _open()
    page = doc[0]
    result = run_clean(doc, page, scale=2.0)
    assert result.mode_a is True
    assert sorted(result.kept_layers) == ["A-DOOR", "A-WALL"]
