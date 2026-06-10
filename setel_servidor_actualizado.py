"""
SETEL Seguridad - Servidor Flask
Versión preparada para Railway (nube) y uso local.

LOCAL:  python setel_servidor_actualizado.py  → http://localhost:5000
NUBE:   Railway lo arranca automáticamente con el Procfile

URLs por técnico:
  http://localhost:5000/tecnico/Javi
  http://localhost:5000/tecnico/Mario
  ... etc.
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import requests, os, re

app = Flask(__name__)
CORS(app)

# ── Configuración ─────────────────────────────────────────────────────────────
STEL_API_KEY  = os.environ.get("STEL_API_KEY", "89Z29hNbdLcCpnhYWh6PVigj70n83UdRPCMPlQER")
STEL_BASE_URL = os.environ.get("STEL_BASE_URL", "https://app.stelorder.com")
HEADERS       = {"APIKEY": STEL_API_KEY, "Content-Type": "application/json"}

# Ruta al HTML (mismo directorio que este script)
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
FICHA_PATH = os.path.join(BASE_DIR, "ficha_cctv_tecnicos.html")
# ─────────────────────────────────────────────────────────────────────────────


def _lista(data, *claves):
    """Extrae lista de una respuesta que puede ser lista directa o dict con clave."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in claves:
            if k in data and isinstance(data[k], list):
                return data[k]
    return []


def _campos_cliente(cli):
    """
    Mapea los campos reales de Stel Order al formato interno de la ficha.
    Campos confirmados: legal-name, name, phone, phone2, email, main-address.*
    """
    addr = cli.get("main-address") or {}
    return {
        "cliente":  str(cli.get("id", "")),
        "nomcom":   cli.get("legal-name") or cli.get("name") or "",
        "nombre":   cli.get("name") or cli.get("legal-name") or "",
        "dir":      addr.get("address-data") or addr.get("formatted-address") or "",
        "pobl":     addr.get("city-town") or addr.get("city") or "",
        "cp":       addr.get("postal-code") or "",
        "tlfno":    cli.get("phone") or cli.get("phone2") or "",
        "email":    cli.get("email") or "",
    }


