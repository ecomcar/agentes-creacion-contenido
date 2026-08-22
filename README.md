# Sistema UGC — los 12 agentes

- **Fase 1 · `app/contracts/`** — los 12 contratos Pydantic.
- **Fase 2 · `app/gateway/`** — AI Gateway, Model Router y Cost Guard.
- **Fase 3 · `app/agents/` + `app/orchestrator/` + `app/prompts/`** — los
  agentes 1-4 y la capa de control.
- **Fase 4 · `app/services/` + proveedor de imagen** — agentes 5-7, assets,
  variantes y biblioteca de avatares.
- **Fase 5 · cola de trabajos + proveedor de video** — agente 8, generación
  asíncrona, idempotencia y recuperación.
- **Fase 6 · bucle de corrección + memoria creativa** — agentes 9-12 y el
  cierre del ciclo.

225 pruebas, todas sin red ni API key. Sólo `pydantic` es obligatorio; el SDK
de `anthropic` hace falta únicamente para llamar al modelo de verdad.

```bash
pip install pydantic pytest
python -m pytest tests/ -q      # 225 pruebas
python demo_contracts.py        # las compuertas de los contratos
python demo_gateway.py          # routing, topes y reparación
python demo_pipeline.py         # el pipeline completo de la fase 3
python demo_imagen.py           # del guion a las imágenes base
python demo_video.py            # generación asíncrona de video
python demo_ciclo.py            # correcciones selectivas y memoria
```

## Antes de construir nada más: validar los prompts

Las 225 pruebas corren con proveedores falsos. Verifican que el sistema
**funciona**; no que los prompts produzcan **buen trabajo**. Un pipeline
impecable que genera ángulos flojos no sirve de nada, y ese fallo no lo
detecta ningún test.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
pip install anthropic

