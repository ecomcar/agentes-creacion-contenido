# Estado del proyecto — Sistema UGC de 12 agentes

**Última actualización:** 25/08/2026
**Repositorio:** https://github.com/ecomcar/agentes-creacion-contenido
**393 pruebas automáticas, todas en verde**

Este documento existe para poder continuar el trabajo en un chat nuevo sin
perder decisiones ya tomadas. Está escrito para que Claude lo lea al
arrancar una sesión nueva y tenga contexto completo sin tener que
redescubrir nada.

---

## Qué es esto

Sistema multi-agente para producir anuncios UGC (User Generated Content)
de principio a fin: investigación → estrategia → hooks → guion →
storyboard → identidad → imagen → video → voz → montaje → auditoría →
análisis de resultados. 12 agentes de IA, cada uno con un contrato
Pydantic estricto, orquestados con compuertas de calidad y regeneración
selectiva (si un clip falla, sólo se rehace ese clip, no el anuncio
entero).

Cliente real en uso: **Karol Salud y Cosmética** (venta de Seytu/Omnilife).
Cliente de prueba usado antes: Party Voom (decoración infantil).

---

## Stack técnico

- **Backend:** Python 3.14, FastAPI, SQLAlchemy + Alembic, Pydantic v2
- **Base de datos:** PostgreSQL vía Docker Compose (`docker-compose.yml`
  en la raíz) — usuario/clave `ugc`/`ugc`, base `ugc`, puerto 5432.
  Adminer en `localhost:8080` para inspeccionar visualmente.
- **Modelos de lenguaje:** Claude vía API de Anthropic directa (sin
  intermediarios)
- **Imagen:** fal.ai → Nano Banana Pro (`fal-ai/nano-banana-pro`,
  editor: `fal-ai/nano-banana-pro/edit`)
- **Video:** fal.ai → Kling v3 Standard
  (`fal-ai/kling-video/v3/standard/image-to-video`)
- **Voz:** fal.ai → ElevenLabs Multilingual v2
  (`fal-ai/elevenlabs/tts/multilingual-v2`)
- **Frontend:** HTML/CSS/JS vanilla, sin build step, servido por el mismo
  FastAPI en `/panel/` (`app/static/`)
- **Entorno de la persona:** Windows, PowerShell, VS Code, Python vía
  `py -3.14` (tiene dos instalaciones de Python; siempre usar `py -3.14`,
  nunca `python` a secas)

---

## Cómo arrancar el proyecto (para reproducir el entorno)

```powershell
cd "C:\Users\ecomc\Documents\AGENTES CREACION CONTENIDO\backend"
docker compose up -d
py -3.14 -m pytest tests/ -q      # confirmar que todo sigue verde
py -3.14 servidor.py              # levanta la API + panel en :8000
```

Panel visual: `http://localhost:8000/panel/`
Documentación técnica interactiva: `http://localhost:8000/docs`

`.env` tiene las claves reales (`ANTHROPIC_API_KEY`, `FAL_KEY`,
`DATABASE_URL`) — **nunca se sube a git**, está en `.gitignore`.
`.env.example` sí está en el repo, como plantilla.

---

## Qué está construido (por fases)

| Fase | Qué cubre |
|---|---|
| 1 | Los 12 contratos Pydantic (`app/contracts/`) |
| 2 | AI Gateway, Model Router, Cost Guard (`app/gateway/`) |
| 3 | Agentes 1-4 (texto) + orquestador + máquina de estados |
| 4 | Agentes 5-7 + servicio de generación de imagen |
| 5 | Agente 8 + cola de trabajos asíncrona + video |
| 6 | Agentes 9-12 + bucle de corrección + memoria creativa |
| — | Validación de prompts con modelo real (`validar_prompts.py`) |
| — | Persistencia: PostgreSQL, SQLAlchemy, Alembic, repositorios |
| — | Conexión real a fal.ai: imagen, video, voz (verificado con
    dinero real) |
| — | Biblioteca de voces curadas (`app/services/voice_library.py`) —
    8 voces en español latino, ver más abajo |
