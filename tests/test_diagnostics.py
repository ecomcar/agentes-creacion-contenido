"""
Pruebas de los diagnósticos.

Cada diagnóstico existe para cazar un modo de fallo que no produce ningún
error. Estas pruebas verifican que efectivamente lo caza — y que no salta con
trabajo bueno, que es igual de importante: un diagnóstico que siempre falla
se ignora al tercer día.
"""

from __future__ import annotations

import pytest

from app.contracts import Hooks, ResearchBrief, Strategy, UGCScript
from app.services.diagnostics import (
    diagnose_brief,
    diagnose_hooks,
    diagnose_script,
    diagnose_strategy,
)

# ---------------------------------------------------------- fixtures

BRIEF = {
    "artifact": "research_brief", "created_by": "agent_01",
    "product": {"name": "Party Voom", "category": "eventos",
                "core_benefit": "La fiesta queda montada sin que organices nada"},
    "audience_signals": {"age_range": "25-40", "location": "Guayaquil",
                         "known_pain_points": ["falta de tiempo"]},
}

ANGULOS_BUENOS = [
    {"angle_id": "A01", "name": "Mamá sola",
     "premise": "La madre agotada que intenta organizarlo todo sin ayuda",
     "emotion": "alivio", "recommended_format": "ugc"},
    {"angle_id": "A02", "name": "Precio oculto",
     "premise": "Nadie cuenta cuánto cuesta realmente improvisar la decoración",
     "emotion": "sorpresa", "recommended_format": "ugc"},
    {"angle_id": "A03", "name": "Antes y después",
     "premise": "Transformación visible del salón en pocas horas",
     "emotion": "orgullo", "recommended_format": "reel"},
]

ANGULOS_DISFRAZADOS = [
    ANGULOS_BUENOS[0],
    {"angle_id": "A02", "name": "Mamá cansada",
     "premise": "La madre cansada que intenta organizarlo todo sin ayuda",
     "emotion": "alivio", "recommended_format": "ugc"},
    ANGULOS_BUENOS[2],
]


def _strategy(angles=None, mecanismo=None, objeciones=None) -> Strategy:
    return Strategy.model_validate({
        "artifact": "strategy", "created_by": "agent_02",
        "awareness_level": "problem_aware",
        "primary_pain": "Organizar la fiesta consume semanas",
        "primary_desire": "Que salga bonita sin esfuerzo",
        "objections": objeciones if objeciones is not None else ["precio", "confianza"],
        "unique_mechanism": mecanismo or ("Montaje en tres horas porque el "
                                          "equipo llega con todo prearmado"),
        "angles": angles or ANGULOS_BUENOS,
    })


def _hooks(scores_list=None, tipos=None, textos=None) -> Hooks:
    tipos = tipos or ["problema", "confesion", "curiosidad", "contrarian",
                      "testimonial", "demostracion", "visual", "problema"]
    defecto = [92, 88, 84, 80, 76, 72, 68, 62]
    scores_list = scores_list or defecto
    textos = textos or [f"Texto natural del hook número {i+1}" for i in range(8)]
    return Hooks.model_validate({
        "artifact": "hooks", "created_by": "agent_03", "angle_id": "A01",
        "hooks": [
            {"hook_id": f"H{i+1:02d}", "type": t, "text": txt,
             "scores": {k: s for k in ("curiosidad", "claridad",
                                       "pattern_interrupt", "relevancia",
                                       "ugc_fit", "visual_ease")}}
            for i, (t, s, txt) in enumerate(zip(tipos, scores_list, textos))
        ],
    })


def _script(dialogos=None, total=35.0, target=35.0) -> UGCScript:
    dialogos = dialogos or [
        "Casi cancelo el cumpleaños de mi hija por esto",
        "Llevaba semanas con listas y presupuestos",
        "Llegaron a las nueve y a las doce estaba todo",
        "Escríbeles antes de volverte loca",
    ]
    roles = ["hook", "problema", "demostracion", "cta"]
    step = total / len(roles)
    return UGCScript.model_validate({
        "artifact": "ugc_script", "created_by": "agent_04", "hook_id": "H01",
        "target_duration_sec": target, "total_duration_sec": total,
        "clips": [{"clip_id": f"C{i+1:02d}", "start": round(i*step, 2),
                   "end": round((i+1)*step, 2), "role": r, "dialogue": d}
                  for i, (r, d) in enumerate(zip(roles, dialogos))],
        "cta": "Escríbenos por WhatsApp",
    })


def _find(findings, check):
    return next(f for f in findings if f.check == check)


# ---------------------------------------------------- agente 1


def test_detecta_caracteristica_disfrazada_de_beneficio():
    brief = ResearchBrief.model_validate({
        **BRIEF, "product": {**BRIEF["product"],
                             "core_benefit": "Servicio de decoración integral"}})
    assert not _find(diagnose_brief(brief), "beneficio, no característica").passed


def test_un_beneficio_real_pasa():
    brief = ResearchBrief.model_validate(BRIEF)
    assert _find(diagnose_brief(brief), "beneficio, no característica").passed