python validar_prompts.py --ejemplo          # escribe producto.json
python validar_prompts.py --producto producto.json
```

Corre los agentes 1→4 sobre un producto real —sólo texto, unos centavos— y
mide los modos de fallo que sólo aparecen con un modelo de verdad:

| Diagnóstico | Qué caza |
|---|---|
| ángulos distintos | tres versiones del mismo ángulo |
| mecanismo, no eslogan | "el mejor servicio" en vez de por qué funciona |
| puntuación con distancia real | todo entre 85 y 95, ranking inservible |
| tensión curiosidad/claridad | 95 en ambos, señal de que no está evaluando |
| suena a persona, no a marca | "descubre nuestro servicio integral" |
| hook usado literal | el guionista reescribe el hook elegido con datos |
| diálogo cabe en el tiempo | más de ~2,5 palabras por segundo |
| habla como persona | vocabulario de folleto en el guion |

Ninguno produce un error. Todos producen anuncios peores.

Para comparar modelos, correr dos veces y contrastar coste **y**
diagnósticos:

```bash
python validar_prompts.py --producto producto.json --forzar claude-sonnet-5
```

El Estratega pide `Quality.HIGH` y el Router lo manda a Opus, lo que en las
pruebas se lleva ~74% del coste de las cuatro etapas. Si Sonnet mantiene los
diagnósticos, el ahorro por campaña es considerable. Es exactamente el tipo de
decisión que no se puede tomar sin datos.

Los prompts están en `app/prompts/agent_NN/v1.md`. Crear `v2.md` y comparar
antes de dar por buena una versión: el sistema los lee en runtime y
`prompt_versions` puede medir cuál rinde mejor.

## La decisión central: dos niveles de validación

**Nivel 1 — Esquema.** Validators de Pydantic. Rechaza lo estructuralmente
imposible: un clip que termina antes de empezar, un score de 130/100, un
rechazo del Auditor sin responsable asignado. Si esto falla, se lanza
`ValidationError` y el artefacto no se guarda.

**Nivel 2 — Criterios de aprobación.** El método `approval_check()`. Evalúa
calidad editorial: ángulos poco distintos, imperfecciones insuficientes,
lenguaje de comercial en el prompt. Devuelve una lista de `ApprovalIssue` con
severidad `blocking` o `warning`. **No lanza excepción.**

Por qué separarlos: si un ángulo flojo tirara una excepción, perderíamos el
trabajo del agente. Queremos guardarlo como borrador, mostrarlo en el
dashboard con sus incumplimientos marcados, y que decida el Orquestador o el
humano.

```python
artefacto.approval_check()    # todos los incumplimientos
artefacto.blocking_issues()   # sólo los que impiden aprobar
artefacto.can_be_approved()   # bool
```

## Reglas que quedaron codificadas, no confiadas al prompt

| Regla | Dónde | Nivel |
|---|---|---|
| El Auditor no puede rechazar sin decir qué agente corrige | `audit_result.py` | Esquema |
| La ruta de corrección se deriva de la categoría del error, no la elige el agente | `ERROR_ROUTING` | Esquema |
| Los umbrales (80 realismo / 75 anuncio) mandan sobre el veredicto del agente | `audit_result.py` | Bloqueo |
| El prompt de imagen debe anclarse en el Character Bible, no redescribir al personaje | `image_prompt.py` | Bloqueo |
| Lenguaje de comercial prohibido en prompts ("perfect skin", "cinematic lighting", "8k") | `COMMERCIAL_TERMS` | Bloqueo |
| Mínimo 3 imperfecciones naturales en el avatar | `character_bible.py` | Bloqueo |
| Los clips del guion deben encadenarse sin huecos ni solapes | `ugc_script.py` | Esquema |
| El storyboard no puede inventar clips que no existen en el guion | `storyboard.py` | Bloqueo |
| Confianza alta en un aprendizaje exige ≥3 campañas y ≥10.000 impresiones | `campaign_learnings.py` | Esquema |
| Sólo insights de confianza alta llegan a `creative_memory` | `writable_to_memory()` | — |

## Detalle de calibración

`too_similar()` detecta ángulos que son el mismo con otras palabras. El umbral
está calibrado con medición, no a ojo: dos premisas casi idénticas dan **0.556**
de Jaccard, así que un umbral de 0.75 no las habría detectado. Quedó en 0.50.

Se reporta como **advertencia y no bloqueo**, porque la similitud léxica es un
indicio y no una prueba —dos ángulos pueden compartir vocabulario y ser
distintos de verdad— y porque el humano elige el ángulo justo en ese paso.

## Estructura

```
app/contracts/
├── base.py                  ArtifactBase, ApprovalIssue, enums, helpers
├── research_brief.py        Agente 1
├── strategy.py              Agente 2
├── hooks.py                 Agente 3
├── ugc_script.py            Agente 4
├── storyboard.py            Agente 5
├── character_bible.py       Agente 6
├── image_prompt.py          Agente 7
├── video_prompt.py          Agente 8
├── voice_direction.py       Agente 9
├── edit_plan.py             Agente 10
├── audit_result.py          Agente 11 + tabla ERROR_ROUTING
├── campaign_learnings.py    Agente 12
└── __init__.py              CONTRACT_REGISTRY, AGENT_OUTPUT, parse_artifact()
```

## Uso desde el Orquestador

```python
from app.contracts import parse_artifact, contract_for_agent, ArtifactType

# Validar la salida cruda de un agente
artefacto = parse_artifact(ArtifactType.STRATEGY, respuesta_del_modelo)

if not artefacto.can_be_approved():
    for issue in artefacto.blocking_issues():
        print(issue.code, issue.message)   # va al feedback del reintento

# Corregir = versión nueva, nunca UPDATE
v2 = artefacto.next_version(primary_pain="...")
```

`ArtifactBase.next_version()` implementa la inmutabilidad decidida en el
esquema de base de datos: nunca se sobrescribe el payload de una versión ya
guardada.

---

# Fase 2 — AI Gateway

## La decisión central: el gateway devuelve contratos, no texto

Un wrapper de API devuelve una cadena que alguien tiene que interpretar. Este
gateway devuelve un objeto `Strategy` validado, o lanza una excepción.

```python
estrategia = gateway.generate_artifact(
    contract=Strategy,
    spec=TaskSpec(task=TaskKind.REASONING, quality=Quality.HIGH),
    system=prompt_del_agente_2,
    user=brief.model_dump_json(),
    agent_number=2, agent_name="strategist",
    project_code="UGC-0001",
)
```

Eso habilita el **bucle de reparación**: si el modelo devuelve un JSON que
incumple el contrato, el gateway le devuelve los errores exactos de Pydantic
y le pide corregir. El agente y el orquestador no se enteran.

```
- campo 'angles': List should have at least 3 items after validation, not 2
```

Un "inténtalo otra vez" no le dice al modelo qué corregir; esto sí. Tope duro
de 2 reparaciones (3 llamadas máximo) para que un modelo terco no vacíe el
presupuesto.

## Orden de operaciones

```
Router elige modelo
    ↓
