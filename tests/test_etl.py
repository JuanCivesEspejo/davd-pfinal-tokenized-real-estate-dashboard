import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.etl import leer_catalogo, normalizar_catalogo
from src.polygon.etl import ClientePolygon, MATCH, MERCADO, TRANSFER, preparar_precios, revisar_precio


RAIZ = Path(__file__).resolve().parents[1]
DATOS = RAIZ / "data"
ESTADO = DATOS / "processed/polygon/dataset_precios/estado_reanudacion.json"


class ValidacionPrecioTest(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((RAIZ / "tests/fixtures/compraventa_control.json").read_text(encoding="utf-8"))
        self.recibo = copy.deepcopy(self.fixture["recibo"])
        self.evento = copy.deepcopy(next(e for e in self.recibo["logs"]
            if e["address"].lower() == MERCADO and e["topics"] and e["topics"][0].lower() == MATCH))
        self.mapa = {self.fixture["contrato_token"]: self.fixture["id_proyecto"]}

    def consultar_decimales(self, metodo, parametros):
        self.assertEqual(metodo, "eth_call")
        return "0x" + format(self.fixture["decimales"][parametros[0]["to"].lower()], "064x")

    def test_venta_conocida_y_gas_fuera_del_precio(self):
        resultado = revisar_precio(self.evento, self.recibo, self.mapa, self.consultar_decimales)
        self.assertEqual(resultado["cantidad_token"], Decimal("3"))
        self.assertEqual(resultado["cantidad_pago"], Decimal("336"))
        self.assertEqual(resultado["precio_por_token"], Decimal("112"))

    def test_operaciones_ambiguas_no_reciben_precio(self):
        for caso in ["sin_pago", "importe_distinto", "otro_activo", "otro_participante", "doble_cruce", "cantidad_cero"]:
            with self.subTest(caso=caso):
                recibo = copy.deepcopy(self.recibo)
                evento = copy.deepcopy(self.evento)
                cruce = next(e for e in recibo["logs"] if e["address"].lower() == MERCADO
                             and e["topics"] and e["topics"][0].lower() == MATCH)
                movimientos = [e for e in recibo["logs"] if e["topics"] and e["topics"][0].lower() == TRANSFER]
                token = next(e for e in movimientos if e["address"].lower() in self.mapa)
                pago = next(e for e in movimientos if e is not token)
                if caso == "sin_pago":
                    recibo["logs"].remove(pago)
                elif caso == "importe_distinto":
                    evento["data"] = cruce["data"] = cruce["data"][:-64] + format(335_000_000, "064x")
                elif caso == "otro_activo":
                    pago["address"] = "0x" + "1" * 40
                elif caso == "otro_participante":
                    pago["topics"][2] = "0x" + "1" * 64
                elif caso == "doble_cruce":
                    recibo["logs"].append(copy.deepcopy(cruce))
                elif caso == "cantidad_cero":
                    token["data"] = "0x" + "0" * 64
                resultado = revisar_precio(evento, recibo, self.mapa, self.consultar_decimales)
                self.assertEqual(resultado["estado_revision"], "revision_manual")
                self.assertNotIn("precio_por_token", resultado)

    def test_recibo_de_otro_bloque_se_rechaza(self):
        self.recibo["blockHash"] = "0x" + "0" * 64
        with self.assertRaises(ValueError):
            revisar_precio(self.evento, self.recibo, self.mapa, self.consultar_decimales)

    def test_cache_ausente_no_inicia_red_por_defecto(self):
        with tempfile.TemporaryDirectory() as carpeta:
            cliente = ClientePolygon(Path(carpeta) / "rpc", Path(carpeta) / "indice.json")
            with patch("requests.Session.post", side_effect=AssertionError("HTTP inesperado")):
                with self.assertRaises(FileNotFoundError):
                    cliente.consultar("eth_chainId", [])


@unittest.skipUnless(ESTADO.exists(), "Requiere la captura local; los datos completos no se versionan.")
class IntegracionLocalTest(unittest.TestCase):
    def test_catalogo_y_cien_ventas_equivalentes_sin_red(self):
        original = leer_catalogo(DATOS / "raw/proyectos_reental.csv")
        catalogo, _ = normalizar_catalogo(original)
        self.assertEqual(len(catalogo), 131)
        anterior = pd.read_csv(DATOS / "processed/polygon/dataset_precios/ventas_verificadas.csv", dtype="string")
        with tempfile.TemporaryDirectory() as carpeta:
            salida = Path(carpeta)
            shutil.copyfile(ESTADO, salida / ESTADO.name)
            with patch("requests.Session.post", side_effect=AssertionError("HTTP inesperado")):
                with contextlib.redirect_stdout(io.StringIO()):
                    ventas = preparar_precios(DATOS / "processed/contratos_polygon.csv",
                        DATOS / "processed/proyectos_catalogo.csv", salida, DATOS / "raw/polygon/rpc")
            actual = pd.read_csv(salida / "ventas_verificadas.csv", dtype="string")
            pd.testing.assert_frame_equal(anterior, actual)
            self.assertEqual(ventas.shape, (100, 25))
            self.assertEqual(ventas["id_proyecto"].nunique(), 48)
            cruce = pd.read_csv(salida / "ventas_proyectos.csv")
            self.assertEqual(cruce.shape, (100, 42))
            self.assertTrue(cruce["nombre"].notna().all())


if __name__ == "__main__":
    unittest.main()
