# Reental — mercado secundario inmobiliario

Proyecto para estudiar las compraventas de tokens inmobiliarios de Reental en Polygon y preparar un modelo que estime el precio ejecutado por token.

Está integrado el tratamiento de datos: descarga y limpieza del CSV, validación de compraventas, caché de respuestas RPC, reanudación y cruce de ventas con proyectos. La captura local contiene **131 proyectos, 130 contratos válidos y 100 ventas verificadas de 48 proyectos**. El modelo, la API, el dashboard y Render siguen pendientes.

## Estructura

```text
src/
├── etl.py                 # Punto de entrada y limpieza del CSV
├── polygon/
│   ├── __init__.py
│   └── etl.py             # Extracción y validación de compraventas
├── ml/                    # Reservado
├── api/                   # Reservado
└── dashboard/             # Reservado
data/
├── raw/
│   ├── proyectos_reental.csv
│   └── polygon/rpc/       # Respuestas originales por consulta y nodo
└── processed/
    ├── proyectos_catalogo.csv
    └── polygon/dataset_precios/
tests/
├── test_etl.py
└── fixtures/compraventa_control.json
```

El notebook didáctico permanece en la carpeta V2. El código integrado trabaja con los archivos de este proyecto.

## Entorno

Desde la carpeta de la asignatura, en PowerShell:

```powershell
cd ".\DAVD Proyecto Final"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

El entorno local ya existe. Para ejecutar únicamente el tratamiento de datos basta instalar `requirements.txt`; no se han añadido dependencias.

## Ejecutar

Solo el catálogo, usando el CSV local:

```powershell
.\.venv\Scripts\python.exe -m src.etl
```

Catálogo y compraventas, usando los datos y la caché locales:

```powershell
.\.venv\Scripts\python.exe -m src.etl --polygon
```

Este es el comando para reproducir la captura actual de 100 ventas. Si falta una respuesta RPC, muestra un error; para obtener consultas nuevas hay que añadir `--online`.

Para descargar el CSV público y permitir consultas RPC faltantes:

```powershell
.\.venv\Scripts\python.exe -m src.etl --download --polygon --online
```

La descarga localiza el enlace CSV en [el track record de Reental](https://track-record.reental.co/). No se consultan fichas de inmuebles ni documentos PDF.

Se mantienen `--input` y `--output` para indicar otro CSV o carpeta de resultados. La extracción admite `--target-sales`, `--from-block`, `--to-block` y `--max-windows`. Los valores predeterminados son 100 ventas, bloques 60.000.000–97.870.204 y hasta 200 ventanas de 30.000 bloques por ejecución. El límite superior es fijo para reproducir la captura; no representa automáticamente el bloque actual. Un objetivo mayor depende del volumen disponible y de los límites de búsqueda. Las ventas existentes se conservan.

## Procesamiento y resultados

El flujo es: **CSV público → selección y conversión de variables → controles de calidad → contratos → eventos de mercado → recibos, bloques y decimales → compraventas verificadas → cruce con proyectos**.

El catálogo conserva fechas, importes, tasas y valores ausentes. Las rentabilidades se expresan como fracciones: `0.12` representa `12 %`. Las incidencias se señalan sin eliminar proyectos. Se generan:

- `proyectos_catalogo.csv`: 131 proyectos y 19 columnas.
- `calidad_catalogo.csv`: tipos, ausentes y conversiones fallidas.
- `incidencias_catalogo.csv`: proyectos que requieren revisión.
- `contratos_polygon.csv`: 130 contratos con formato válido y sin duplicados.

Las salidas del mercado están en `data/processed/polygon/dataset_precios/`:

| Archivo | Contenido de la captura actual |
| --- | --- |
| `ventas_verificadas.csv` | 100 compraventas, 25 columnas; objetivo: precio por token. |
| `ventas_proyectos.csv` | Las mismas 100 ventas con el catálogo asociado, 42 columnas. |
| `revision_operaciones.csv` | 104 operaciones revisadas; cuatro quedan sin precio. |
| `candidatos.csv` | 106 eventos únicos: 104 revisados, un control separado y uno pendiente. |
| `cobertura.csv` | 52 ventanas consultadas; se conservan sus límites y errores. |
| `resumen_proyectos.csv` | Conteos y fechas de los 48 proyectos con ventas verificadas. |
| `estado_reanudacion.json` | Revisiones terminadas, versión de reglas y firma del catálogo. |
| `consultas_usadas.json` | Nombres de las respuestas utilizadas, relativos a `data/raw/polygon/rpc/`. |
| `alcance.json` | Cobertura, objetivo, conteos y límites del dataset. |

Los candidatos se deduplican por red, transacción e índice del evento. El precio exige un cruce de órdenes del mercado observado, dos transferencias recíprocas, un proyecto del catálogo, cantidades positivas y un pago coincidente con el cruce. Se consultan los decimales del bloque correspondiente. Los casos ambiguos quedan sin precio. El gas POL se conserva separado.

Las respuestas y el estado se escriben primero en archivos temporales. Las consultas completadas se reutilizan y se aplican pausas y hasta tres intentos a las nuevas solicitudes. Si cambia el catálogo o la versión de reglas, el estado requiere revisión antes de reutilizarse. Se usa Tenderly para eventos históricos y dRPC para recibos, bloques y decimales.

## Verificación

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Las pruebas comprueban una venta pública conocida, pagos incoherentes, recibos discordantes y la ausencia de consultas de red por defecto. Con la captura local también verifican la equivalencia de las 100 ventas y su cruce con proyectos. Esta última prueba se omite si no están los datos completos. El flujo integrado se ha ejecutado con HTTP bloqueado.

## Alcance y próximos pasos

La muestra cubre un mercado, un contrato de pago y compraventas simples. Las 52 ventanas representan 1.270.000 bloques distintos; el censo sigue siendo parcial. La venta de control de 112 USDT0/token se verifica aparte y no aumenta el dataset.

El precio se denomina en unidades del contrato USDT/USDT0 por token. USDT0 es su etiqueta actual; no se convierte a EUR. El cruce con el catálogo usa su captura actual: campos como el estado o los resultados de cierre no acreditan información conocida antes de cada venta y todavía no forman una matriz X para ML. El experimento anterior de rentabilidad publicada queda en el notebook como antecedente.

Queda ampliar y comprobar el volumen disponible hacia la meta de 5.000–10.000 ventas, preparar variables anteriores a cada operación y la separación temporal, entrenar y evaluar modelos, y construir API, dashboard y despliegue en Render.

Los datos completos, resultados, modelos y `.venv` quedan excluidos mediante `.gitignore`. La pequeña captura pública de control en `tests/fixtures/` permite comprobar las reglas sin descargar el histórico completo.