Cost Guard estima el PEOR caso y autoriza o corta   ← antes de gastar
    ↓
Proveedor ejecuta
    ↓
Se extrae el JSON (tolera vallas de markdown y preámbulos)
    ↓
Se valida contra el contrato
    ↓
¿inválido? → reparación dirigida (tope duro)
    ↓
Se registra el gasto REAL y se emite la traza
```

## Tres piezas

**`model_router.py`** — El agente declara `TaskSpec(task, quality, budget)` y
nunca un nombre de modelo. Las reglas son datos, no `if`s desperdigados: se
ven, se testean y se cambian en un sitio. Cuando salga un modelo mejor, se
edita la tabla y ningún agente se entera. Hay un test que verifica que
`generate_artifact` **no acepta** parámetro `model`, para que esto no se
degrade con el tiempo.

**`cost_guard.py`** — Comprueba antes de llamar, estimando el peor caso
(entrada real + `max_tokens` de salida completos). Tres niveles: por llamada,
por proyecto y por sesión. Un test verifica que cuando el tope corta, el
proveedor recibe **cero** llamadas.

**`pricing.py`** — Sólo `claude-sonnet-5` está marcado `verified=True` (2/10
por millón, la cifra con la que se presupuestó el proyecto anterior). Los
demás están `verified=False` y `unverified_models()` los lista. Un modelo sin
precio registrado reporta coste 0 **y lo dice en la nota**, en vez de inventar
una cifra plausible.

## Añadir Kling o Nano Banana en la fase 4-5

Implementar el protocolo `Provider` (un método `generate`) y registrar una
regla en el Router. No se toca ningún agente, contrato ni el orquestador.
Mientras tanto, `ModelRouter` falla con un mensaje explícito si alguien pide
`VIDEO_GENERATION`, en vez de devolver un modelo de texto silenciosamente.

## `FakeProvider`

No imita a un modelo: devuelve las respuestas que se le programan, en orden.
Permite probar el gateway completo —routing, topes, reparación, trazas— sin
red, sin clave y sin gasto. Es lo que hace que las 83 pruebas corran en medio
segundo.

---

# Fase 3 — Agentes 1-4 y orquestador

Con estos cuatro agentes el pipeline ya produce **guiones UGC trazables sin
gastar un dólar en imagen ni video**. Es donde conviene validar los prompts de
razonamiento, porque desde el Agente 7 cada iteración cuesta créditos.

## Los prompts viven en archivos, no en el código

`app/prompts/agent_NN/vN.md`, leídos en runtime. Editar un prompt no requiere
deploy, cada versión queda en git, y `prompt_versions` (ya en el schema) puede
medir después si V2 rinde mejor que V1.

Cada prompt nombra explícitamente el modo de fallo conocido de ese agente.
El del Estratega, por ejemplo, muestra el error de entregar tres veces el
mismo ángulo con otras palabras, con ejemplo incluido. Hay tests que
verifican que esas advertencias siguen en el texto.

## Reintento ≠ reparación

Son dos bucles distintos y conviene no confundirlos:

| | Reparación (gateway) | Reintento (orquestador) |
|---|---|---|
| Causa | JSON que no cumple el contrato | Artefacto válido que no supera los criterios, o rechazo humano |
| Qué se le devuelve | Errores de Pydantic | `approval_check()` + feedback humano |
| Tope | 2 | Por etapa (2 texto, 3 imagen/video) |
| Quién se entera | Nadie | El dashboard |

**El artefacto rechazado no se pierde.** Queda como borrador con sus
incumplimientos marcados. Perder el trabajo del agente por un campo flojo
sería tirar dinero ya gastado.

## Los topes de imagen y video se cuentan por clip

`RetryPolicy.retry_key(stage, clip_id)`. Contados por proyecto, un anuncio de
seis clips agotaría el tope en el segundo clip problemático y bloquearía los
cuatro que aún no se han intentado.

## Cadenas de corrección, no agentes sueltos

El Auditor identifica al responsable, pero corregir casi nunca es un solo
agente: rehacer la identidad obliga a regenerar imagen y después video. El
enrutador devuelve la **cadena mínima**:

```
motion       11 → 8 → 11                     1 etapa    consume créditos
pacing       11 → 10 → 11                    1 etapa    no consume
voice        11 → 9 → 10 → 11                2 etapas   consume
identity     11 → 6 → 7 → 8 → 11             3 etapas   consume
hook_visual  11 → 3 → 4 → 5 → 7 → 8 → 11     5 etapas   consume
```

`cheapest_first()` ordena por coste: cuando un clip falla en varios ejes,
arreglar primero lo barato a veces sube lo suficiente el realismo como para
que el resto deje de importar.

Hay un test que verifica que `ERROR_ROUTING` (contrato del Auditor) y
`CORRECTION_CHAINS` (orquestador) no diverjan: son dos tablas editables por
separado que deben coincidir en el responsable.

## La máquina de estados no deja saltar etapas

`StateMachine.advance()` sólo permite la sucesora legítima. Sin esto, un bug
en el enrutamiento puede mandar el proyecto a "video" sin pasar por
"storyboard", y el fallo aparece tres pasos después disfrazado de otra cosa.

Las compuertas humanas están donde una decisión equivocada se paga cara:
elegir ángulo, elegir hook, aprobar guion y storyboard, seleccionar imagen y
video. `auto_mode=True` las desactiva cuando ya se sepa qué decisiones
producen buenos anuncios.

---

# Fase 4 — Agentes 5-7 y generación de imagen

## Aquí cambia la naturaleza del coste

Hasta la fase 3 todo se pagaba por token. A partir de aquí se paga **por
generación**, y eso tiene dos consecuencias que atraviesan el diseño:

1. El Cost Guard no puede estimar con `max_tokens`. El servicio de imagen
   comprueba `n_variantes × precio_por_imagen` antes de generar, con topes
   por clip y por proyecto.
2. **Un fallo cuesta lo mismo que un acierto.** Por eso las compuertas del
   Agente 7 rechazan el prompt antes de llegar al proveedor, no después.

Un prompt que redescribe al personaje o que contiene `cinematic lighting`
lanza `GenerationBlocked` y el generador recibe cero llamadas.

## Generar no es tarea de un agente

El Agente 7 produce un `ImagePrompt` —un objeto Pydantic— y
`ImageGenerationService` lo ejecuta. Mantener esa separación es lo que permite
testear los agentes sin proveedores y cambiar de proveedor sin tocar agentes.
Añadir Nano Banana real es implementar el protocolo `ImageProvider`: un método
`generate`. Nada más cambia.

## Un avatar sin referencias no está listo

`AvatarLibrary.is_ready()` exige los cinco ángulos. Generar clips antes de
tenerlos produce exactamente la deriva de rostro que todo el diseño evita —y
que dispara la cadena de corrección más cara (identidad → imagen → video).

La biblioteca vive **fuera** del proyecto. Un avatar se construye una vez y se
reutiliza en decenas de campañas: ése es el activo real que acumula el
sistema.

## Una sola variante seleccionada por clip

`select()` deselecciona automáticamente las demás del mismo clip. Es el
equivalente en memoria del índice parcial único del esquema. Sin esa garantía,
el Editor termina ensamblando dos versiones distintas del mismo clip —un fallo
que aparece tarde y cuesta encontrar.

Regenerar nunca sobrescribe: crea versiones nuevas, igual que los artefactos.

## Precios de imagen: ninguno verificado

No tengo cifras confirmadas de ningún proveedor de imagen. Todas las entradas
de `IMAGE_PRICES` valen 0 y están marcadas `verified=False`.
`unverified_image_providers()` las lista, y hay un test que lo comprueba.

**Configurar `PRICE_IMAGE_*` en `.env` antes de presupuestar una campaña.**
Las cifras que muestra la demo son simuladas.

---

# Fase 5 — Agente 8 y generación de video

## Primera pieza asíncrona del sistema

Un clip de Kling tarda minutos. Eso rompe el patrón de todas las fases
anteriores. El protocolo del proveedor deja de ser `generate()` y pasa a ser
dos operaciones:

```
submit(request) → provider_job_id     (vuelve enseguida)
poll(job_id)    → VideoJobStatus      (se consulta hasta terminar)
```

La API HTTP responde al instante con el `job_id`; el frontend sondea.

## Tres problemas que sólo aparecen cuando algo deja de ser instantáneo

**Doble cobro.** El usuario pulsa "generar" dos veces. La clave de
idempotencia se deriva del contenido —proyecto, clip, prompt, imagen,
duración y **semilla**— así que dos envíos idénticos devuelven el mismo
trabajo y el proveedor recibe uno.

La semilla tuvo que añadirse tras encontrar el fallo con un test: sin ella,
pedir una segunda variante del mismo clip —el caso más normal cuando la
primera no convence— devolvía el trabajo anterior y no generaba nada.

**Trabajos huérfanos.** El proceso muere con un trabajo en vuelo; el proveedor
sigue ejecutándolo y cobrando. `provider_job_id` se guarda **antes que
cualquier otra cosa** tras el envío, y `reconcile()` recoge los resultados al
arrancar.

**Sondeo infinito.** Un trabajo que nunca termina pasa a `ABANDONED` tras el
tope, con un mensaje que advierte de revisarlo en el proveedor antes de
reintentar para no pagar dos veces.

`Job` tiene la forma de una tabla `jobs` que el esquema aún no incluye: es lo
que hay que añadir al migrar esta fase a Postgres.

## Compuertas nuevas

No se anima un clip cuya imagen **no está seleccionada por un humano**, ni con
la imagen de otro clip. Sin esto el sistema generaría video sobre una variante
que nadie eligió.

El coste de video va **por segundo**, no por generación: los topes estiman
`duración × precio_por_segundo`.

## Precios de video: ninguno verificado

Igual que en imagen. `unverified_video_providers()` los lista y valen 0 hasta
configurarse en `.env`. Los $0.05/s de la demo son inventados.

---

# Fase 6 — Agentes 9-12 y cierre del ciclo

Con estos cuatro el sistema deja de ser una cadena y se convierte en un ciclo.

## El bucle de corrección: regenerar sólo lo que falla

El enrutamiento del Auditor estaba especificado desde la fase 1 y probado
desde la fase 3, pero nadie lo ejecutaba. `CorrectionLoop` lo hace.

```
C02  motion    11 → 8 → 11              1 etapa    con créditos
C03  identity  11 → 6 → 7 → 8 → 11      3 etapas   con créditos
C04  pacing    11 → 10 → 11             1 etapa    sin créditos
```

Sin categoría, los tres habrían disparado la cadena larga. Ahí está el ahorro
de todo el diseño.

**`CorrectionLoop.decide()` no ejecuta agentes: devuelve la ruta.** Separar
decisión de ejecución permite enseñarle al humano qué va a pasar antes de que
pase, y evita que un Auditor mal calibrado dispare gasto por su cuenta.

## El desperdicio queda medido

`wasted_regenerations()`, `billable_corrections()` y `by_category()`. Es el
dato que dice qué prompt mejorar: si la mitad de las correcciones son de
identidad, el trabajo está en el Agente 6, no en generar más variantes.

## El Agente 12 está fuera del pipeline

No lo dispara una etapa sino la llegada de métricas, días o semanas después de
publicar. Modelarlo como etapa obligaría a que un proyecto quedara "en curso"
indefinidamente esperando datos que quizá no lleguen.

`OUT_OF_PIPELINE_AGENTS` lo declara. Lo encontró un test de invariantes al
subir la frontera de implementación, no una revisión manual.

## La memoria creativa: tres defensas contra convertir ruido en doctrina

Un aprendizaje sacado de una campaña, tratado como ley por los agentes de
estrategia, hace que el sistema repita un acierto casual durante meses.

1. El contrato del Agente 12 rechaza confianza alta sin 3 campañas y 10.000
   impresiones.
2. Sólo la confianza alta se escribe en memoria.
3. Los aprendizajes caducan a los 180 días y pueden desactivarse sin borrarse
   —el histórico explica decisiones pasadas.

Además, la consulta ordena por peso de evidencia: si dos aprendizajes se
contradicen, el agente ve primero el que se apoya en más datos. Y el filtro es
por marca o categoría, así que la memoria no se contagia entre sectores.

## Tres modelos de coste conviviendo

| Fase | Se paga por | Estimación previa |
|---|---|---|
| Texto | token | entrada real + `max_tokens` |
| Imagen | generación | `n_variantes × precio` |
| Video | segundo | `duración × precio/s` |
| Voz | carácter | `len(texto) × precio/1k` |

No hay fórmula común: cada tipo de proveedor necesita la suya. Ninguno de los
precios de imagen, video o voz viene verificado.

---

## Lo que NO está aquí

- Persistencia → `app/db/` (SQL especificado, más una tabla `jobs`)
- API HTTP → `app/api/`
- Frontend → el dashboard de 5 zonas ya diseñado
- Worker real (Celery o ARQ) → la cola es en memoria; las operaciones son las
  mismas sobre Postgres

Los agentes reciben un objeto Pydantic y devuelven otro. No hablan con la base
de datos ni conocen a ningún proveedor. Por eso todo se puede testear sin
levantar Postgres y sin gastar un dólar.
