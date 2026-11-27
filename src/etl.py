"""Limpieza del catálogo de Reental e integración de compraventas de Polygon."""

import argparse
import csv
import math
import re
from html import unescape
from pathlib import Path

import pandas as pd
import requests


RAIZ = Path(__file__).resolve().parents[1]
URL_WEB = "https://track-record.reental.co/"
CAMPOS = {
    "ID": "id_proyecto",
    "Nombre del proyecto": "nombre",
    "ESTADO": "estado",
    "Ubicación": "ubicacion",
    "Token Address": "contrato_token",
    "Link a inmueble en la web publica": "url_ficha",
    "LANZAMIENTO": "fecha_lanzamiento",
    "Fecha de Financiación": "fecha_financiacion",
    "Estimación fecha de fin desde Lanzamiento": "fecha_fin_prevista",
    "Real fecha de fin": "fecha_fin_real",
    "Nº de Tokens": "tokens_publicados",
    "Px Emisión Token": "precio_emision",
    "Divisa": "moneda",
    "Importe proyecto en €": "importe_eur",
    "Importe proyecto en $": "importe_usd_fuente",
    "Estimación Nº Meses desde Lanzamiento": "plazo_previsto_meses",
    "Estimación Rentab. Total (Alq. + Plusv.) anualizado Reentel": "rent_anual_prevista",
    "Real Rentab. Total Anualizada Reentel": "rent_anual_real",
}
NUMERICAS = ["tokens_publicados", "precio_emision", "importe_eur", "importe_usd_fuente", "plazo_previsto_meses"]
FECHAS = ["fecha_lanzamiento", "fecha_financiacion", "fecha_fin_prevista", "fecha_fin_real"]
RENTABILIDADES = ["rent_anual_prevista", "rent_anual_real"]
OBLIGATORIAS = ["id_proyecto", "nombre", "fecha_lanzamiento", "precio_emision", "moneda", "importe_proyecto"]


def descargar_csv(destino: Path) -> str:
    """Localiza el CSV en el track record y conserva una copia original."""
    respuesta_web = requests.get(URL_WEB, timeout=30)
    respuesta_web.raise_for_status()
    coincidencia = re.search(r"""const LIVE_CSV_URL\s*=\s*['"]([^'"]+)['"]""", respuesta_web.text)
    if coincidencia is None:
        raise ValueError("No encontramos el enlace de datos; hay que revisar la web.")
    url_csv = unescape(coincidencia.group(1))
    respuesta_csv = requests.get(url_csv, timeout=30)
    respuesta_csv.raise_for_status()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(respuesta_csv.content.decode("utf-8-sig"), encoding="utf-8")
    return url_csv


def leer_catalogo(ruta: Path) -> pd.DataFrame:
    """Busca la cabecera real y lee las filas que contienen un ID."""
    with ruta.open(encoding="utf-8-sig", newline="") as fichero:
        filas = list(csv.reader(fichero))
    cabecera = next((i for i, fila in enumerate(filas)
                     if fila[:3] == ["ID", "Nombre del proyecto", "ESTADO"]), None)
    if cabecera is None:
        raise ValueError("No se reconoce la cabecera del CSV.")
    columnas = [" ".join(nombre.split()) for nombre in filas[cabecera]]
    registros = []
    for fila in filas[cabecera + 1:]:
        if not fila or not fila[0].strip():
            continue
        if len(fila) > len(columnas):
            raise ValueError("Una fila tiene más campos que la cabecera; hay que revisarla.")
        registros.append(fila + [""] * (len(columnas) - len(fila)))
    if not registros:
        raise ValueError("El CSV no contiene proyectos.")
    return pd.DataFrame(registros, columns=columnas)


def convertir_numero(valor):
    if pd.isna(valor):
        return float("nan")
    texto = str(valor).replace("€", "").replace("$", "").replace(" ", "").replace("\u00a0", "")
    if not texto or texto.startswith(("#", "N/A")):
        return float("nan")
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        grupos = texto.split(",")
        texto = texto.replace(",", "") if all(len(g) == 3 for g in grupos[1:]) else texto.replace(",", ".")
    try:
        numero = float(texto)
        return numero if math.isfinite(numero) else float("nan")
    except ValueError:
        return float("nan")


def convertir_porcentaje(valor):
    if pd.isna(valor) or "%" not in str(valor):
        return float("nan")
    return convertir_numero(str(valor).replace("%", "")) / 100


