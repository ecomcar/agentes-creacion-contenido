"""
Demostración de la fase 6: `python demo_ciclo.py`

El sistema deja de ser una cadena y se convierte en un ciclo. Muestra:

  1. El Auditor devolviendo cada problema al agente correcto.
  2. Lo que cuesta cada ruta de corrección.
  3. El tope de ciclos derivando a humano.
  4. El Analista escribiendo (o no) en la memoria creativa.
  5. La memoria alimentando la campaña siguiente.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.contracts import (
    ERROR_ROUTING,
    AuditDecision,
    AuditIssue,
    AuditResult,
    AuditScores,
    CampaignLearnings,
    Confidence,
    IssueCategory,
)
from app.orchestrator import (
    CorrectionLoop,
    ProjectState,
    RetryLimits,
    RetryPolicy,
    stages_touching_credits,
)
from app.services import CreativeMemory

LINE = "─" * 72


def scores(**over) -> AuditScores:
    base = dict(identity=92, anatomy=88, motion=85, physics=87, lip_sync=90,
                voice=86, product=95, continuity=89, ugc_realism=84,
                hook_visual=81, pacing=83, commercial_clarity=80)
    base.update(over)
    return AuditScores(**base)


def audit(clip_id, category=None, *, realism=88, ad=82, cycle=1,
          decision=AuditDecision.APPROVED, desc="", **over) -> AuditResult:
    issue = None
    if category is not None:
        issue = AuditIssue(category=category, description=desc,
                           route_to_agent=ERROR_ROUTING[category])
    return AuditResult(artifact="audit_result", created_by="agent_11",
                       clip_id=clip_id, cycle=cycle, scores=scores(**over),
                       realism_score=realism, ad_score=ad, decision=decision,
                       issue=issue)


# ══ 1 · Cada problema vuelve a su responsable ═══════════════════════════
print(f"{LINE}\n1 · Un anuncio de cuatro clips pasa por auditoría\n{LINE}")
loop = CorrectionLoop(RetryPolicy(RetryLimits(audit_cycles=3)))
state = ProjectState(project_code="UGC-0001")

casos = [
    ("C01", None, dict(realism=91, ad=85),
     "clip correcto"),
    ("C02", IssueCategory.MOTION, dict(realism=64, ad=79, motion=41),
     "la mano derecha hace un movimiento imposible"),
    ("C03", IssueCategory.IDENTITY, dict(realism=58, ad=80, identity=44),
     "el rostro cambia respecto al clip 2"),
    ("C04", IssueCategory.PACING, dict(realism=86, ad=61, pacing=48),
     "el corte llega tarde y el CTA se pisa"),
]

print(f"  {'clip':6} {'decisión':12} {'ruta':28} {'etapas':>7} créditos")
for clip, cat, over, desc in casos:
    decision = (AuditDecision.APPROVED if cat is None
                else AuditDecision.REGENERATE)
    out = loop.decide(state, audit(clip, cat, decision=decision, desc=desc,
                                   **over))
    if out.route:
        credito = "sí" if out.route.touches_billable else "no"
        print(f"  {clip:6} {out.decision:12} {out.route.as_path():28} "
              f"{out.route.regenerations:>7} {credito:>8}")
    else:
        print(f"  {clip:6} {out.decision:12} {'—':28} {'—':>7} {'—':>8}")

print("\n  Sin categoría, los cuatro habrían disparado la cadena larga.")


# ══ 2 · Lo que costó la calidad ═════════════════════════════════════════
print(f"\n{LINE}\n2 · El desperdicio queda medido, no escondido\n{LINE}")
print(f"  Reejecuciones de etapa por correcciones: {loop.wasted_regenerations()}")
print(f"  De ésas, con créditos de generación:     {loop.billable_corrections()}")
print("\n  Correcciones por categoría:")
for cat, n in loop.by_category().items():
    etapas = stages_touching_credits(
        next(o.route for o in loop.history
             if o.route and o.route.category is cat))
    print(f"    {cat.value:16} {n}×   etapas con crédito: "
          f"{', '.join(s.value for s in etapas) or 'ninguna'}")
print("\n  Este dato dice qué prompt mejorar: si la mitad de las correcciones")
print("  son de identidad, el trabajo está en el Agente 6, no en generar más.")


# ══ 3 · El tope de ciclos ═══════════════════════════════════════════════
print(f"\n{LINE}\n3 · Un clip que no mejora acaba en manos de un humano\n{LINE}")
loop2 = CorrectionLoop(RetryPolicy(RetryLimits(audit_cycles=3)))
state2 = ProjectState(project_code="UGC-0002")
for ciclo in (1, 2, 3, 4):
    out = loop2.decide(state2, audit("C03", IssueCategory.MOTION, cycle=ciclo,
                                     decision=AuditDecision.REGENERATE,
                                     realism=62, motion=44,
                                     desc="el gesto sigue siendo imposible"))
    marca = "🔄" if out.decision == "correct" else "🖐"
    print(f"  Ciclo {ciclo}: {marca} {out.decision:14} {out.message[:52]}")

print("\n  Y el Auditor tampoco puede aprobarse a sí mismo por debajo:")
out = loop2.decide(state2, audit("C05", decision=AuditDecision.APPROVED,
                                 realism=62, ad=70))
print(f"  🖐 {out.message}")


# ══ 4 · El Analista y la memoria ════════════════════════════════════════
print(f"\n{LINE}\n4 · Cerrar el ciclo: de las métricas al aprendizaje\n{LINE}")
memoria = CreativeMemory()


def learnings(confidence, projects, impressions, texto):
    return CampaignLearnings.model_validate({
        "artifact": "campaign_learnings", "created_by": "agent_12",
        "project_code": "UGC-0001",
        "metrics": {"impressions": 52_000, "ctr": 0.021, "hook_rate": 0.34,
                    "cpa": 4.10, "roas": 3.2, "spend_usd": 900.0},
        "insights": [{
            "text": texto, "confidence": confidence.value,
            "applies_to": ["hook_type"], "scope": "category",
            "scope_value": "eventos_infantiles",
            "evidence": {"project_codes": [f"UGC-{i:04d}"
                                           for i in range(1, projects + 1)],
                         "total_impressions": impressions,
                         "total_spend_usd": 900.0}}]})


print("  Campaña 1 — una sola campaña de evidencia:")
l1 = learnings(Confidence.MEDIA, 1, 8_000,
               "Parece que los hooks de confesión funcionan mejor")
escritas = memoria.write(l1)
print(f"    Insight de confianza media → escrito en memoria: {len(escritas)}")
print("    Un patrón visto una vez no puede gobernar las campañas siguientes.")

print("\n  Campaña 3 — evidencia acumulada:")
l3 = learnings(Confidence.ALTA, 3, 50_000,
               "Los hooks de confesión superan a los de problema en CTR "
               "con mujeres 25-34")
escritas = memoria.write(l3)
print(f"    Insight de confianza alta → escrito en memoria: {len(escritas)}")
print(f"    Evidencia: {escritas[0].evidence_impressions:,} impresiones "
      f"en {len(escritas[0].evidence_projects)} campañas")


# ══ 5 · La campaña siguiente no arranca de cero ═════════════════════════
print(f"\n{LINE}\n5 · Lo que recibe el Estratega en la campaña siguiente\n{LINE}")
lineas = memoria.as_prompt_lines(scope_value="eventos_infantiles")
for l in lineas:
    print(f"    · {l}")
print(f"\n  Para otra categoría: "
      f"{len(memoria.as_prompt_lines(scope_value='software_b2b'))} aprendizajes")
print("  La memoria es por marca o categoría; no se contagia entre sectores.")

futuro = datetime.now(timezone.utc) + timedelta(days=200)
print(f"\n  Dentro de 200 días: {len(memoria.query(now=futuro))} aprendizajes "
      f"activos")
print("  En publicidad digital, un insight de hace un año es arqueología.")

print(f"\n{LINE}")
print("  Crear → publicar → medir → aprender → crear mejor.")
print(f"{LINE}")
