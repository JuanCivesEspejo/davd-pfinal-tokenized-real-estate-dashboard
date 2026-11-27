"""Extracción, validación y limpieza de compraventas de Polygon."""

import hashlib
import json
import time
from datetime import datetime, timezone
from decimal import Decimal, getcontext
from pathlib import Path

import pandas as pd
import requests


NODOS = {"eventos": "https://tenderly.rpc.polygon.community", "datos": "https://polygon.drpc.org"}
MERCADO = "0x77ff7fcf6b581be21c6a88c36883a788b9f2a99f"
MATCH = "0xc4109843e0b7d514e4c093114b863f8e7d8d9a458c372cd51bfe526b588006c9"
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
PAGO = "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"
CONTROL = "0x26459a10191df0b2d5acf05f40ad2f944772e53fc150c7ee146154f6cd0a59b7"
VERSION_REGLAS = "venta_simple_v1"
COLUMNAS = ["chain_id", "mercado", "transaccion", "indice_evento", "bloque", "hash_bloque",
    "fecha_utc", "comision_red_pol", "estado_revision", "motivo", "id_proyecto", "contrato_token",
    "contrato_pago", "activo_pago", "cantidad_token_bruta", "cantidad_pago_bruta", "decimales_token",
    "decimales_pago", "cantidad_token", "cantidad_pago", "precio_por_token", "comprador", "vendedor",
    "origen_datos", "version_reglas"]