| — | `AudioGenerationService` (paralelo a Image/VideoGenerationService) |
| — | API HTTP con FastAPI (`app/api/`) — proyectos, clips, artefactos,
    assets, etapas 1-4 |
| — | Panel visual en `/panel/` (`app/static/`) — Proyectos, Pipeline,
    Panel del Agente, Marcas |
| — | Marcas con brief persistente + historial de campañas |

### Lo que NO está construido todavía

- **Storyboard/Imagen/Video/Voz por HTTP** — esto es lo que se estaba
  construyendo cuando se cortó el chat anterior (ver "Tarea en curso"
  abajo). Existe el servicio (`ImageGenerationService`,
  `VideoGenerationService`, `AudioGenerationService`) y funciona vía
  scripts de terminal (`demo_pipeline_multiclip.py`), pero no hay
  endpoints de API ni panel visual para ellos todavía.
- Agente 12 (Analista) por HTTP — no forma parte del pipeline
  secuencial, se dispara aparte cuando llegan métricas de campaña
- "Modo prueba" con modelos baratos/gratis — **decisión tomada, en
  pausa** (ver sección dedicada abajo)
- Reglas específicas por plataforma (Instagram/TikTok/etc.) — se discutió
  pero se decidió construir Marcas primero; sigue pendiente

---

## Tarea en curso ahora mismo

**Conectar Storyboard, Imagen, Video y Voz al panel HTTP.**

Contexto: hasta ahora, generar imagen/video/voz de un clip sólo se podía
hacer corriendo `demo_pipeline_multiclip.py` desde la terminal. La
persona quiere que esto también se pueda hacer desde el panel web
(`/panel/`), igual que ya funciona para investigación/estrategia/hooks/
guion.

Lo que hace falta:
1. Endpoints de API para: crear/ver storyboard, generar imagen de un
   clip (con selección de variante), generar video de un clip (con
   sondeo de progreso, porque es asíncrono), generar voz de un clip
2. Actualizar `app/static/app.js` para mostrar estas etapas en el panel
   (ahora mismo dicen "Próximamente")
3. Reutilizar `ImageGenerationService`, `VideoGenerationService`,
   `AudioGenerationService` que ya existen — no reinventarlos
4. El video es asíncrono (cola con `JobQueue`) — la API tiene que
   devolver el job_id al instante y el panel debe sondear el progreso,
   no bloquear el request HTTP esperando 1-3 minutos

**Proyecto real esperando esto:** `UGC-0002` (Karol, Brillo Labial
Diamante) ya tiene guion aprobado y está parado exactamente en
`storyboard`, esperando esta funcionalidad.

---

## Decisión en pausa: "Modo prueba" con modelos baratos/gratis

La persona pidió poder elegir, al crear una campaña, un "modo prueba"
que use modelos de lenguaje baratos o gratis para las etapas de texto
(dejando imagen/video/voz siempre con las APIs de pago, porque ahí no
hay alternativa gratuita real), más un botón por etapa para "regenerar
con mejor calidad" si algo sale flojo.

**Decisión tomada:** se hace como una sola pieza combinando dos cosas,
no por separado:
1. Un modelo barato ya integrado y verificado: **Claude Haiku** (no es
   gratis, pero es una fracción del costo de Sonnet)
2. **Gemini Flash/Flash-Lite** — la única opción realmente gratuita por
   API (con límite ~15 peticiones/minuto, ~1.000-1.500/día), a
   integrarse con el mismo rigor que se usó con fal.ai (verificar
   documentación real antes de escribir código, no asumir nada)

**Aclaración importante ya discutida:** los planes gratuitos de
Claude.ai/ChatGPT/Gemini en su versión de chat web **no tienen API** —
automatizarlos violaría los términos de servicio de esos productos y no
es algo que se vaya a construir. Sólo se integran modelos con API real.

**Estado:** la persona pidió esperar y hacer las dos cosas (Haiku +
Gemini) juntas más adelante, no ahora. No empezar esto sin que la
persona lo pida explícitamente.

---