def normalizar_catalogo(original: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Aplica los tipos del notebook y conserva los textos para revisar conversiones."""
    faltantes = set(CAMPOS) - set(original.columns)
    if faltantes:
        raise ValueError(f"Faltan columnas esperadas: {sorted(faltantes)}")
    proyectos = original[list(CAMPOS)].rename(columns=CAMPOS).copy()
    for columna in proyectos:
        proyectos[columna] = proyectos[columna].astype("string").str.strip().replace("", pd.NA)
    texto = proyectos.copy()
    proyectos["id_proyecto"] = proyectos["id_proyecto"].str.upper()
    proyectos["estado"] = proyectos["estado"].str.upper()
    proyectos["contrato_token"] = proyectos["contrato_token"].str.lower()
    for columna in NUMERICAS:
        proyectos[columna] = proyectos[columna].map(convertir_numero)
    for columna in FECHAS:
        proyectos[columna] = pd.to_datetime(proyectos[columna], format="%d/%m/%Y", errors="coerce")
    for columna in RENTABILIDADES:
        proyectos[columna] = proyectos[columna].map(convertir_porcentaje)
    proyectos["moneda"] = proyectos["moneda"].str.upper().replace({"€": "EUR", "$": "USD"})
    proyectos["importe_proyecto"] = proyectos["importe_eur"].where(
        proyectos["moneda"].eq("EUR"),
        proyectos["importe_usd_fuente"].where(proyectos["moneda"].eq("USD")),
    )
    return proyectos, texto


def revisar_catalogo(proyectos: pd.DataFrame, texto: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Genera las mismas cuatro tablas finales del notebook, sin eliminar proyectos."""
    convertidas = NUMERICAS + FECHAS + RENTABILIDADES
    fallos = texto[convertidas].notna() & proyectos[convertidas].isna()
    calidad = pd.DataFrame({
        "tipo": proyectos.dtypes.astype(str),
        "ausentes": proyectos.isna().sum(),
        "conversiones_no_validas": fallos.sum().reindex(proyectos.columns, fill_value=0),
    })
    calidad["porcentaje_ausentes"] = (100 * calidad["ausentes"] / len(proyectos)).round(1)
    validos = proyectos["contrato_token"].str.fullmatch(r"0x[0-9a-f]{40}", na=False)
    repetidos = proyectos["contrato_token"].notna() & proyectos["contrato_token"].duplicated(keep=False)
    contratos = proyectos.loc[
        validos & ~repetidos, ["id_proyecto", "nombre", "contrato_token", "moneda"]
    ].copy()
    cerrados = proyectos["estado"].eq("CERRADO").fillna(False)
    revisiones = pd.DataFrame({
        "id_duplicado": proyectos["id_proyecto"].duplicated(keep=False),
        "faltan_datos_basicos": proyectos[OBLIGATORIAS].isna().any(axis=1),
        "moneda_no_reconocida": proyectos["moneda"].notna() & ~proyectos["moneda"].isin(["EUR", "USD"]),
        "contrato_ausente_o_invalido": ~validos,
        "contrato_compartido": repetidos,
        "valor_no_positivo": proyectos[["precio_emision", "tokens_publicados", "importe_proyecto", "plazo_previsto_meses"]].le(0).any(axis=1),
        "cierre_anterior_al_lanzamiento": proyectos["fecha_fin_real"].lt(proyectos["fecha_lanzamiento"]),
        "cerrado_sin_resultado_o_fecha": cerrados & proyectos[["rent_anual_real", "fecha_fin_real"]].isna().any(axis=1),
        "resultado_en_proyecto_no_cerrado": ~cerrados & proyectos["rent_anual_real"].notna(),
        "conversion_no_valida": fallos.any(axis=1),
    }).fillna(False)
    incidencias = pd.concat([proyectos[["id_proyecto", "nombre"]], revisiones], axis=1)
    return {
        "proyectos_catalogo.csv": proyectos,
        "calidad_catalogo.csv": calidad.rename_axis("columna").reset_index(),
        "incidencias_catalogo.csv": incidencias.loc[revisiones.any(axis=1)].copy(),
        "contratos_polygon.csv": contratos,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Actualizar el CSV desde el track record público.")
    parser.add_argument("--input", type=Path, default=RAIZ / "data/raw/proyectos_reental.csv", help="CSV original.")
    parser.add_argument("--output", type=Path, default=RAIZ / "data/processed", help="Carpeta de resultados.")
    parser.add_argument("--polygon", action="store_true", help="Integrar también las compraventas verificadas.")
    parser.add_argument("--online", action="store_true", help="Permitir consultas RPC faltantes; requiere --polygon.")
    parser.add_argument("--target-sales", type=int, default=100, help="Objetivo de ventas verificadas, conservando las existentes.")
    parser.add_argument("--from-block", type=int, default=60_000_000, help="Límite inferior de búsqueda en Polygon.")
    parser.add_argument("--to-block", type=int, default=97_870_204, help="Bloque superior fijo para reproducir la captura.")
    parser.add_argument("--max-windows", type=int, default=200, help="Máximo de ventanas de 30.000 bloques por ejecución.")
    args = parser.parse_args()
    if args.online and not args.polygon:
        parser.error("--online requiere --polygon.")
    if args.download:
        print("Fichero público:", descargar_csv(args.input))
    if not args.input.is_file():
        parser.error("No existe el CSV. Usa --download o indica su ruta con --input.")
    original = leer_catalogo(args.input)
    proyectos, texto = normalizar_catalogo(original)
    archivos = revisar_catalogo(proyectos, texto)
    args.output.mkdir(parents=True, exist_ok=True)
    for nombre, tabla in archivos.items():
        tabla.to_csv(args.output / nombre, index=False, encoding="utf-8-sig", date_format="%Y-%m-%d")
    comparables = proyectos["estado"].eq("CERRADO") & proyectos[RENTABILIDADES].notna().all(axis=1)
    print("Proyectos conservados:", len(proyectos))
    print("Cerrados con previsión y resultado publicados:", int(comparables.sum()))
    print("Contratos con formato válido y sin duplicados:", len(archivos["contratos_polygon.csv"]))
    print("Proyectos con incidencias:", len(archivos["incidencias_catalogo.csv"]))
    print("Resultados guardados en:", args.output.resolve())
    for nombre, tabla in archivos.items():
        print(f"  {nombre}: {len(tabla)} filas")
    if args.polygon:
        from .polygon.etl import preparar_precios

        ventas = preparar_precios(args.output / "contratos_polygon.csv", args.output / "proyectos_catalogo.csv",
            args.output / "polygon/dataset_precios", RAIZ / "data/raw/polygon/rpc", online=args.online,
            objetivo=args.target_sales, desde=args.from_block, hasta=args.to_block, max_ventanas=args.max_windows)
        print("Compraventas verificadas:", len(ventas))
        print("Proyectos con ventas:", ventas["id_proyecto"].nunique())
        print("Dataset:", (args.output / "polygon/dataset_precios/ventas_verificadas.csv").resolve())


if __name__ == "__main__":
    main()
