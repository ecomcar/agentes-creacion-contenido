# Qué falta para terminar el proyecto

Estado a 22/08/2026. 249 pruebas en verde, 112 archivos.

---

## Ahora mismo puedes ejecutar esto

```bash
cd backend
pip install -r requirements.txt
docker compose up -d                    # Postgres en :5432, Adminer en :8080
cp .env.example .env                    # y pegar ANTHROPIC_API_KEY
python -m alembic upgrade head          # crea las 14 tablas
python -m pytest tests/ -q              # 249 pruebas
python validar_prompts.py --ejemplo     # escribe producto.json
python validar_prompts.py --producto producto.json
```

Lo último es lo que importa: corre los agentes 1→4 con un modelo real y mide
si los prompts producen buen trabajo. Cuesta centavos y no genera imagen ni
video.

---

## Lo que está construido y probado

| Capa | Estado |
|---|---|
| 12 contratos Pydantic | completo |
| AI Gateway, Router, Cost Guard | completo |
| 12 agentes con prompts versionados | completo |
| Orquestador, máquina de estados, topes | completo |
| Bucle de corrección y enrutamiento de errores | completo |
| Memoria creativa | completo |
| Cola de trabajos asíncrona | completo (en memoria + tablas listas) |
| Persistencia: 14 tablas, repositorios, migración | completo |
| Diagnósticos de calidad de prompts | completo |

---

## Lo que falta, por orden de importancia

### 1. Los proveedores de generación son plantillas, no implementaciones

`HTTPImageProvider`, `HTTPVideoProvider` y `HTTPVoiceProvider` lanzan
`NotImplementedError` a propósito. Cada uno son ~50 líneas contra la API real,
pero **están bloqueados por decisiones que no puedo tomar**:

- ¿Nano Banana Pro directo, o a través de una plataforma de inferencia?
- ¿Kling directo, o vía la misma plataforma?
- ¿Qué proveedor de voz?

Los contratos de entrada y salida ya están fijados. Implementar cada uno es
rellenar un método `generate` o `submit`/`poll`; nada más del sistema cambia.

**Esto es lo único que impide producir un anuncio completo de punta a punta.**

### 2. Ningún precio de generación está verificado

Imagen, video y voz valen 0 en las tablas de precios, marcados
`verified=False`. Los topes de gasto dependen de esas cifras, así que hoy no
protegen nada en esas etapas.

Son tres modelos de coste distintos —por generación, por segundo, por
carácter— y hay que configurarlos en `.env` con las cifras reales de los
proveedores que elijas.

### 3. Validar los prompts con modelos reales

Las 249 pruebas usan proveedores falsos. Verifican que el sistema **funciona**,
no que los prompts produzcan **buen trabajo**. Ese fallo no lo detecta ningún
test.

`validar_prompts.py` mide ocho modos de fallo concretos. Córrelo con dos o
tres productos distintos antes de dar los prompts por buenos.

Hay una decisión concreta esperando datos: el Estratega pide `Quality.HIGH` y
el Router lo manda a Opus, que en las pruebas se lleva ~74% del coste de las
cuatro etapas de texto. `--forzar claude-sonnet-5` te dice si el modelo caro
se justifica.

### 4. API HTTP

FastAPI sobre lo que ya existe. Es mecánica: los repositorios y el orquestador
ya tienen la forma que necesita. Sin decisiones difíciles.

### 5. Almacenamiento de archivos

S3, Cloudflare R2 o Supabase Storage. Hoy las URLs de assets son cadenas; nada
sube archivos a ningún sitio.

### 6. Worker real

La cola es en memoria. Con Celery o ARQ sobre las tablas `jobs` que ya
existen, sobrevive a reinicios de verdad. Los repositorios ya están escritos.

### 7. Frontend

El dashboard de cinco zonas que diseñaste. Depende de la API. Es la parte más
vistosa y la de menor riesgo técnico.

---

## Decisiones que sólo puedes tomar tú

1. **Qué proveedores de imagen, video y voz.** Bloquea el punto 1.
2. **Presupuesto máximo por anuncio.** Los topes por defecto son
   conservadores; con los precios reales habrá que ajustarlos.
3. **Cuántas variantes por clip.** Multiplica directamente el coste.
4. **Modo automático o human-in-the-loop.** Arranca en manual; el sistema ya
   soporta ambos.

---

## Orden que recomiendo

**Primero validar prompts** (punto 3). Cuesta centavos y puede ahorrarte
rehacer trabajo caro después. Si el Estratega entrega ángulos flojos, eso se
arregla editando `app/prompts/agent_02/v1.md`, no construyendo más capas.

**Después un proveedor de imagen** (puntos 1 y 2). Con eso el pipeline llega
hasta imágenes reales y se puede juzgar si el Agente 7 ancla bien la
identidad.

**Luego video, API y frontend**, en ese orden.

---

## Nota sobre la verificación

Docker no estaba disponible donde se construyó esto, así que:

- Todo se verificó contra **SQLite**, no Postgres.
- La migración se generó con autogenerate contra SQLite; **los predicados de
  los índices parciales se corrigieron a mano** (`IS 1` → `IS true`), porque
  Postgres rechaza la sintaxis de SQLite.

Al levantar el compose por primera vez, `alembic upgrade head` es la prueba
real. Si algo falla ahí, será en esos índices.

Una cosa que sí encontró la verificación: la restricción única de artefactos
incluía `clip_id`, que es NULL en los artefactos de proyecto. SQL trata cada
NULL como distinto, así que tres `strategy v1` convivían sin protesta. Se
corrigió añadiendo `clip_key` no nulo. Ese bug habría aparecido en producción
como versiones duplicadas sin explicación.