## Decisiones y calibraciones importantes (para no repetir el trabajo)

Estas son cosas que se decidieron con **evidencia real**, no a ojo —
importante no revertirlas sin la misma evidencia:

- **`StrategistAgent` usa Sonnet, no Opus.** Se comparó con datos reales
  sobre dos productos (Party Voom, Karol): Sonnet produce ángulos igual
  de buenos por una fracción del costo (~$0.04 vs ~$0.25 por ejecución).
- **`HooksAgent` usa el prompt v2, no v1** (`app/prompts/agent_03/v2.md`
  es el default). v1 dejaba hooks demasiado largos para decirse en 3-4
  segundos; v2 agrega un procedimiento de recorte con ejemplo.
- **Umbral de calidad de Hooks: 75, no 80** (`Hooks.MIN_AVERAGE` en
  `app/contracts/hooks.py`). El valor original (80) se puso sin datos y
  bloqueaba campañas con trabajo genuinamente bueno — recalibrado con
  evidencia real del proyecto UGC-0002 (dos intentos reales, ver el
  comentario en el código para el cálculo completo).
- **Umbral de dispersión de puntuación de hooks: 10, no 15**
  (`app/services/diagnostics.py`) — mismo tipo de recalibración, para
  el script de validación standalone (no es una compuerta del sistema
  real, sólo un diagnóstico informativo).
- **`JobQueue.wait()` duerme 8 segundos entre sondeos por defecto**
  (`app/services/job_queue.py`). Bug real encontrado: sin esa espera,
  agotaba los 120 intentos en segundos y abandonaba videos que Kling
  seguía generando de verdad. Las pruebas pasan `poll_interval_s=0`
  explícitamente para no volverse lentas.
- **Nano Banana Pro necesita dos endpoints distintos** según si hay
  imágenes de referencia: sin referencia usa
  `fal-ai/nano-banana-pro`, con referencia usa
  `fal-ai/nano-banana-pro/edit`. Ver `app/gateway/providers/
  fal_provider.py`.
- **Kling: status y resultado se consultan con el namespace base**
  (`fal-ai/kling-video`), no con el path completo que se usó para
  enviar el trabajo. Usar el path completo da 405, no 404 — detalle
  real de la API de fal.ai encontrado con una llamada real.

---

## Biblioteca de voces (español latino, acento neutro)

8 voces curadas de ElevenLabs, en `app/services/voice_library.py`:

**Femeninas:** Daniela (`ajOR9IDAaubDK5qtLUqQ`), Valeria
(`22VndfJPBU7AZORAZZTT`), Sandra (`rEVYTKPqwSMhytFPayIb`), Kate
(`qWWAqFomnJ99VwQLREfT`)

**Masculinas:** Juan (`VvYiNBPylZtUh8Bf6u8l`), Brian
(`U9TSK9KHMlMU2qkeXlQP`), Luis (`xXmo2BFwhd1KUag3K5Qz`), JC
(`4XUsiqPDK4UACIM2BILe`)

Todas verificadas con generación real. Hay un chequeo automático
(`find_duplicate_ids`) que detectó y ayudó a corregir un error de
copiado real en estos IDs — dejarlo, es una red de seguridad barata.

---

## Proyectos reales en la base de datos ahora mismo

| Código | Marca | Producto | Etapa actual |
|---|---|---|---|
| `UGC-0002` | Karol Alvarez | Brillo Labial Diamante | **storyboard** (esperando la tarea en curso) |
| `UGC-0001` | karol salud y cosmetica | Brillo Labial Diamante | (verificar estado) |
| `PRUEBA-01` | Karol Salud y Cosmética | Seytu | (proyecto de prueba temprano) |
| `DEMO-MULTICLIP` | Karol Salud y Cosmética | Seytu | completo — demo de regeneración selectiva con 2 clips reales |

Marca registrada: **Karol Alvarez / Karol Salud y Cosmética** (hay
cierta inconsistencia en cómo quedó escrito el nombre entre proyectos —
no es urgente pero vale la pena unificarlo en algún momento).

---

