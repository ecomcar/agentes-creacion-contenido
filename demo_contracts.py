"""
Demostración ejecutable de los contratos: `python demo_contracts.py`

Simula tres situaciones reales del pipeline sin llamar a ningún modelo:
  1. El Agente 7 entrega un prompt que redescribe al personaje.
  2. El Agente 11 aprueba un clip que no llega a los umbrales.
  3. El Agente 11 rechaza sin decir quién corrige.

Sirve para ver el comportamiento de las compuertas antes de conectar la API.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from app.contracts import (
    ArtifactType,
    AuditDecision,
    AuditIssue,
    AuditResult,
    AuditScores,
    ImagePrompt,
    IssueCategory,
    SceneTemplate,
    parse_artifact,
)

LINE = "─" * 68


def show(title: str, issues) -> None:
    print(f"\n{LINE}\n{title}\n{LINE}")
    if not issues:
        print("  Sin incumplimientos. Apto para aprobación.")
    for i in issues:
        mark = "✗" if i.severity.value == "blocking" else "!"
        print(f"  {mark} [{i.severity.value:8}] {i.code}")
        print(f"      {i.message}")


# 1 ─ Prompt de imagen que redescribe al personaje y suena a comercial
malo = ImagePrompt(
    artifact=ArtifactType.IMAGE_PROMPT, created_by="agent_07", clip_id="C01",
    avatar_id="AV-FEMALE-EC-001", template_code="NB_SELFIE_UGC",
    template_version=3, scene=SceneTemplate.SELFIE,
    prompt_text="Beautiful latina woman, 30 years old, perfect skin, "
                "cinematic lighting, holding the product, 8k",
    identity_reference_used=False,
    imperfections_included=[],
    negative_constraints=[],
)
show("1 · Agente 7 entrega un prompt que ignora el Character Bible",
     malo.approval_check())
print(f"\n  ¿Puede aprobarse?  {malo.can_be_approved()}")

# 2 ─ El Auditor se aprueba a sí mismo por debajo del umbral
optimista = AuditResult(
    artifact=ArtifactType.AUDIT_RESULT, created_by="agent_11", clip_id="C03",
    scores=AuditScores(identity=91, anatomy=70, motion=43, physics=65,
                       lip_sync=88, voice=80, product=95, continuity=86,
                       ugc_realism=58, hook_visual=72, pacing=75,
                       commercial_clarity=79),
    realism_score=64, ad_score=71, decision=AuditDecision.APPROVED,
)
show("2 · El Editor aprueba 64/71; los umbrales son 80/75",
     optimista.approval_check())
print(f"\n  ¿Puede aprobarse?  {optimista.can_be_approved()}")
print("  Las compuertas deterministas mandan sobre el juicio del agente.")

# 3 ─ Rechazo sin responsable: ni siquiera se puede construir
print(f"\n{LINE}\n3 · El Auditor rechaza sin decir quién corrige\n{LINE}")
try:
    AuditResult(
        artifact=ArtifactType.AUDIT_RESULT, created_by="agent_11", clip_id="C03",
        scores=optimista.scores, realism_score=64, ad_score=71,
        decision=AuditDecision.REGENERATE, issue=None,
    )
except ValidationError as e:
    print(f"  ✗ Rechazado por el esquema: {e.errors()[0]['msg'][:90]}...")

# 4 ─ Enrutamiento correcto: movimiento artificial va al Agente 8
bueno = AuditResult(
    artifact=ArtifactType.AUDIT_RESULT, created_by="agent_11", clip_id="C03",
    scores=optimista.scores, realism_score=64, ad_score=71,
    decision=AuditDecision.REGENERATE,
    issue=AuditIssue(category=IssueCategory.MOTION,
                     description="La mano derecha hace un movimiento imposible",
                     route_to_agent=8),
)
print(f"\n{LINE}\n4 · Rechazo bien formado\n{LINE}")
print(f"  Eje más débil: {bueno.scores.weakest()}")
print(f"  Ruta: 11 → {bueno.issue.route_to_agent} → 11")
print("  No se regenera la imagen, ni el guion, ni el storyboard.")

# 5 ─ Round-trip JSON: lo que se guarda en Postgres vuelve a validar
payload = json.loads(bueno.model_dump_json())
vuelto = parse_artifact(ArtifactType.AUDIT_RESULT, payload)
print(f"\n{LINE}\n5 · Round-trip JSON ↔ contrato\n{LINE}")
print(f"  Reconstruido correctamente: {vuelto.issue.category.value} → "
      f"agente {vuelto.issue.route_to_agent}")
