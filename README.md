# Reental - DAVD Proyecto Final

Proyecto para analizar las previsiones y los resultados publicados de Reental, estudiar su mercado secundario en Polygon y evaluar modelos de predicción de rentabilidad.

Actualmente está implementada la obtención y limpieza del CSV. Polygon, ML, API, dashboard y Render se desarrollarán en los siguientes pasos. El código permanece local; no se ha publicado en GitHub.

## Estructura

```text
DAVD Proyecto Final/
├── src/
│   ├── etl.py             # Descarga, lectura, normalización y controles
│   ├── polygon/           # Reservado para operaciones y precios
│   ├── ml/                # Reservado para entrenamiento e inferencia
│   ├── api/               # Reservado para la API
│   └── dashboard/         # Reservado para la interfaz y los gráficos
├── data/
│   ├── raw/               # CSV original
│   └── processed/         # Proyectos limpios y revisiones
├── models/                # Reservado para modelos entrenados
├── assets/                # Reservado para estilos e imágenes
├── notebooks/             # Reservado para cuadernos del repositorio
├── docs/                  # Reservado para propuesta y presentación
├── tests/                 # Reservado para pruebas del proyecto
├── requirements.txt       # Dependencias del script
├── requirements-dev.txt   # Añade herramientas para notebooks
└── .gitignore
```

Las carpetas reservadas contienen únicamente `.gitkeep`. La estructura conserva `src/etl.py`, siguiendo la separación entre tratamiento de datos y aplicación del material de despliegue de la asignatura.

## Preparar el entorno

Desde la carpeta de la asignatura, en PowerShell:

```powershell
cd ".\DAVD Proyecto Final"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

El entorno local ya está creado. Para ejecutar únicamente el script basta instalar `requirements.txt`; las dependencias de desarrollo permiten trabajar también con el notebook.

## Ejecutar la limpieza

Con el CSV ya guardado:

```powershell
.\.venv\Scripts\python.exe -m src.etl
```

Para actualizar primero los datos públicos:

```powershell
.\.venv\Scripts\python.exe -m src.etl --download
```

Para indicar otro fichero o carpeta de salida:

```powershell
.\.venv\Scripts\python.exe -m src.etl --input "ruta\proyectos_reental.csv" --output "data\processed"
```

La descarga localiza el enlace CSV en `https://track-record.reental.co/`. El script no consulta fichas de inmuebles ni documentos PDF. Sin `--download` trabaja con el archivo local; si falta, indica cómo obtenerlo.

El flujo es: **descargar o leer CSV → localizar cabecera → seleccionar variables → convertir tipos → comprobar calidad y contratos → exportar**.

## Resultados

Se generan cuatro archivos en `data/processed/`:

- `proyectos_catalogo.csv`: todos los proyectos, con las 18 variables del paso 2 y el importe correspondiente a su moneda.
- `calidad_catalogo.csv`: tipos, ausentes y conversiones no válidas por columna.
- `incidencias_catalogo.csv`: proyectos señalados por los controles y el motivo.
- `contratos_polygon.csv`: contratos con formato válido y sin duplicados, preparados para su posterior consulta.

Las rentabilidades se guardan como fracciones: `0.12` representa `12 %`. Los ausentes permanecen ausentes y las incidencias se señalan sin eliminar proyectos. La variable `rent_anual_real` conserva el significado de rentabilidad anualizada real publicada por Reental; no es una TIR reconstruida a partir de flujos fechados.

Los datos originales, resultados, modelos y el entorno local quedan excluidos mediante `.gitignore`. Una futura copia del repositorio podrá obtener el CSV con `--download`.

## Relación con el notebook

El cuaderno didáctico se mantiene en `../DAF proyecto final V2/00_notebook_vacio.ipynb`. El script integra su descarga del CSV, las conversiones del paso 2 y la limpieza de todo el catálogo, evitando repetir el procesamiento de la muestra de cinco proyectos.

Se ha retirado la exploración de fichas. En el notebook quedan los pasos 1, 2 y 3: descarga, limpieza de la muestra y limpieza completa, respectivamente.

## Próximos pasos

1. Obtener una operación de Polygon vinculada a un contrato del CSV.
2. Ampliar el historial, clasificar operaciones y calcular precios cuando exista una contraprestación identificable.
3. Unir proyectos y operaciones; analizar precios, volumen y actividad.
4. Preparar el dataset de ML, comparar referencias, modelos de regresión y un posible ensamble; evaluar sin información futura.
5. Implementar backend, API y dashboard.
6. Preparar Render y completar documentación y presentación.

La primera variable objetivo de ML será `rent_anual_real`, utilizando información disponible antes del resultado. Las características de los proyectos procederán del CSV. Las variables de Polygon solo se incorporarán a las predicciones cuando sean anteriores a su fecha de corte.
