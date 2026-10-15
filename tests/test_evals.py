from pathlib import Path

from jobhunt.evals import blind, load_cases, score

CASES = Path(__file__).resolve().parents[1] / "evals" / "auditor" / "cases.jsonl"


def test_los_casos_son_validos_y_el_juez_no_ve_etiquetas():
    cases = load_cases(CASES)
    assert {c["label"] for c in cases} == {"fiel", "exagera", "agrega"}
    assert len({c["id"] for c in cases}) == len(cases)
    assert all(set(b) == {"id", "sources", "cv_text"} for b in blind(cases))


def test_puntaje_binario_y_faltantes_cuentan_como_dejar_pasar():
    cases = [{"id": "a", "label": "fiel", "seeded": ""}, {"id": "b", "label": "exagera", "seeded": ""},
             {"id": "c", "label": "agrega", "seeded": ""}, {"id": "d", "label": "fiel", "seeded": ""}]
    s = score(cases, {"a": "fiel", "b": "agrega", "d": "exagera"})
    assert s.unfaithful_recall == 0.5      # b detectado (aunque mal clasificado), c sin respuesta
    assert s.false_alarm_rate == 0.5       # d
    assert s.missed == ["c"] and s.missing_predictions == ["c"]
    assert s.accuracy_3 == 0.25