# ── Rutas HTML ────────────────────────────────────────────────────────────────
def _html_con_tecnico(nombre_tecnico=None):
    """Lee el HTML e inyecta el nombre del técnico si se proporciona."""
    with open(FICHA_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    if nombre_tecnico:
        # Inyecta variable JS antes de </head> para preseleccionar técnico
        script = f'<script>window.TECNICO_PRESELECCIONADO = "{nombre_tecnico}";</script>'
        html = html.replace("</head>", script + "\n</head>")
    return Response(html, mimetype="text/html")

@app.route("/", methods=["GET"])
@app.route("/ficha", methods=["GET"])
def ficha():
    """Ficha sin técnico preseleccionado."""
    return _html_con_tecnico()

@app.route("/tecnico/<nombre>", methods=["GET"])
def ficha_tecnico(nombre):
    """
    Ficha con el técnico preseleccionado.
    Ej: /tecnico/Javi  →  abre la ficha con Javi ya seleccionado.
    """
    return _html_con_tecnico(nombre)


# ── Proxy productos (endpoint original) ──────────────────────────────────────
@app.route("/app/products", methods=["GET"])
def productos():
    params = dict(request.args)
    try:
        resp = requests.get(f"{STEL_BASE_URL}/app/products",
                            headers=HEADERS, params=params, timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Buscar producto por código de barras ──────────────────────────────────────
@app.route("/api/producto", methods=["GET"])
def buscar_producto():
    """
    GET /api/producto?barcode=8412345678901
    Devuelve: { "found": true, "nombre": "Cámara domo IP 4MP" }
    """
    barcode = request.args.get("barcode", "").strip()
    if not barcode:
        return jsonify({"error": "Falta barcode"}), 400

    try:
        # Búsqueda por barcode exacto
        r = requests.get(f"{STEL_BASE_URL}/app/products",
                         headers=HEADERS,
                         params={"barcode": barcode, "limit": 5},
                         timeout=10)
        items = _lista(r.json(), "data", "products", "items")

        # Si no aparece, buscar por referencia (algunos productos usan ref como barcode)
        if not items:
            r2 = requests.get(f"{STEL_BASE_URL}/app/products",
                              headers=HEADERS,
                              params={"reference": barcode, "limit": 5},
                              timeout=10)
            items = _lista(r2.json(), "data", "products", "items")

        if items:
            p = items[0]
            nombre = p.get("name") or p.get("description") or p.get("reference") or ""
            return jsonify({"found": True, "nombre": nombre, "producto": p})

        return jsonify({"found": False})

    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Sin conexión a Stel Order"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Cargar cliente por nº de aviso ────────────────────────────────────────────
@app.route("/api/cliente-aviso", methods=["GET"])
def cliente_por_aviso():
    """
    GET /api/cliente-aviso?aviso=ABT00027

    La API de Stel Order no soporta filtrar por reference/full-reference como
    parámetro GET. Solución: traer los últimos registros y buscar por full-reference
    en el servidor (búsqueda local sobre la página devuelta).

    Busca en: workDeliveryNotes → incidents → workOrders → workEstimates
    """
    aviso = request.args.get("aviso", "").strip().upper()
    if not aviso:
        return jsonify({"error": "Falta aviso"}), 400

    # Endpoints a buscar en orden de probabilidad
    # (ABT = Albarán de Trabajo → workDeliveryNotes, MTO = incidents, PDT = workOrders)
    ENDPOINTS = [
        "/app/workDeliveryNotes",
        "/app/incidents",
        "/app/workOrders",
        "/app/workEstimates",
    ]

    try:
        for endpoint in ENDPOINTS:
            # Traer hasta 200 registros ordenados por fecha desc
            r = requests.get(f"{STEL_BASE_URL}{endpoint}",
                             headers=HEADERS,
                             params={"limit": 200, "sort": "date", "order": "desc"},
                             timeout=15)
            if r.status_code != 200:
                continue

            items = _lista(r.json(),
                           "data", "items", "incidents",
                           "workOrders", "workDeliveryNotes", "workEstimates")

            # Buscar por full-reference (exacto) o reference
            doc = None
            for item in items:
                fr = (item.get("full-reference") or "").upper()
                rf = (item.get("reference") or "").upper()
                if fr == aviso or rf == aviso:
                    doc = item
                    break

            if not doc:
                continue

            # Obtener datos del cliente por account-id
            cli_id = doc.get("account-id") or doc.get("client-id")
            if not cli_id:
                continue

            rc = requests.get(f"{STEL_BASE_URL}/app/clients/{cli_id}",
                              headers=HEADERS, timeout=10)
            if rc.status_code != 200:
                continue

            cliente_data = _campos_cliente(rc.json())
            cliente_data["contrato"] = doc.get("full-reference") or doc.get("reference") or aviso

            return jsonify({"found": True, "cliente": cliente_data})

        return jsonify({"found": False})

    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Sin conexión a Stel Order"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Crear parte de trabajo en Stel Order ──────────────────────────────────────
@app.route("/api/enviar-parte", methods=["POST"])
def enviar_parte():
    """
    POST /api/enviar-parte
    Crea un workOrder en Stel Order con los datos de la ficha.
    Campos en kebab-case según la API verificada.
    """
    data = request.json or {}

    # Buscar el ID del cliente si tenemos su referencia o nombre
    cliente_id = None
    if data.get("cliente") and str(data["cliente"]).isdigit():
        cliente_id = int(data["cliente"])

    # Construir líneas del parte (material instalado)
    lineas = []
    for item in data.get("material", []):
        if not item.get("ref") and not item.get("desc"):
            continue
        linea = {
            "quantity": 1,
            "description": item.get("desc") or item.get("ref") or "",
        }
        if item.get("ref"):
            linea["reference"] = item["ref"]
        if item.get("serie"):
            linea["serial-number"] = item["serie"]
        if item.get("ubic"):
            linea["notes"] = item["ubic"]
        lineas.append(linea)

    # Cuerpo del workOrder (kebab-case, formato Stel Order)
    parte = {
        "reference":   data.get("aviso") or "",
        "date":        data.get("fecha") or "",
        "notes":       "\n".join(filter(None, [
                           f"Contrato: {data.get('contrato','')}",
                           f"Técnico: {data.get('tecnico','')}",
                           f"Mantenimiento: {data.get('mant','')}",
                           data.get("obs", ""),
                       ])),
        "lines":       lineas,
    }
    if cliente_id:
        parte["client-id"] = cliente_id

    try:
        resp = requests.post(f"{STEL_BASE_URL}/app/workOrders",
                             headers=HEADERS,
                             json=parte,
                             timeout=15)
        result = {}
        if resp.content:
            try:
                result = resp.json()
            except Exception:
                pass

        if resp.status_code in (200, 201):
            wo_id = result.get("id") or result.get("reference") or ""
            return jsonify({"ok": True, "id": wo_id, "data": result})
        else:
            msg = result.get("message") or result.get("error") or resp.text[:200]
            return jsonify({"ok": False, "error": msg}), resp.status_code

    except requests.exceptions.ConnectionError:
        return jsonify({"ok": False, "error": "Sin conexión a Stel Order"}), 503
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ── Arranque ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("=" * 55)
    print(f"  SETEL Seguridad - Servidor")
    print(f"  http://localhost:{port}")
    print(f"  http://localhost:{port}/tecnico/Javi  (ejemplo)")
    print("  Ctrl+C para parar")
    print("=" * 55)
    app.run(host="0.0.0.0", port=port, debug=False)