def guardar_json(ruta, contenido):
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(contenido, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temporal.replace(ruta)


def exportar_csv(ruta, tabla):
    temporal = ruta.with_suffix(".csv.tmp")
    tabla.to_csv(temporal, index=False, encoding="utf-8-sig")
    temporal.replace(ruta)


class ClientePolygon:
    """Reutiliza las respuestas originales; la red requiere online=True."""

    def __init__(self, cache, indice, online=False):
        self.cache = Path(cache)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.indice = Path(indice)
        self.online = online
        self.consultas = json.loads(self.indice.read_text(encoding="utf-8")) if self.indice.exists() else {}
        self.sesion = requests.Session()
        self.sesion.headers["User-Agent"] = "DAVD academic research / secondary-market dataset"
        self.ultimo_envio = 0.0

    def consultar(self, metodo, parametros, nodo="datos"):
        url = NODOS[nodo]
        clave = hashlib.sha256(json.dumps([url, metodo, parametros], sort_keys=True).encode()).hexdigest()
        ruta = self.cache / f"{clave}.json"
        if ruta.exists():
            guardado = json.loads(ruta.read_text(encoding="utf-8"))
            if (guardado["chain_id"], guardado["metodo"], guardado["parametros"], guardado["rpc"]) != (137, metodo, parametros, url):
                raise ValueError("La caché no corresponde a la consulta.")
            self.consultas[clave] = ruta.name
            return guardado["resultado"]
        if not self.online:
            raise FileNotFoundError(f"Falta una respuesta local de {metodo}. Usa --online para obtenerla.")
        ultimo_error = None
        for intento in range(3):
            time.sleep(max(0, 0.35 - (time.monotonic() - self.ultimo_envio)))
            self.ultimo_envio = time.monotonic()
            try:
                respuesta = self.sesion.post(url, json={"jsonrpc": "2.0", "id": 10,
                    "method": metodo, "params": parametros}, timeout=30)
                documento = respuesta.json()
                if "error" in documento or documento.get("result") is None:
                    raise RuntimeError(f"HTTP {respuesta.status_code}: {documento.get('error', 'sin resultado')}")
                respuesta.raise_for_status()
                guardar_json(ruta, {"chain_id": 137, "metodo": metodo, "parametros": parametros, "rpc": url,
                    "capturado_utc": datetime.now(timezone.utc).isoformat(), "resultado": documento["result"]})
                self.consultas[clave] = ruta.name
                return documento["result"]
            except (requests.RequestException, RuntimeError, ValueError) as error:
                ultimo_error = str(error)
                if intento < 2:
                    time.sleep(2 ** intento)
        raise RuntimeError(f"{metodo}: {ultimo_error}")


def clave_evento(evento):
    return f"137:{evento['transactionHash'].lower()}:{int(evento['logIndex'], 16)}"


def firma_evento(evento):
    return (evento["address"].lower(), evento["transactionHash"].lower(), int(evento["logIndex"], 16),
            int(evento["blockNumber"], 16), evento["blockHash"].lower(),
            tuple(t.lower() for t in evento["topics"]), evento["data"].lower())


def revisar_precio(evento, recibo, mapa, consultar):
    """Devuelve precio solo cuando el cruce y las dos transferencias concuerdan."""
    if (recibo["transactionHash"].lower() != evento["transactionHash"].lower()
            or recibo["blockHash"].lower() != evento["blockHash"].lower()
            or int(recibo["blockNumber"], 16) != int(evento["blockNumber"], 16)):
        raise ValueError("El recibo no coincide con el evento.")
    revision = {"estado_revision": "revision_manual", "motivo": ""}

    def rechazar(motivo):
        return dict(revision, motivo=motivo)

    if int(recibo["status"], 16) != 1:
        return rechazar("Transacción fallida.")
    cruces = [x for x in recibo["logs"] if x["address"].lower() == MERCADO
              and x["topics"] and x["topics"][0].lower() == MATCH]
    movimientos = [x for x in recibo["logs"] if x["topics"] and x["topics"][0].lower() == TRANSFER]
    proyectos = [x for x in movimientos if x["address"].lower() in mapa]
    if (evento.get("removed") or (recibo.get("to") or "").lower() != MERCADO
            or len(cruces) != 1 or len(movimientos) != 2 or len(proyectos) != 1):
        return rechazar("Se requiere un cruce, dos movimientos y un proyecto del catálogo.")
    if cruces[0].get("removed") or firma_evento(cruces[0]) != firma_evento(evento):
        return rechazar("El cruce del recibo no coincide con el candidato.")
    if any(x.get("removed") or len(x["topics"]) != 3 or len(x["data"]) != 66 for x in movimientos):
        return rechazar("Movimiento retirado o formato ERC-20 no reconocido.")
    token = proyectos[0]
    pago = next(x for x in movimientos if x is not token)
    revision.update(id_proyecto=mapa[token["address"].lower()],
                    contrato_token=token["address"].lower(), contrato_pago=pago["address"].lower())
    origen = lambda x: "0x" + x["topics"][1][-40:].lower()
    destino = lambda x: "0x" + x["topics"][2][-40:].lower()
    participantes = {"0x" + t[-40:].lower() for t in evento["topics"][1:3]}
    if pago["address"].lower() != PAGO:
        return rechazar("Activo de pago fuera del piloto USDT/USDT0.")
    if (origen(token) != destino(pago) or destino(token) != origen(pago)
            or participantes != {origen(token), destino(token)}):
        return rechazar("El pago y los participantes no son recíprocos.")
    if origen(token) == destino(token) or "0x" + "0" * 40 in participantes:
        return rechazar("Automovimiento, emisión o quema.")
    bruto_token, bruto_pago = int(token["data"], 16), int(pago["data"], 16)
    if min(bruto_token, bruto_pago) <= 0 or int(evento["data"][-64:], 16) != bruto_pago:
        return rechazar("Cantidades no positivas o pago distinto al importe del cruce.")
    cantidades, decimales = [], []
    for movimiento in [token, pago]:
        respuesta = consultar("eth_call", [
            {"to": movimiento["address"], "data": "0x313ce567"}, recibo["blockNumber"]])
        if len(respuesta) != 66 or not 0 <= int(respuesta, 16) <= 255:
            raise ValueError("Respuesta de decimals() no válida.")
        decimales.append(int(respuesta, 16))
        cantidades.append(Decimal(int(movimiento["data"], 16)) / Decimal(10) ** decimales[-1])
    return dict(revision, estado_revision="compraventa_verificada",
        motivo="Cruce de órdenes, proyecto y pago recíproco concordantes.",
        activo_pago="USDT0", cantidad_token_bruta=str(bruto_token), cantidad_pago_bruta=str(bruto_pago),
        decimales_token=decimales[0], decimales_pago=decimales[1],
        cantidad_token=cantidades[0], cantidad_pago=cantidades[1],
        precio_por_token=cantidades[1] / cantidades[0], comprador=destino(token), vendedor=origen(token))


def preparar_precios(ruta_contratos, ruta_catalogo, salida, cache, *, online=False,
                     objetivo=100, desde=60_000_000, hasta=97_870_204, max_ventanas=200):
    """Integra el histórico, reanuda la extracción y cruza ventas con el CSV."""
    getcontext().prec = 78
    if objetivo < 1 or desde < 0 or hasta < desde or max_ventanas < 1:
        raise ValueError("Revisa el objetivo y los límites de búsqueda.")
    salida = Path(salida)
    salida.mkdir(parents=True, exist_ok=True)
    contratos = pd.read_csv(ruta_contratos, dtype="string")
    contratos["contrato_token"] = contratos["contrato_token"].str.lower()
    if (contratos["id_proyecto"].isna().any() or contratos["id_proyecto"].duplicated().any()
            or not contratos["contrato_token"].str.fullmatch(r"0x[0-9a-f]{40}", na=False).all()
            or not contratos["contrato_token"].is_unique):
        raise ValueError("Los contratos requieren ID único y dirección válida sin duplicados.")
    mapa = contratos.set_index("contrato_token")["id_proyecto"].to_dict()
    firma_catalogo = hashlib.sha256(Path(ruta_contratos).read_bytes()).hexdigest()
    cliente = ClientePolygon(cache, salida / "consultas_usadas.json", online)
    for nodo in NODOS:
        if int(cliente.consultar("eth_chainId", [], nodo), 16) != 137:
            raise ValueError("El nodo no corresponde a Polygon PoS.")
    candidatos, cobertura = {}, {}

    def registrar_pagina(eventos, inicio, fin):
        for evento in eventos:
            if (evento["address"].lower() != MERCADO or evento.get("removed")
                    or len(evento["topics"]) != 4 or evento["topics"][0].lower() != MATCH
                    or len(evento["data"]) != 194 or not inicio <= int(evento["blockNumber"], 16) <= fin):
                raise ValueError("Evento incompatible con el filtro.")
            clave = clave_evento(evento)
            if clave in candidatos and firma_evento(candidatos[clave]) != firma_evento(evento):
                raise ValueError("Dos respuestas discrepan sobre el mismo evento.")
            candidatos[clave] = evento
        cobertura[(inicio, fin)] = {"desde": inicio, "hasta": fin, "estado": "completa",
            "eventos_en_ventana": len(eventos), "mercado": MERCADO}

    for ruta in cliente.cache.glob("*.json"):
        registro = json.loads(ruta.read_text(encoding="utf-8"))
        if registro.get("metodo") != "eth_getLogs" or registro.get("rpc") != NODOS["eventos"]:
            continue
        filtro = registro["parametros"][0]
        if filtro.get("address", "").lower() != MERCADO or filtro.get("topics") != [MATCH]:
            continue
        if registro.get("chain_id") != 137:
            raise ValueError("Red incorrecta en la captura.")
        registrar_pagina(registro["resultado"], int(filtro["fromBlock"], 16), int(filtro["toBlock"], 16))
        cliente.consultas[ruta.stem] = ruta.name

    recibo_control = cliente.consultar("eth_getTransactionReceipt", [CONTROL])
    evento_control = next(e for e in recibo_control["logs"] if e["address"].lower() == MERCADO
                          and e["topics"] and e["topics"][0].lower() == MATCH)
    if revisar_precio(evento_control, recibo_control, mapa, cliente.consultar).get("precio_por_token") != Decimal("112"):
        raise ValueError("La comprobación de la venta conocida ha fallado.")

    estado_ruta = salida / "estado_reanudacion.json"
    revisiones = {}
    if estado_ruta.exists():
        estado = json.loads(estado_ruta.read_text(encoding="utf-8"))
        if estado["version_reglas"] != VERSION_REGLAS or estado["firma_catalogo"] != firma_catalogo:
            raise ValueError("El catálogo o las reglas han cambiado; revisa el estado antes de reutilizarlo.")
        revisiones = {fila["clave"]: fila["datos"] for fila in estado["revisiones"]}

    def numero_ventas():
        return sum(r["estado_revision"] == "compraventa_verificada" for r in revisiones.values())

    def guardar_estado():
        guardar_json(estado_ruta, {"version_reglas": VERSION_REGLAS, "firma_catalogo": firma_catalogo,
            "objetivo_ventas": objetivo, "revisiones": [{"clave": k, "datos": v} for k, v in revisiones.items()]})
        guardar_json(cliente.indice, cliente.consultas)

    def exportar_tablas():
        revisadas = pd.DataFrame(list(revisiones.values()), columns=COLUMNAS)
        for campo in ["chain_id", "indice_evento", "bloque", "decimales_token", "decimales_pago"]:
            revisadas[campo] = pd.to_numeric(revisadas[campo], errors="raise").astype("Int64")
        revisadas = revisadas.sort_values(["bloque", "indice_evento"]).reset_index(drop=True)
        ventas = revisadas.loc[revisadas["estado_revision"].eq("compraventa_verificada")].copy()
        inventario = pd.DataFrame([{"clave": k, "chain_id": 137, "mercado": MERCADO,
            "transaccion": e["transactionHash"].lower(), "indice_evento": int(e["logIndex"], 16),
            "bloque": int(e["blockNumber"], 16), "hash_bloque": e["blockHash"],
            "es_control": e["transactionHash"].lower() == CONTROL, "revisado": k in revisiones}
            for k, e in candidatos.items()], columns=["clave", "chain_id", "mercado", "transaccion",
                "indice_evento", "bloque", "hash_bloque", "es_control", "revisado"])
        ventanas = pd.DataFrame(list(cobertura.values()), columns=["desde", "hasta", "estado",
            "eventos_en_ventana", "mercado", "error"]).sort_values(["desde", "hasta"])
        for nombre, tabla in {"revision_operaciones.csv": revisadas, "ventas_verificadas.csv": ventas,
                              "candidatos.csv": inventario, "cobertura.csv": ventanas}.items():
            exportar_csv(salida / nombre, tabla)
        return ventas

    def procesar(evento):
        clave = clave_evento(evento)
        if clave in revisiones or evento["transactionHash"].lower() == CONTROL:
            return
        recibo = cliente.consultar("eth_getTransactionReceipt", [evento["transactionHash"]])
        resultado = revisar_precio(evento, recibo, mapa, cliente.consultar)
        bloque = cliente.consultar("eth_getBlockByHash", [evento["blockHash"], False])
        if (bloque["hash"].lower() != evento["blockHash"].lower()
                or int(bloque["number"], 16) != int(evento["blockNumber"], 16)):
            raise ValueError("El bloque no coincide con la operación.")
        revisiones[clave] = {"chain_id": 137, "mercado": MERCADO,
            "transaccion": evento["transactionHash"].lower(), "indice_evento": int(evento["logIndex"], 16),
            "bloque": int(evento["blockNumber"], 16), "hash_bloque": evento["blockHash"].lower(),
            "fecha_utc": datetime.fromtimestamp(int(bloque["timestamp"], 16), timezone.utc).isoformat(),
            "comision_red_pol": Decimal(int(recibo["gasUsed"], 16)) *
                Decimal(int(recibo["effectiveGasPrice"], 16)) / Decimal(10) ** 18,
            "origen_datos": "polygon_rpc", "version_reglas": VERSION_REGLAS, **resultado}
        guardar_estado()
        if numero_ventas() and numero_ventas() % 10 == 0:
            exportar_tablas()
            print(f"Ventas verificadas: {numero_ventas()}/{objetivo}", flush=True)

    for evento in sorted(candidatos.values(), key=lambda e: (int(e["blockNumber"], 16), int(e["logIndex"], 16))):
        if numero_ventas() >= objetivo:
            break
        procesar(evento)
    for n, fin in enumerate(range(hasta, desde - 1, -30_000)):
        if numero_ventas() >= objetivo or n >= max_ventanas:
            break
        inicio = max(desde, fin - 29_999)
        if (inicio, fin) not in cobertura:
            try:
                pagina = cliente.consultar("eth_getLogs", [{"address": MERCADO, "topics": [MATCH],
                    "fromBlock": hex(inicio), "toBlock": hex(fin)}], "eventos")
                registrar_pagina(pagina, inicio, fin)
            except (RuntimeError, ValueError, FileNotFoundError) as error:
                cobertura[(inicio, fin)] = {"desde": inicio, "hasta": fin, "estado": "error",
                    "eventos_en_ventana": None, "mercado": MERCADO, "error": str(error)}
                exportar_tablas()
                raise
        pendientes = [e for k, e in candidatos.items() if k not in revisiones
            and e["transactionHash"].lower() != CONTROL and inicio <= int(e["blockNumber"], 16) <= fin]
        pendientes.sort(key=lambda e: (int(e["blockNumber"], 16), int(e["logIndex"], 16)), reverse=True)
        for evento in pendientes:
            if numero_ventas() >= objetivo:
                break
            procesar(evento)
        exportar_tablas()
    ventas = exportar_tablas()
    if ventas.duplicated(["chain_id", "transaccion", "indice_evento"]).any() or ventas["transaccion"].eq(CONTROL).any():
        raise ValueError("Ventas duplicadas o control mezclado con el dataset.")
    for fila in ventas.to_dict("records"):
        cantidad = Decimal(str(fila["cantidad_token_bruta"])) / Decimal(10) ** int(fila["decimales_token"])
        pago = Decimal(str(fila["cantidad_pago_bruta"])) / Decimal(10) ** int(fila["decimales_pago"])
        if (cantidad <= 0 or pago <= 0 or cantidad != Decimal(str(fila["cantidad_token"]))
                or pago != Decimal(str(fila["cantidad_pago"]))
                or pago / cantidad != Decimal(str(fila["precio_por_token"]))
                or fila["contrato_pago"] != PAGO or mapa.get(fila["contrato_token"]) != fila["id_proyecto"]):
            raise ValueError("Proyecto, cantidades o precio incoherentes.")

    catalogo = pd.read_csv(ruta_catalogo, dtype={"id_proyecto": "string", "contrato_token": "string"})
    enriquecidas = ventas.merge(catalogo, on=["id_proyecto", "contrato_token"], how="left",
                                validate="many_to_one", indicator=True)
    if not enriquecidas["_merge"].eq("both").all():
        raise ValueError("Hay ventas sin correspondencia con el catálogo.")
    exportar_csv(salida / "ventas_proyectos.csv", enriquecidas.drop(columns="_merge"))
    resumen = ventas.groupby("id_proyecto").agg(ventas=("transaccion", "size"),
        primera_venta=("fecha_utc", "min"), ultima_venta=("fecha_utc", "max")).sort_values("ventas", ascending=False)
    exportar_csv(salida / "resumen_proyectos.csv", resumen.reset_index())
    intervalos = []
    for inicio, fin in sorted((r["desde"], r["hasta"]) for r in cobertura.values() if r["estado"] == "completa"):
        if intervalos and inicio <= intervalos[-1][1] + 1:
            intervalos[-1][1] = max(intervalos[-1][1], fin)
        else:
            intervalos.append([inicio, fin])
    guardar_json(salida / "alcance.json", {"chain_id": 137, "version_reglas": VERSION_REGLAS,
        "firma_catalogo": firma_catalogo, "mercados_consultados": [MERCADO], "nodos": NODOS,
        "objetivo_actual": objetivo, "ventas_verificadas": len(ventas), "objetivo_actual_alcanzado": len(ventas) >= objetivo,
        "proyectos_con_ventas": int(ventas["id_proyecto"].nunique()), "candidatos_unicos": len(candidatos),
        "candidatos_sin_revisar": sum(k not in revisiones and e["transactionHash"].lower() != CONTROL
                                     for k, e in candidatos.items()),
        "operaciones_revisadas": len(revisiones), "operaciones_revisadas_sin_precio": len(revisiones) - len(ventas),
        "control_excluido": CONTROL, "ventanas_completas": sum(r["estado"] == "completa" for r in cobertura.values()),
        "intervalos_unidos": intervalos, "bloques_unicos_consultados": sum(b - a + 1 for a, b in intervalos),
        "censo_completo": False, "meta_final": [5000, 10000], "viabilidad_meta_final_confirmada": False,
        "unidad_objetivo": "Unidades del contrato USDT/USDT0 por token del proyecto.",
        "limites": ["Un mercado y un activo de pago; solo ventas simples.",
            "Muestra limitada por ventanas y parada, sin muestreo aleatorio.",
            "USDT0 es la etiqueta actual del contrato; gas POL separado y sin conversión a EUR.",
            "ventas_proyectos.csv usa la captura actual del catálogo; no acredita datos históricos para ML."]})
    guardar_estado()
    return ventas