# ---------------------------------------------------- agente 2


def test_detecta_tres_angulos_que_son_uno():
    """El modo de fallo característico del Estratega."""
    f = _find(diagnose_strategy(_strategy(ANGULOS_DISFRAZADOS)),
              "ángulos distintos")
    assert not f.passed
    assert "A01/A02" in f.detail


def test_angulos_de_verdad_distintos_pasan():
    assert _find(diagnose_strategy(_strategy()), "ángulos distintos").passed


def test_detecta_un_eslogan_en_lugar_de_mecanismo():
    f = _find(diagnose_strategy(_strategy(mecanismo="El mejor servicio")),
              "mecanismo, no eslogan")
    assert not f.passed


def test_un_mecanismo_con_causa_pasa():
    assert _find(diagnose_strategy(_strategy()), "mecanismo, no eslogan").passed


def test_detecta_falta_de_objeciones():
    f = _find(diagnose_strategy(_strategy(objeciones=["precio"])),
              "objeciones identificadas")
    assert not f.passed


# ---------------------------------------------------- agente 3


def test_detecta_puntuacion_aplanada():
    """
    Si todo puntúa entre 85 y 95, el ranking no ordena nada y la elección
    humana pierde su apoyo. No produce ningún error.
    """
    f = _find(diagnose_hooks(_hooks([92, 90, 89, 91, 88, 90, 87, 89])),
              "puntuación con distancia real")
    assert not f.passed
    assert "rango" in f.value


def test_una_puntuacion_con_rango_pasa():
    assert _find(diagnose_hooks(_hooks()),
                 "puntuación con distancia real").passed


def test_detecta_falta_de_variedad_de_tipos():
    f = _find(diagnose_hooks(_hooks(tipos=["problema"] * 8)),
              "variedad de tipos")
    assert not f.passed


def test_detecta_lenguaje_de_marca_en_los_hooks():
    textos = ["Descubre nuestro servicio integral de decoración"] + [
        f"Texto natural del hook {i}" for i in range(2, 9)]
    f = _find(diagnose_hooks(_hooks(textos=textos)),
              "suena a persona, no a marca")
    assert not f.passed and "H01" in f.detail


def test_detecta_que_no_se_refleja_la_tension_curiosidad_claridad():
    """Un hook muy intrigante suele ser menos claro; si el modelo le pone 95
    a ambos en todos, no está evaluando."""
    f = _find(diagnose_hooks(_hooks([95] * 8)),
              "tensión curiosidad/claridad reflejada")
    assert not f.passed


# ---------------------------------------------------- agente 4


def test_detecta_que_el_guionista_mejoro_el_hook():
    """
    El hook se eligió con puntuaciones. Reescribirlo descarta esa decisión
    sin avisar a nadie.
    """
    hooks = _hooks(textos=["Casi cancelo el cumpleaños de mi hija por esto"]
                   + [f"Otro hook {i}" for i in range(2, 9)])
    script = _script(dialogos=["Estuve a punto de cancelar la fiesta",
                               "Llevaba semanas con listas",
                               "Llegaron a las nueve",
                               "Escríbeles"])
    f = _find(diagnose_script(script, hooks, "H01"), "hook usado literal")
    assert not f.passed


def test_el_hook_literal_pasa():
    hooks = _hooks(textos=["Casi cancelo el cumpleaños de mi hija por esto"]
                   + [f"Otro hook {i}" for i in range(2, 9)])
    assert _find(diagnose_script(_script(), hooks, "H01"),
                 "hook usado literal").passed


def test_detecta_dialogo_que_no_cabe_en_el_tiempo():
    """~2,5 palabras por segundo. Más, y la voz sale acelerada."""
    largo = " ".join(["palabra"] * 60)      # 60 palabras en 8.75s
    script = _script(dialogos=[largo, "corto", "corto", "corto"])
    f = _find(diagnose_script(script, _hooks(), "H01"),
              "diálogo cabe en el tiempo")
    assert not f.passed and "C01" in f.detail


def test_detecta_vocabulario_de_folleto():
    script = _script(dialogos=["Casi cancelo el cumpleaños",
                               "Una solución integral para tu evento",
                               "Llegaron a las nueve", "Escríbeles"])
    f = _find(diagnose_script(script, _hooks(), "H01"), "habla como persona")
    assert not f.passed and "C02" in f.detail


def test_detecta_duracion_fuera_de_objetivo():
    f = _find(diagnose_script(_script(total=50.0, target=35.0), _hooks(), "H01"),
              "duración en objetivo")
    assert not f.passed


def test_un_guion_bueno_pasa_todos_los_diagnosticos():
    """Igual de importante: un diagnóstico que siempre falla se ignora."""
    hooks = _hooks(textos=["Casi cancelo el cumpleaños de mi hija por esto"]
                   + [f"Otro hook natural {i}" for i in range(2, 9)])
    assert all(f.passed for f in diagnose_script(_script(), hooks, "H01"))