## Convenciones de trabajo con esta persona (importante)

1. **Entrega de archivos:** cada vez que se entregan archivos nuevos o
   modificados, dar la ruta completa y el comando `Copy-Item`
   correspondiente, **uno por uno en bloques individuales de código**,
   nunca agrupados. Ejemplo:
   ```powershell
   Copy-Item "$env:USERPROFILE\Downloads\archivo.py" -Destination "ruta\archivo.py" -Force
   ```
2. **Cuando dos archivos entregados se llaman igual** (típicamente dos
   `__init__.py` de carpetas distintas), copiarlos con nombres
   temporales distintos antes de entregarlos, para que la persona no
   los confunda al descargarlos del navegador.
3. **Siempre recordar el flujo de git al final**, en bloques
   individuales:
   ```powershell
   git add .
   ```
   ```powershell
   git commit -m "mensaje descriptivo"
   ```
   ```powershell
   git push
   ```
4. **Nunca pedir que se corra algo que gaste dinero sin avisar el costo
   aproximado antes.** Esta persona ya tuvo una situación real donde
   un umbral mal calibrado bloqueó una etapa después de gastar dinero
   real — quedó sensibilizada con el tema, con razón. Preferir siempre
   diagnosticar primero con lo que ya está guardado en la base de datos
   (sin nuevas llamadas a proveedores) antes de sugerir un reintento
   pago.
5. **Verificar todo antes de entregar.** El patrón establecido en este
   proyecto es: escribir código → probarlo en seco con proveedores
   falsos (`FakeProvider`, `FakeImageProvider`, etc.) o pruebas
   automáticas → sólo entonces entregar. Varias veces se encontraron
   bugs reales así antes de que le costaran dinero a la persona.
6. **No dar por hecho la documentación de APIs externas.** Con fal.ai
   se cometieron y corrigieron varios errores por asumir en vez de
   verificar (el `model_id` de Kling, el endpoint de status vs.
   resultado, etc.). Siempre buscar la documentación real antes de
   escribir un proveedor nuevo.
7. La persona tiene conocimientos técnicos básicos (sabe usar VS Code y
   PowerShell, pero no programa) — explicaciones claras, sin asumir
   jerga que no se ha usado antes en la conversación.

---

## Scripts de utilidad disponibles (todos en la raíz de `backend/`)

- `servidor.py` — levanta la API + panel
- `validar_prompts.py` — corre agentes 1-4 con modelo real, mide calidad
- `demo_pipeline_multiclip.py` — pipeline completo con 2 clips reales
  (imagen+video+voz), reanudable, persiste en base de datos
- `probar_fal.py` / `probar_fal_video.py` / `probar_fal_voz.py` —
  verificación aislada de cada proveedor de fal.ai
- `probar_voces_lote.py` — prueba las 8 voces curadas de una vez
- `revisar_hooks_fallidos.py` — diagnóstico sin costo de por qué falló
  una etapa de hooks (lee la base, no llama a ningún proveedor)
- `revalidar_y_desbloquear.py` — revisa un artefacto bloqueado contra
  las reglas actuales y lo aprueba sin gastar si ya califica

---

## Estructura de carpetas (resumen)

```
backend/
├── app/
│   ├── contracts/       12 contratos Pydantic
│   ├── gateway/          AI Gateway, Router, proveedores (Anthropic, fal.ai)
│   ├── agents/            Los 12 agentes
│   ├── orchestrator/    Máquina de estados, enrutamiento de correcciones
│   ├── services/          Image/Video/Audio GenerationService, voice_library,
│   │                    creative_memory, diagnostics
│   ├── db/                 Modelos SQLAlchemy, repositorios
│   ├── api/                FastAPI: main.py, deps.py, schemas.py, routers/
│   ├── static/             Panel visual (index.html, style.css, app.js)
│   └── prompts/            Prompts versionados en Markdown, uno por agente
├── alembic/                 Migraciones
├── tests/                     393 pruebas
├── docker-compose.yml
├── .env / .env.example
└── (scripts sueltos, ver arriba)
```
