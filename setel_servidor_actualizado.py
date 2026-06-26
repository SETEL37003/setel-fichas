"""
SETEL Seguridad - Servidor Flask
Version preparada para Railway (nube) y uso local.

LOCAL:  python setel_servidor_actualizado.py  -> http://localhost:5000
NUBE:   Railway lo arranca automaticamente con el Procfile

URLs por tecnico:
  http://localhost:5000/tecnico/Javi
  http://localhost:5000/tecnico/Mario
  ... etc.
"""

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
import requests, os, re, io, json, glob
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Configuracion
STEL_API_KEY  = os.environ.get("STEL_API_KEY", "89Z29hNbdLcCpnhYWh6PVigj70n83UdRPCMPlQER")
STEL_BASE_URL = os.environ.get("STEL_BASE_URL", "https://app.stelorder.com")
HEADERS       = {"APIKEY": STEL_API_KEY, "Content-Type": "application/json"}

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
FICHA_PATH   = os.path.join(BASE_DIR, "ficha_cctv_tecnicos.html")
ALMACEN_PATH = os.path.join(BASE_DIR, "almacen.html")
REVISION_PATH= os.path.join(BASE_DIR, "revision.html")
# mantenimiento.html: en la nube (Railway) esta en la raiz del repo (BASE_DIR);
# en local esta en la carpeta hermana "Revision de mantenimiento".
MANT_PATH    = os.path.join(BASE_DIR, "mantenimiento.html")
if not os.path.exists(MANT_PATH):
    MANT_PATH = os.path.normpath(os.path.join(BASE_DIR, "..", "Revision de mantenimiento", "mantenimiento.html"))
# Carpeta donde se archivan los partes recibidos (copia de seguridad)
_MANT_BASE   = os.path.normpath(os.path.join(BASE_DIR, "..", "Revision de mantenimiento"))
MANT_DIR     = os.path.join(_MANT_BASE if os.path.isdir(_MANT_BASE) else BASE_DIR, "partes_recibidos")
SALIDAS_DIR  = os.path.join(BASE_DIR, "salidas")
PARTES_DIR   = os.path.join(BASE_DIR, "partes")
os.makedirs(SALIDAS_DIR, exist_ok=True)
os.makedirs(PARTES_DIR,  exist_ok=True)


def _lista(data, *claves):
    """Busca una lista dentro de un JSON de Stel Order.
    Prueba cada clave en el nivel raíz y también traversa anidados.
    """
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    # 1. Buscar cada clave en el nivel raíz
    for k in claves:
        if k in data and isinstance(data[k], list):
            return data[k]
    # 2. Traversar un nivel de profundidad (p.ej. data["data"]["products"])
    for k in claves:
        if k in data and isinstance(data[k], dict):
            sub = data[k]
            for k2 in claves:
                if k2 in sub and isinstance(sub[k2], list):
                    return sub[k2]
    # 3. Buscar recursivamente cualquier lista en los valores del dict
    for k, v in data.items():
        if isinstance(v, list) and v:
            return v
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if isinstance(v2, list) and v2:
                    return v2
    return []


def _campos_cliente(cli):
    if isinstance(cli, list):
        cli = cli[0] if cli else {}
    addr = cli.get("main-address") or {}
    num_cli = (cli.get("referencia") or cli.get("reference") or
               cli.get("client-number") or str(cli.get("id", "")))
    return {
        "cliente":  num_cli,
        "id_stel":  str(cli.get("id", "")),
        "nomcom":   cli.get("legal-name") or cli.get("name") or "",
        "nombre":   cli.get("name") or cli.get("legal-name") or "",
        "dir":      addr.get("address-data") or addr.get("formatted-address") or "",
        "pobl":     addr.get("city-town") or addr.get("city") or "",
        "cp":       addr.get("postal-code") or "",
        "tlfno":    cli.get("phone") or cli.get("phone2") or "",
        "email":    cli.get("email") or "",
    }


@app.route("/api/ping")
def ping():
    import time
    return jsonify({"ok": True, "ts": time.time()})

@app.route("/", methods=["GET"])
@app.route("/ficha", methods=["GET"])
def ficha():
    return _html_con_tecnico()

@app.route("/tecnico/<nombre>", methods=["GET"])
def ficha_tecnico(nombre):
    return _html_con_tecnico(nombre)

@app.route("/almacen", methods=["GET"])
def almacen():
    with open(ALMACEN_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    resp = Response(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.route("/revision", methods=["GET"])
def revision():
    with open(REVISION_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    resp = Response(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.route("/mantenimiento", methods=["GET"])
def mantenimiento():
    with open(MANT_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    resp = Response(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.route("/api/enviar-mantenimiento", methods=["POST"])
def enviar_mantenimiento():
    """Archiva un parte de mantenimiento (copia de seguridad en la oficina)."""
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"ok": False, "error": "JSON invalido"}), 400
    campos = data.get("campos", {}) or {}
    if not (campos.get("nombre") or "").strip():
        return jsonify({"ok": False, "error": "Falta el nombre del cliente"}), 400
    try:
        os.makedirs(MANT_DIR, exist_ok=True)
        hoy = datetime.now().strftime("%Y%m%d")
        n = len(glob.glob(os.path.join(MANT_DIR, f"MT-{hoy}-*.json"))) + 1
        ref = f"MT-{hoy}-{n:03d}"
        data["referencia"] = ref
        data["recibido"] = datetime.now().isoformat()
        with open(os.path.join(MANT_DIR, f"{ref}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, "referencia": ref})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

def _html_con_tecnico(nombre_tecnico=None):
    with open(FICHA_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    if nombre_tecnico:
        script = f'<script>window.TECNICO_PRESELECCIONADO = "{nombre_tecnico}";</script>'
        html = html.replace("</head>", script + "\n</head>")
    resp = Response(html, mimetype="text/html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/app/products", methods=["GET"])
def productos():
    params = dict(request.args)
    try:
        resp = requests.get(f"{STEL_BASE_URL}/app/products",
                            headers=HEADERS, params=params, timeout=10)
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/producto", methods=["GET"])
def buscar_producto():
    barcode = request.args.get("barcode", "").strip()
    if not barcode:
        return jsonify({"error": "Falta barcode"}), 400
    try:
        items = []
        for param in [{"barcode": barcode}, {"reference": barcode}, {"name": barcode}]:
            r = requests.get(f"{STEL_BASE_URL}/app/products",
                             headers=HEADERS,
                             params={**param, "limit": 5},
                             timeout=10)
            if r.status_code != 200:
                continue
            try:
                found = _lista(r.json(), "data", "products", "items")
            except Exception:
                continue
            if found:
                items = found
                break
        # Si no hay items, devolver respuesta de diagnóstico
        if not items:
            # Intentar obtener el JSON crudo del primer intento para diagnóstico
            try:
                r_diag = requests.get(f"{STEL_BASE_URL}/app/products",
                                      headers=HEADERS,
                                      params={"reference": barcode, "limit": 5},
                                      timeout=10)
                raw = r_diag.json() if r_diag.status_code == 200 else {"http_status": r_diag.status_code}
            except Exception as ex:
                raw = {"error_diag": str(ex)}
            return jsonify({"found": False, "_debug_raw": raw})

        if items:
            p = items[0]
            def _extraer_nombre_producto(p):
                """Busca la descripción en cualquier campo del producto, incluyendo anidados."""
                # Campos directos - incluye variantes camelCase y con guiones
                CAMPOS_NOMBRE = [
                    # Inglés estándar
                    "name", "description", "title",
                    # Con guion (estilo Stel Order)
                    "product-name", "product-description", "item-name",
                    "commercial-name", "comercial-name", "short-description",
                    "long-description", "article-name",
                    # camelCase (común en APIs españolas)
                    "productName", "productDescription", "comercialName",
                    "nombreComercial", "itemName", "articleName",
                    "shortDescription", "longDescription",
                    # Español
                    "nombre", "titulo", "descripcion", "denominacion",
                    "articulo", "detalle", "etiqueta", "label",
                    "summary", "detail", "denomination",
                ]
                CAMPOS_SKIP_SET = {
                    "id", "reference", "barcode", "ean", "code", "sku",
                    "type", "status", "price", "cost", "tax", "quantity",
                    "stock", "weight", "created", "updated", "category",
                    "family", "provider", "url", "image", "currency",
                    "measure", "unit", "vat", "margin", "discount",
                }
                def _es_skip(k):
                    kl = k.lower().replace("-", "").replace("_", "")
                    return any(s in kl for s in CAMPOS_SKIP_SET)

                # 1. Buscar en campos conocidos directamente
                for f in CAMPOS_NOMBRE:
                    v = p.get(f)
                    if v and isinstance(v, str) and len(v.strip()) > 1:
                        return v.strip()
                # 2. Buscar en objetos anidados (p.ej. "product": {"name": "..."})
                for k, v in p.items():
                    if isinstance(v, dict):
                        for f in CAMPOS_NOMBRE:
                            vv = v.get(f)
                            if vv and isinstance(vv, str) and len(vv.strip()) > 1:
                                return vv.strip()
                        # También cualquier string largo dentro del subobjeto
                        for sk, sv in v.items():
                            if not _es_skip(sk) and isinstance(sv, str) and len(sv.strip()) > 3 and not sv.strip().isdigit():
                                return sv.strip()
                # 3. Cualquier string largo que no sea un campo técnico
                candidatos = [
                    (k, str(v)) for k, v in p.items()
                    if not _es_skip(k)
                    and isinstance(v, str)
                    and len(v.strip()) > 3
                    and not v.strip().isdigit()
                ]
                candidatos.sort(key=lambda x: len(x[1]), reverse=True)
                if candidatos:
                    return candidatos[0][1].strip()
                return ""

            nombre = _extraer_nombre_producto(p)
            referencia = p.get("reference") or p.get("barcode") or p.get("ean") or barcode
            # Devolver también todos los campos para diagnóstico
            return jsonify({
                "found":      True,
                "nombre":     nombre,
                "referencia": referencia,
                "item_id":    p.get("id"),
                "producto":   p,
                "_campos":    list(p.keys()),  # para diagnóstico
            })
        return jsonify({"found": False})
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Sin conexion a Stel Order"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/buscar-cliente", methods=["GET"])
def buscar_cliente_por_nombre():
    nombre = request.args.get("nombre", "").strip()
    if not nombre or len(nombre) < 2:
        return jsonify({"clientes": []})
    try:
        clientes = []
        for param in [{"name": nombre}, {"search": nombre}, {"query": nombre}]:
            r = requests.get(f"{STEL_BASE_URL}/app/clients",
                             headers=HEADERS,
                             params={**param, "limit": 20},
                             timeout=10)
            if r.status_code != 200:
                continue
            items = _lista(r.json(), "data", "clients", "items")
            if items:
                clientes = items
                break
        if not clientes:
            # Fallback: traer todos y filtrar localmente con normalización
            import unicodedata, re as _re
            def _norm(s):
                # quitar acentos, puntos, guiones y pasar a minúsculas
                s = unicodedata.normalize("NFD", str(s))
                s = "".join(c for c in s if unicodedata.category(c) != "Mn")
                s = _re.sub(r"[^a-z0-9 ]", " ", s.lower())
                return " ".join(s.split())

            palabras = _norm(nombre).split()

            for page_limit in [200, 500]:
                r = requests.get(f"{STEL_BASE_URL}/app/clients",
                                 headers=HEADERS,
                                 params={"limit": page_limit, "sort": "name", "order": "asc"},
                                 timeout=15)
                if r.status_code == 200:
                    items = _lista(r.json(), "data", "clients", "items")
                    def _coincide(c):
                        campos = " ".join([
                            c.get("name") or "",
                            c.get("legal-name") or "",
                            c.get("commercial-name") or "",
                            c.get("nomcom") or "",
                        ])
                        texto = _norm(campos)
                        return all(p in texto for p in palabras)
                    clientes = [c for c in items if _coincide(c)][:15]
                    if clientes:
                        break
        resultado = []
        # Posibles nombres del campo número/referencia de cliente en Stel Order
        NUM_FIELDS = ["referencia", "reference", "client-number", "num", "numero",
                      "cod", "codigo", "code", "external-id", "customer-number",
                      "client_number", "num_cliente", "nif", "cif"]
        for c in clientes[:15]:
            addr = c.get("main-address") or {}
            # Buscar el número en campos conocidos y en cualquier campo que lo contenga
            num_cli = next((str(c[f]) for f in NUM_FIELDS if c.get(f)), None)
            if not num_cli:
                num_cli = str(c.get("id", ""))
            resultado.append({
                "id":      str(c.get("id", "")),
                "num_cli": num_cli,
                "nombre":  (c.get("legal-name") or c.get("name") or
                            c.get("commercial-name") or c.get("nomcom") or ""),
                "dir":     addr.get("address-data") or addr.get("formatted-address") or addr.get("address") or "",
                "pobl":    addr.get("city-town") or addr.get("city") or addr.get("town") or "",
                "cp":      addr.get("postal-code") or addr.get("zip") or "",
                "tlfno":   c.get("phone") or c.get("phone2") or c.get("mobile") or "",
                "email":   c.get("email") or "",
            })
        return jsonify({"clientes": resultado})
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Sin conexion a Stel Order"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/buscar-cliente-numero", methods=["GET"])
def buscar_cliente_por_numero():
    numero = request.args.get("numero", "").strip()
    if not numero or len(numero) < 1:
        return jsonify({"clientes": []})
    try:
        clientes = []
        # Intentar búsqueda directa por referencia/número
        for param in [{"referencia": numero}, {"reference": numero}, {"client-number": numero}]:
            r = requests.get(f"{STEL_BASE_URL}/app/clients",
                             headers=HEADERS,
                             params={**param, "limit": 20},
                             timeout=10)
            if r.status_code == 200:
                items = _lista(r.json(), "data", "clients", "items")
                if items:
                    clientes = items
                    break
        if not clientes:
            # Fallback: traer todos y filtrar por número en CUALQUIER campo
            for page_limit in [200, 500]:
                r = requests.get(f"{STEL_BASE_URL}/app/clients",
                                 headers=HEADERS,
                                 params={"limit": page_limit, "sort": "name", "order": "asc"},
                                 timeout=15)
                if r.status_code == 200:
                    items = _lista(r.json(), "data", "clients", "items")
                    # Buscar el número en todos los valores del objeto (no solo campos conocidos)
                    def _contiene_numero(c, num):
                        for v in c.values():
                            if isinstance(v, (str, int)) and num in str(v):
                                return True
                        return False
                    clientes = [c for c in items if _contiene_numero(c, numero)][:15]
                    if clientes:
                        break
        resultado = []
        # Posibles nombres del campo número/referencia de cliente en Stel Order
        NUM_FIELDS = ["referencia", "reference", "client-number", "num", "numero",
                      "cod", "codigo", "code", "external-id", "customer-number",
                      "client_number", "num_cliente", "nif", "cif"]
        for c in clientes[:15]:
            addr = c.get("main-address") or {}
            # Buscar el número en campos conocidos y en cualquier campo que lo contenga
            num_cli = next((str(c[f]) for f in NUM_FIELDS if c.get(f)), None)
            if not num_cli:
                num_cli = str(c.get("id", ""))
            resultado.append({
                "id":      str(c.get("id", "")),
                "num_cli": num_cli,
                "nombre":  (c.get("legal-name") or c.get("name") or
                            c.get("commercial-name") or c.get("nomcom") or ""),
                "dir":     addr.get("address-data") or addr.get("formatted-address") or addr.get("address") or "",
                "pobl":    addr.get("city-town") or addr.get("city") or addr.get("town") or "",
                "cp":      addr.get("postal-code") or addr.get("zip") or "",
                "tlfno":   c.get("phone") or c.get("phone2") or c.get("mobile") or "",
                "email":   c.get("email") or "",
            })
        return jsonify({"clientes": resultado})
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Sin conexion a Stel Order"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/debug-cliente-campos", methods=["GET"])
def debug_cliente_campos():
    """Endpoint de diagnóstico: muestra las claves del primer cliente devuelto por Stel Order"""
    try:
        r = requests.get(f"{STEL_BASE_URL}/app/clients",
                         headers=HEADERS,
                         params={"limit": 3},
                         timeout=10)
        if r.status_code != 200:
            return jsonify({"error": f"Stel devolvió {r.status_code}", "body": r.text[:500]}), 502
        raw = r.json()
        items = _lista(raw, "data", "clients", "items")
        if not items:
            return jsonify({"error": "Sin clientes", "raw_keys": list(raw.keys()) if isinstance(raw, dict) else "lista vacía"})
        primer = items[0]
        return jsonify({
            "campos": list(primer.keys()),
            "muestra": {k: str(v)[:80] for k, v in primer.items() if not isinstance(v, dict)},
            "total_items": len(items)
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cliente-aviso", methods=["GET"])
def cliente_por_aviso():
    aviso = request.args.get("aviso", "").strip().upper()
    if not aviso:
        return jsonify({"error": "Falta aviso"}), 400
    ENDPOINTS = [
        "/app/workDeliveryNotes",
        "/app/incidents",
        "/app/workOrders",
        "/app/workEstimates",
    ]
    try:
        for endpoint in ENDPOINTS:
            r = requests.get(f"{STEL_BASE_URL}{endpoint}",
                             headers=HEADERS,
                             params={"limit": 200, "sort": "date", "order": "desc"},
                             timeout=15)
            if r.status_code != 200:
                continue
            items = _lista(r.json(), "data", "items", "incidents",
                           "workOrders", "workDeliveryNotes", "workEstimates")
            doc = None
            for item in items:
                fr = (item.get("full-reference") or "").upper()
                rf = (item.get("reference") or "").upper()
                if fr == aviso or rf == aviso:
                    doc = item
                    break
            if not doc:
                continue
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
        return jsonify({"error": "Sin conexion a Stel Order"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def cliente_por_aviso():
    aviso = request.args.get("aviso", "").strip().upper()
    if not aviso:
        return jsonify({"error": "Falta aviso"}), 400
    ENDPOINTS = ["/app/workDeliveryNotes","/app/incidents","/app/workOrders","/app/workEstimates"]
    try:
        for endpoint in ENDPOINTS:
            r = requests.get(f"{STEL_BASE_URL}{endpoint}", headers=HEADERS,
                             params={"limit": 200}, timeout=15)
            if r.status_code != 200: continue
            items = _lista(r.json(), "data", "items", "incidents",
                           "workOrders", "workDeliveryNotes", "workEstimates")
            doc = next((i for i in items if
                        (i.get("full-reference") or "").upper() == aviso or
                        (i.get("reference") or "").upper() == aviso), None)
            if not doc: continue
            cli_id = doc.get("account-id") or doc.get("client-id")
            if not cli_id: continue
            rc = requests.get(f"{STEL_BASE_URL}/app/clients/{cli_id}", headers=HEADERS, timeout=10)
            if rc.status_code != 200: continue
            cliente_data = _campos_cliente(rc.json())
            cliente_data["contrato"] = doc.get("full-reference") or doc.get("reference") or aviso
            return jsonify({"found": True, "cliente": cliente_data})
        return jsonify({"found": False})
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Sin conexion a Stel Order"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── PDF: generar y adjuntar ────────────────────────────────────────────────────

def _html_pdf_ficha(data):
    mat   = data.get("material", [])
    fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
    def v(key, default=""):
        val = data.get(key, default)
        return str(val).strip() if val else default
    filas_mat = ""
    for i, item in enumerate(mat, 1):
        if item.get("ref") or item.get("desc"):
            estado = ""
            if item.get("devuelto"): estado = " [DEVUELTO]"
            elif item.get("furgoneta"): estado = " [FURGONETA]"
            filas_mat += (
                f"<tr><td style='text-align:center'>{i}</td>"
                f"<td>{item.get('ref','')}</td>"
                f"<td>{item.get('desc','')}{estado}</td>"
                f"<td>{item.get('serie','')}</td>"
                f"<td>{item.get('ip','')}</td>"
                f"<td>{item.get('ubic','')}</td></tr>"
            )
    if not filas_mat:
        filas_mat = "<tr><td colspan='6' style='text-align:center;color:#999'>Sin material</td></tr>"
    return (
        "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'><style>"
        "* {box-sizing:border-box;margin:0;padding:0;}"
        "body {font-family:Arial,sans-serif;font-size:10pt;color:#222;background:#fff;}"
        ".hdr {background:#1a3a6b;color:white;padding:12px 20px;display:flex;justify-content:space-between;}"
        ".hdr h1 {font-size:14pt;font-weight:bold;}"
        ".hdr .meta {text-align:right;font-size:8pt;line-height:1.7;opacity:.9;}"
        ".sec {background:#1a3a6b;color:white;font-size:8pt;font-weight:bold;padding:3px 8px;margin:10px 18px 4px;}"
        ".grid {display:grid;gap:4px;margin:0 18px 4px;}"
        ".g2 {grid-template-columns:1fr 1fr;} .g3 {grid-template-columns:1fr 1fr 1fr;}"
        ".field {border:1px solid #ccc;padding:3px 7px;min-height:24px;}"
        ".lbl {font-size:7pt;color:#777;display:block;} .val {font-size:10pt;font-weight:600;}"
        "table {width:100%;border-collapse:collapse;font-size:8.5pt;}"
        "thead th {background:#f5a623;color:#412402;padding:4px 6px;text-align:left;}"
        "tbody tr:nth-child(even) {background:#f7f7f7;}"
        "tbody td {border:1px solid #ddd;padding:3px 6px;}"
        ".obs {border:1px solid #ccc;padding:6px;min-height:40px;font-size:9.5pt;margin:0 18px;}"
        ".footer {margin:14px 18px 10px;padding-top:6px;border-top:1px solid #ddd;"
        "font-size:7.5pt;color:#888;display:flex;justify-content:space-between;}"
        "</style></head><body>"
        f"<div class='hdr'><h1>SETEL Seguridad &mdash; Ficha CCTV</h1>"
        f"<div class='meta'><div>Aviso: <strong>{v('aviso') or v('contrato')}</strong></div>"
        f"<div>Contrato: {v('contrato')}</div>"
        f"<div>Fecha: {fecha}</div></div></div>"
        "<div class='sec'>DATOS DEL CLIENTE</div>"
        f"<div class='grid g2'>"
        f"<div class='field'><span class='lbl'>RAZ&Oacute;N SOCIAL</span><span class='val'>{v('nomcom')}</span></div>"
        f"<div class='field'><span class='lbl'>N&ordm; CLIENTE</span><span class='val'>{v('cliente')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>DIRECCI&Oacute;N</span><span class='val'>{v('direccion') or v('dir')}</span></div>"
        f"<div class='field'><span class='lbl'>POBLACI&Oacute;N</span><span class='val'>{v('poblacion') or v('pobl')}</span></div>"
        f"<div class='field'><span class='lbl'>C.P.</span><span class='val'>{v('cp')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>TEL&Eacute;FONO</span><span class='val'>{v('tlfno')}</span></div>"
        f"<div class='field'><span class='lbl'>EMAIL</span><span class='val'>{v('email')}</span></div>"
        f"<div class='field'><span class='lbl'>CONTRATO</span><span class='val'>{v('contrato')}</span></div></div>"
        "<div class='sec'>DATOS DE LA INTERVENCI&Oacute;N</div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>T&Eacute;CNICO</span><span class='val'>{v('tecnico')}</span></div>"
        f"<div class='field'><span class='lbl'>VIA / AVISO</span><span class='val'>{v('aviso')} {v('via')}</span></div>"
        f"<div class='field'><span class='lbl'>RECEPTORA / ABONADO</span><span class='val'>{v('receptora')} / {v('n_abonado')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>V&Iacute;DEO / DOM</span><span class='val'>{v('video')} / {v('dom')}</span></div>"
        f"<div class='field'><span class='lbl'>IP C&Aacute;MARA / CAM IP</span><span class='val'>{v('ip')} / {v('camip')}</span></div>"
        f"<div class='field'><span class='lbl'>PUERTO / PUERTOW / P2P</span><span class='val'>{v('puerto')} / {v('puertow')} / {v('p2p')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>MANTENIMIENTO</span><span class='val'>{v('mant')}</span></div>"
        f"<div class='field'><span class='lbl'>D&Iacute;AS GRABACI&Oacute;N</span><span class='val'>{v('dias')}</span></div>"
        f"<div class='field'><span class='lbl'>CLAVE ADMIN</span><span class='val'>{v('adm') or v('adm1')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>USUARIO</span><span class='val'>{v('usr')}</span></div>"
        f"<div class='field'><span class='lbl'>CONTACTO</span><span class='val'>{v('contacto')}</span></div>"
        f"<div class='field'><span class='lbl'>CABLE</span><span class='val'>{v('cable')}</span></div></div>"
        "<div class='sec'>MATERIAL INSTALADO</div>"
        "<div style='margin:0 18px;'><table><thead><tr>"
        "<th style='width:28px'>#</th><th style='width:100px'>REFERENCIA</th>"
        "<th>DESCRIPCI&Oacute;N</th><th style='width:110px'>N&ordm; SERIE</th>"
        "<th style='width:80px'>IP</th><th>UBICACI&Oacute;N</th>"
        f"</tr></thead><tbody>{filas_mat}</tbody></table></div>"
        "<div class='sec'>OBSERVACIONES</div>"
        f"<div class='obs'>{v('observaciones') or v('obs')}</div>"
        + _html_firma_fotos(data)
        + f"<div class='footer'>"
        "<span>SETEL Seguridad &mdash; T&eacute;cnicos de Servicios M&uacute;ltiples S.L. &mdash; Salamanca</span>"
        f"<span>Generado: {fecha}</span></div>"
        "</body></html>"
    )


def _generar_pdf_ficha(data):
    try:
        from weasyprint import HTML
        return HTML(string=_html_pdf_ficha(data)).write_pdf()
    except ImportError:
        raise RuntimeError("WeasyPrint no instalado. Ejecuta instalar_weasyprint.bat primero.")


def _subir_file_io(pdf_bytes, filename="ficha_cctv.pdf"):
    try:
        r = requests.post("https://file.io",
                          files={"file": (filename, io.BytesIO(pdf_bytes), "application/pdf")},
                          data={"expires": "14d"}, timeout=30)
        result = r.json()
        if result.get("success"):
            url = result.get("link")
            print(f"[FILE.IO] Subido OK: {url}")
            return url
        print(f"[FILE.IO] Error: {result}")
    except Exception as e:
        print(f"[FILE.IO] Error al subir: {e}")
    return None


def _adjuntar_a_parte(wo_id, file_url):
    try:
        payload = {"file-url": file_url, "entity-id": int(wo_id), "entity-type": "WORKORDER"}
        r = requests.post(f"{STEL_BASE_URL}/app/entityAttachments",
                          headers=HEADERS, json=payload, timeout=15)
        print(f"[STEL] Adjunto HTTP {r.status_code}: {r.text[:200]}")
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"[STEL] Error al adjuntar: {e}")
        return False



# ── Endpoint: enviar parte ─────────────────────────────────────────────────────

@app.route("/api/enviar-parte", methods=["POST"])
def enviar_parte():
    data = request.get_json(force=True)
    contrato = (data.get("contrato") or "").strip().upper()
    tecnico   = (data.get("tecnico") or "").strip()
    material  = data.get("material", [])

    # ── 1. Guardar parte local ────────────────────────────────────────────────
    hoy_p = datetime.now().strftime("%y%m%d")
    existing_p = glob.glob(os.path.join(PARTES_DIR, f"PT-{hoy_p}-*.json"))
    seq_p = len(existing_p) + 1
    parte_ref_local = f"PT-{hoy_p}-{seq_p:03d}"
    # Guardar TODOS los campos del request + los generados por el servidor
    parte_local = dict(data)   # copia completa del payload del técnico
    parte_local.update({
        "referencia":        parte_ref_local,
        "fecha":             datetime.now().isoformat(),
        "estado":            "pendiente",
        "material":          material,
        "presupuesto":       data.get("contrato", ""),
        "aviso":             data.get("aviso", ""),
        "nomcom":            data.get("nomcom") or data.get("nombre") or "",
        "direccion":         data.get("direccion") or data.get("dir") or "",
        "poblacion":         data.get("poblacion") or data.get("pobl") or "",
        "observaciones":     data.get("observaciones") or data.get("obs") or "",
        "firma_cliente":     data.get("firma_cliente") or {},
        "firma_tecnico":     data.get("firma_tecnico") or {},
        "fotos":             data.get("fotos") or [],
        "wo_id":             None,
        "wo_ref":            None,
    })

    # ── 2. Buscar cliente en Stel Order ──────────────────────────────────────
    cliente_id = None
    if contrato:
        try:
            for ep in ["/app/workOrders", "/app/workEstimates",
                       "/app/workDeliveryNotes", "/app/incidents"]:
                r = requests.get(f"{STEL_BASE_URL}{ep}", headers=HEADERS,
                                 params={"limit": 200}, timeout=15)
                if r.status_code != 200: continue
                items = _lista(r.json(), "data","items","workOrders",
                               "workEstimates","workDeliveryNotes","incidents")
                doc = next((i for i in items if
                            (i.get("full-reference") or i.get("reference") or "").upper() == contrato), None)
                if doc:
                    cliente_id = doc.get("account-id") or doc.get("client-id")
                    # enriquecer datos de cliente
                    if cliente_id:
                        rc = requests.get(f"{STEL_BASE_URL}/app/clients/{cliente_id}",
                                          headers=HEADERS, timeout=10)
                        if rc.status_code == 200:
                            cd = _campos_cliente(rc.json())
                            for k, flds in {
                                "nomcom":    ["nomcom","nombre"],
                                "direccion": ["direccion","dir"],
                                "poblacion": ["poblacion","pobl"],
                                "cp":        ["cp"],
                                "tlfno":     ["tlfno"],
                            }.items():
                                for f in flds:
                                    if not parte_local[k] and cd.get(f):
                                        parte_local[k] = cd[f]
                                        break
                    break
        except Exception as e:
            print(f"[STEL] Error buscando cliente: {e}")

    parte_local["cliente_id"] = str(cliente_id or "")

    # ── 3. Guardar JSON ──────────────────────────────────────────────────────
    parte_path = os.path.join(PARTES_DIR, f"{parte_ref_local}.json")
    try:
        with open(parte_path, "w", encoding="utf-8") as f:
            json.dump(parte_local, f, ensure_ascii=False, indent=2)
        print(f"[PARTE] Guardado {parte_ref_local}")
    except Exception as e:
        print(f"[PARTE] Error guardando: {e}")

    # ── 4. Generar PDF ───────────────────────────────────────────────────────
    try:
        pdf_bytes = _generar_pdf_ficha(data)
    except Exception as e:
        return jsonify({"ok": True, "parte_ref": parte_ref_local,
                        "warn": f"Parte guardado pero no se pudo generar PDF: {e}"}), 200

    # ── 5. Subir a file.io ───────────────────────────────────────────────────
    pdf_filename = f"SETEL_CCTV_{contrato or parte_ref_local}.pdf"
    file_url = _subir_file_io(pdf_bytes, pdf_filename)
    if not file_url:
        # guardar PDF local como fallback
        pdf_path = os.path.join(PARTES_DIR, pdf_filename)
        with open(pdf_path, "wb") as pf:
            pf.write(pdf_bytes)
        return jsonify({"ok": True, "parte_ref": parte_ref_local,
                        "warn": "PDF guardado localmente (file.io no disponible)",
                        "pdf_local": pdf_path}), 200

    # ── 6. Crear Work Order en Stel Order ────────────────────────────────────
    wo_id  = None
    wo_ref = None
    if cliente_id and contrato:
        try:
            lineas_wo = []
            for item in material:
                if item.get("ref"):
                    try:
                        pr = requests.get(f"{STEL_BASE_URL}/app/products",
                                          headers=HEADERS,
                                          params={"reference": item["ref"], "limit": 1},
                                          timeout=10)
                        prod_data = pr.json()
                        prods = _lista(prod_data, "data","items","products")
                        prod = next((p for p in prods if
                                     (p.get("reference") or "").upper() == item["ref"].upper()), None)
                        if prod:
                            lineas_wo.append({
                                "product-id":    prod["id"],
                                "quantity":      1,
                                "selling-price": prod.get("selling-price", 0),
                                "description":   item.get("desc", prod.get("name", item["ref"])),
                            })
                    except Exception:
                        pass
            wo_payload = {
                "account-id":   int(cliente_id),
                "title":        f"Instalación CCTV – {contrato}",
                "description":  data.get("obs", ""),
                "reference":    contrato,
                "technician":   tecnico,
                "lines":        lineas_wo,
            }
            rwo = requests.post(f"{STEL_BASE_URL}/app/workOrders",
                                headers=HEADERS, json=wo_payload, timeout=15)
            print(f"[STEL] WO HTTP {rwo.status_code}: {rwo.text[:300]}")
            if rwo.status_code in (200, 201):
                wo_data = rwo.json()
                wo_id  = wo_data.get("id") or (wo_data.get("data") or {}).get("id")
                wo_ref = (wo_data.get("full-reference") or
                          (wo_data.get("data") or {}).get("full-reference") or "")
        except Exception as e:
            print(f"[STEL] Error creando WO: {e}")

    # ── 7. Adjuntar PDF ──────────────────────────────────────────────────────
    if wo_id and file_url:
        _adjuntar_a_parte(wo_id, file_url)

    # ── 8. Actualizar parte local con wo_id ──────────────────────────────────
    if wo_id:
        parte_local["wo_id"]  = wo_id
        parte_local["wo_ref"] = wo_ref
        try:
            with open(parte_path, "w", encoding="utf-8") as f:
                json.dump(parte_local, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return jsonify({
        "ok":          True,
        "parte_ref":   parte_ref_local,
        "wo_id":       wo_id,
        "wo_ref":      wo_ref,
        "pdf_url":     file_url,
    })



# ── Endpoints: presupuesto ─────────────────────────────────────────────────────

@app.route("/api/presupuesto", methods=["GET"])
def buscar_presupuesto():
    ref = request.args.get("ref", "").strip().upper()
    if not ref:
        return jsonify({"error": "Falta ref"}), 400
    try:
        r = requests.get(f"{STEL_BASE_URL}/app/workEstimates",
                         headers=HEADERS, params={"limit": 200}, timeout=15)
        if r.status_code != 200:
            return jsonify({"found": False, "error": f"HTTP {r.status_code}"}), 200
        items = _lista(r.json(), "data", "items", "workEstimates")
        doc = next((i for i in items if
                    (i.get("full-reference") or i.get("reference") or "").upper() == ref), None)
        if not doc:
            return jsonify({"found": False})
        # Obtener lineas detalladas
        doc_id = doc.get("id")
        lineas_raw = []
        if doc_id:
            rl = requests.get(f"{STEL_BASE_URL}/app/workEstimates/{doc_id}/lines",
                              headers=HEADERS, timeout=10)
            if rl.status_code == 200:
                lineas_raw = _lista(rl.json(), "data", "items", "lines")
        items_parsed = []
        for ln in lineas_raw:
            item_id = ln.get("product-id") or ln.get("id")
            ref_prod = ln.get("reference") or ln.get("product-reference") or ""
            nombre   = ln.get("description") or ln.get("name") or ref_prod
            cant     = ln.get("quantity") or 1
            items_parsed.append({
                "item-id":  item_id,
                "ref":      ref_prod,
                "nombre":   nombre,
                "cantidad": cant,
            })
        cliente_info = {}
        cli_id = doc.get("account-id") or doc.get("client-id")
        if cli_id:
            rc = requests.get(f"{STEL_BASE_URL}/app/clients/{cli_id}", headers=HEADERS, timeout=10)
            if rc.status_code == 200:
                cliente_info = _campos_cliente(rc.json())
        return jsonify({
            "found":    True,
            "id":       doc_id,
            "ref":      ref,
            "cliente":  doc.get("account-name") or cliente_info.get("nomcom") or "",
            "lineas":   len(items_parsed),
            "items":    items_parsed,
            **cliente_info,
        })
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Sin conexion a Stel Order"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Almacén: descuento de stock en Stel Order ─────────────────────────────────

def _descontar_stock_stel(items_list, sal_ref=""):
    """
    Intenta descontar stock en Stel Order para cada item de la salida.
    No lanza excepción: devuelve lista con resultado por item.
    Prueba dos endpoints distintos según la versión de la API de Stel Order.
    """
    resultados = []
    for item in items_list:
        item_id  = item.get("item_id")
        cantidad = int(item.get("cantidad", 1))
        ref      = item.get("ref", "")
        serie    = item.get("serie", "")

        if not item_id:
            resultados.append({"ref": ref, "status": "sin_id_stel"})
            continue

        nota = f"Salida almacén SETEL {sal_ref}"
        if serie:
            nota += f" | serie {serie}"

        # Intento 1: endpoint por producto  (algunas versiones de Stel Order)
        ok = False
        try:
            r = requests.post(
                f"{STEL_BASE_URL}/app/products/{item_id}/stockMovements",
                headers=HEADERS,
                json={"quantity": -cantidad, "type": "out", "notes": nota},
                timeout=10,
            )
            if r.status_code in (200, 201):
                ok = True
                resultados.append({"ref": ref, "status": "ok", "endpoint": "v1"})
        except Exception:
            pass

        if ok:
            continue

        # Intento 2: endpoint global de movimientos
        try:
            r2 = requests.post(
                f"{STEL_BASE_URL}/app/stockMovements",
                headers=HEADERS,
                json={
                    "product-id": item_id,
                    "quantity":   -cantidad,
                    "type":       "out",
                    "notes":      nota,
                },
                timeout=10,
            )
            if r2.status_code in (200, 201):
                resultados.append({"ref": ref, "status": "ok", "endpoint": "v2"})
            else:
                resultados.append({
                    "ref": ref, "status": "api_error",
                    "code": r2.status_code, "body": r2.text[:200],
                })
        except Exception as e:
            resultados.append({"ref": ref, "status": "error", "error": str(e)})

    return resultados


# ── Endpoints: almacén ────────────────────────────────────────────────────────

@app.route("/api/salida-almacen", methods=["POST"])
def registrar_salida():
    data = request.get_json(force=True)
    ref = data.get("referencia", "").strip()
    if not ref:
        hoy_s = datetime.now().strftime("%y%m%d")
        existing_s = glob.glob(os.path.join(SALIDAS_DIR, f"SAL-{hoy_s}-*.json"))
        ref = f"SAL-{hoy_s}-{len(existing_s)+1:03d}"
        data["referencia"] = ref
    data["fecha"] = datetime.now().isoformat()
    path = os.path.join(SALIDAS_DIR, f"{ref}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # Intentar descuento de stock en Stel Order (no bloquea si falla)
    stel_resultado = []
    try:
        items_list = data.get("items", [])
        if items_list:
            stel_resultado = _descontar_stock_stel(items_list, ref)
    except Exception as e:
        stel_resultado = [{"status": "error_general", "error": str(e)}]

    stel_ok    = all(r.get("status") == "ok" for r in stel_resultado) if stel_resultado else None
    stel_msg   = ("Stock descontado en Stel Order ✓" if stel_ok
                  else "Sin conexión a Stel Order (SAL guardada localmente)" if stel_resultado
                  else "")

    return jsonify({
        "ok":           True,
        "referencia":   ref,
        "stel_stock":   stel_resultado,
        "stel_ok":      stel_ok,
        "stel_msg":     stel_msg,
    })


@app.route("/api/get-salida/<ref>", methods=["GET"])
def get_salida(ref):
    path = os.path.join(SALIDAS_DIR, f"{ref}.json")
    if not os.path.exists(path):
        return jsonify({"found": False}), 200
    try:
        with open(path, encoding="utf-8") as f:
            salida = json.load(f)
        return jsonify({"found": True, "salida": salida})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/lista-salidas", methods=["GET"])
def lista_salidas():
    try:
        files = sorted(glob.glob(os.path.join(SALIDAS_DIR, "SAL-*.json")), reverse=True)
        salidas = []
        for fp in files[:100]:
            try:
                with open(fp, encoding="utf-8") as f:
                    d = json.load(f)
                salidas.append({
                    "referencia":  d.get("referencia", os.path.basename(fp).replace(".json","")),
                    "fecha":       d.get("fecha", ""),
                    "presupuesto": d.get("presupuesto", ""),
                    "tecnico":     d.get("tecnico", ""),
                    "items":       len(d.get("items", [])),
                    "nomcom":      d.get("nomcom", ""),
                    "poblacion":   d.get("poblacion", ""),
                })
            except Exception:
                pass
        return jsonify({"salidas": salidas})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Endpoints: revisión ────────────────────────────────────────────────────────

@app.route("/api/partes-pendientes", methods=["GET"])
def partes_pendientes():
    try:
        files = sorted(glob.glob(os.path.join(PARTES_DIR, "PT-*.json")), reverse=True)
        partes = []
        for fp in files[:200]:
            try:
                with open(fp, encoding="utf-8") as f:
                    d = json.load(f)
                partes.append({
                    "referencia":  d.get("referencia", ""),
                    "fecha":       d.get("fecha", ""),
                    "tecnico":     d.get("tecnico", ""),
                    "nomcom":      d.get("nomcom", ""),
                    "aviso":       d.get("aviso", ""),
                    "cliente":     d.get("cliente", ""),
                    "estado":      d.get("estado", "pendiente"),
                    "presupuesto": d.get("presupuesto", ""),
                    "sal_ref":     d.get("sal_ref", ""),
                    "n_items":     len(d.get("material", [])),
                    "wo_ref":      d.get("wo_ref", ""),
                    "direccion":   d.get("direccion", ""),
                    "poblacion":   d.get("poblacion", ""),
                })
            except Exception:
                pass
        return jsonify({"partes": partes})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/parte/<ref>", methods=["GET"])
def get_parte(ref):
    path = os.path.join(PARTES_DIR, f"{ref}.json")
    if not os.path.exists(path):
        return jsonify({"found": False}), 200
    try:
        with open(path, encoding="utf-8") as f:
            parte = json.load(f)

        # Obtener lineas de presupuesto desde Stel Order para comparación
        pres_ref = parte.get("presupuesto", "").strip().upper()
        presupuesto_items = []
        if pres_ref:
            try:
                rp = requests.get(f"{STEL_BASE_URL}/app/workEstimates",
                                  headers=HEADERS, params={"limit": 200}, timeout=15)
                if rp.status_code == 200:
                    est_list = _lista(rp.json(), "data","items","workEstimates")
                    doc = next((i for i in est_list if
                                (i.get("full-reference") or i.get("reference","")).upper() == pres_ref), None)
                    if doc and doc.get("id"):
                        rl = requests.get(f"{STEL_BASE_URL}/app/workEstimates/{doc['id']}/lines",
                                          headers=HEADERS, timeout=10)
                        if rl.status_code == 200:
                            for ln in _lista(rl.json(), "data","items","lines"):
                                presupuesto_items.append({
                                    "item-id": ln.get("product-id") or ln.get("id"),
                                    "ref":     ln.get("reference") or ln.get("product-reference",""),
                                    "nombre":  ln.get("description") or ln.get("name",""),
                                    "cantidad": ln.get("quantity", 1),
                                })
            except Exception as e:
                print(f"[PRESUP] Error: {e}")

        parte["presupuesto_items"] = presupuesto_items
        return jsonify({"found": True, "parte": parte})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/aprobar-parte/<ref>", methods=["POST"])
def aprobar_parte(ref):
    path = os.path.join(PARTES_DIR, f"{ref}.json")
    if not os.path.exists(path):
        return jsonify({"error": "Parte no encontrado"}), 404
    try:
        with open(path, encoding="utf-8") as f:
            parte = json.load(f)

        # Obtener items de presupuesto para el libro
        pres_ref = parte.get("presupuesto", "").strip().upper()
        presupuesto_items = []
        if pres_ref:
            try:
                rp = requests.get(f"{STEL_BASE_URL}/app/workEstimates",
                                  headers=HEADERS, params={"limit": 200}, timeout=15)
                if rp.status_code == 200:
                    est_list = _lista(rp.json(), "data","items","workEstimates")
                    doc = next((i for i in est_list if
                                (i.get("full-reference") or i.get("reference","")).upper() == pres_ref), None)
                    if doc and doc.get("id"):
                        rl = requests.get(f"{STEL_BASE_URL}/app/workEstimates/{doc['id']}/lines",
                                          headers=HEADERS, timeout=10)
                        if rl.status_code == 200:
                            for ln in _lista(rl.json(), "data","items","lines"):
                                presupuesto_items.append({
                                    "item-id": ln.get("product-id") or ln.get("id"),
                                    "ref":     ln.get("reference") or ln.get("product-reference",""),
                                    "nombre":  ln.get("description") or ln.get("name",""),
                                    "cantidad": ln.get("quantity", 1),
                                })
            except Exception as e:
                print(f"[PRESUP] Error al aprobar: {e}")

        parte["presupuesto_items"] = presupuesto_items
        parte["estado"]            = "aprobado"
        parte["fecha_aprobacion"]  = datetime.now().isoformat()

        # Generar libro PDF
        from weasyprint import HTML
        libro_html  = _html_libro_revision(parte)
        libro_bytes = HTML(string=libro_html).write_pdf()
        libro_path  = os.path.join(PARTES_DIR, f"LIBRO_{ref}.pdf")
        with open(libro_path, "wb") as lf:
            lf.write(libro_bytes)

        # Subir a file.io y adjuntar
        libro_url = _subir_file_io(libro_bytes, f"LIBRO_{ref}.pdf")
        if libro_url and parte.get("wo_id"):
            _adjuntar_a_parte(parte["wo_id"], libro_url)

        # Guardar parte actualizado
        with open(path, "w", encoding="utf-8") as f:
            json.dump(parte, f, ensure_ascii=False, indent=2)

        return jsonify({
            "ok":        True,
            "libro_url": libro_url,
            "libro_local": libro_path,
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


def _html_firma_fotos(parte):
    """Genera HTML con firmas (cliente + técnico) y fotos para el libro PDF."""
    html = ""

    # Soporte nuevo formato (firma_cliente / firma_tecnico) y legado (firma)
    firma_cli = parte.get("firma_cliente") or {}
    firma_tec = parte.get("firma_tecnico") or {}
    firma_legacy = parte.get("firma")  # compatibilidad partes anteriores

    img_cli    = firma_cli.get("img")    if isinstance(firma_cli, dict) else None
    nombre_cli = firma_cli.get("nombre", "") if isinstance(firma_cli, dict) else ""
    img_tec    = firma_tec.get("img")    if isinstance(firma_tec, dict) else None
    nombre_tec = firma_tec.get("nombre", "") if isinstance(firma_tec, dict) else ""

    tiene_firma = img_cli or img_tec or firma_legacy

    if tiene_firma:
        html += "<div class='sec'>FIRMAS</div>"
        html += "<div style='display:flex;gap:20px;padding:10px 18px;flex-wrap:wrap;'>"

        if img_cli or firma_legacy:
            src = img_cli or firma_legacy
            lbl = nombre_cli or "Cliente"
            html += (
                "<div style='text-align:center;'>"
                f"<img src='{src}' style='width:280px;max-height:90px;object-fit:contain;"
                "border:1px solid #ccc;border-radius:4px;display:block;'>"
                f"<div style='font-size:10px;color:#555;margin-top:4px;font-weight:600;'>{lbl}</div>"
                "</div>"
            )

        if img_tec:
            html += (
                "<div style='text-align:center;'>"
                f"<img src='{img_tec}' style='width:280px;max-height:90px;object-fit:contain;"
                "border:1px solid #ccc;border-radius:4px;background:#f4f7ff;display:block;'>"
                f"<div style='font-size:10px;color:#1a3a6b;margin-top:4px;font-weight:600;'>{nombre_tec or 'Técnico'}</div>"
                "</div>"
            )

        html += "</div>"

    fotos = parte.get("fotos", [])
    if fotos:
        fotos_html = "".join(
            f"<div style='display:inline-block;margin:4px;'>"
            f"<img src='{f}' style='width:180px;height:135px;object-fit:cover;"
            "border-radius:4px;border:1px solid #ddd;' alt='Foto instalación'>"
            "</div>"
            for f in fotos[:8]
        )
        html += (
            "<div class='sec'>FOTOS DE LA INSTALACI&Oacute;N</div>"
            f"<div style='padding:10px 18px;'>{fotos_html}</div>"
        )

    return html


@app.route("/api/descargar-libro-multiple", methods=["POST"])
def descargar_libro_multiple():
    """Combina múltiples libros PDF en uno solo y lo devuelve."""
    data = request.get_json() or {}
    refs = data.get("refs", [])
    if not refs:
        return jsonify({"error": "Sin referencias"}), 400
    try:
        import io
        from pypdf import PdfWriter
        writer = PdfWriter()
        encontrados = 0
        for ref in refs:
            libro_path = os.path.join(PARTES_DIR, f"LIBRO_{ref}.pdf")
            if os.path.exists(libro_path):
                from pypdf import PdfReader
                reader = PdfReader(libro_path)
                for page in reader.pages:
                    writer.add_page(page)
                encontrados += 1
        if not encontrados:
            return jsonify({"error": "No se encontraron libros aprobados para las referencias dadas"}), 404
        buf = io.BytesIO()
        writer.write(buf)
        buf.seek(0)
        from flask import send_file
        return send_file(buf, mimetype="application/pdf",
                         as_attachment=True,
                         download_name=f"partes_{__import__('datetime').date.today()}.pdf")
    except ImportError:
        return jsonify({"error": "Librería pypdf no disponible"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/descargar-libro/<ref>", methods=["GET"])
def descargar_libro(ref):
    libro_path = os.path.join(PARTES_DIR, f"LIBRO_{ref}.pdf")
    if not os.path.exists(libro_path):
        return jsonify({"error": "Libro no encontrado. Aprueba el parte primero."}), 404
    from flask import send_file
    return send_file(libro_path, mimetype="application/pdf",
                     download_name=f"LIBRO_{ref}.pdf", as_attachment=True)



# ── Libro de mantenimiento HTML ────────────────────────────────────────────────

def _html_libro_revision(parte):
    material      = parte.get("material", [])
    pres_items    = parte.get("presupuesto_items", [])
    ref           = parte.get("referencia", "")
    fecha_apro    = parte.get("fecha_aprobacion", datetime.now().isoformat())
    try:
        dt_apro = datetime.fromisoformat(fecha_apro).strftime("%d/%m/%Y %H:%M")
    except Exception:
        dt_apro = fecha_apro

    def v(key, default=""):
        val = parte.get(key, default)
        return str(val).strip() if val else default

    # Construir mapa de lo instalado por item-id y por ref
    inst_map_id  = {}
    inst_map_ref = {}
    extras = []
    for item in material:
        if item.get("devuelto"): continue
        iid = item.get("item-id") or item.get("item_id")
        if iid:
            inst_map_id[str(iid)] = item
        ref_item = (item.get("ref") or "").upper()
        if ref_item:
            inst_map_ref[ref_item] = item

    # Construir filas de comparación
    filas_html   = ""
    pres_ids_usados = set()
    color_ok     = "#ffffff"
    color_dev    = "#ffe0e0"
    color_furgo  = "#e0eeff"
    color_extra  = "#fffbe0"
    color_noinst = "#ffe0e0"

    row_num = 0

    # 1. Recorrer instalados marcando extras
    for item in material:
        row_num += 1
        iid      = str(item.get("item-id") or item.get("item_id") or "")
        ref_item = (item.get("ref") or "").upper()
        devuelto = item.get("devuelto", False)
        furgo    = item.get("furgoneta", False)

        # Buscar en presupuesto
        pres_match = None
        if iid and iid in {str(p.get("item-id","")) for p in pres_items}:
            pres_match = next((p for p in pres_items if str(p.get("item-id","")) == iid), None)
        elif ref_item:
            pres_match = next((p for p in pres_items if (p.get("ref") or "").upper() == ref_item), None)

        if pres_match:
            pres_ids_usados.add(str(pres_match.get("item-id","")))

        if devuelto:
            bg = color_dev; estado_txt = "DEVUELTO"
        elif furgo:
            bg = color_furgo; estado_txt = "FURGONETA"
        elif not pres_match:
            bg = color_extra; estado_txt = "EXTRA"
        else:
            bg = color_ok; estado_txt = "✓ OK"

        cant_pres = pres_match.get("cantidad", "-") if pres_match else "-"
        filas_html += (
            f"<tr style='background:{bg}'>"
            f"<td style='text-align:center'>{row_num}</td>"
            f"<td>{item.get('ref','')}</td>"
            f"<td>{item.get('desc','') or item.get('nombre','')}</td>"
            f"<td style='text-align:center'>{cant_pres}</td>"
            f"<td>{item.get('serie','')}</td>"
            f"<td>{item.get('ip','')}</td>"
            f"<td>{item.get('ubic','')}</td>"
            f"<td style='text-align:center;font-weight:bold'>{estado_txt}</td>"
            f"</tr>"
        )

    # 2. Items presupuestados NO instalados
    for p in pres_items:
        pid = str(p.get("item-id",""))
        if pid in pres_ids_usados: continue
        ref_p = (p.get("ref") or "").upper()
        if ref_p in inst_map_ref: continue
        row_num += 1
        filas_html += (
            f"<tr style='background:{color_noinst}'>"
            f"<td style='text-align:center'>{row_num}</td>"
            f"<td>{p.get('ref','')}</td>"
            f"<td>{p.get('nombre','')}</td>"
            f"<td style='text-align:center'>{p.get('cantidad','-')}</td>"
            f"<td colspan='3' style='color:#999;font-style:italic'>No instalado</td>"
            f"<td style='text-align:center;font-weight:bold;color:#c00'>&#10060; NO INST.</td>"
            f"</tr>"
        )

    if not filas_html:
        filas_html = "<tr><td colspan='8' style='text-align:center;color:#999'>Sin material registrado</td></tr>"

    return (
        "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'><style>"
        "* {box-sizing:border-box;margin:0;padding:0;}"
        "body {font-family:Arial,sans-serif;font-size:10pt;color:#222;background:#fff;}"
        ".hdr {background:#1a3a6b;color:white;padding:14px 20px;display:flex;justify-content:space-between;align-items:center;}"
        ".hdr h1 {font-size:15pt;font-weight:bold;}"
        ".hdr .meta {text-align:right;font-size:8pt;line-height:1.8;opacity:.9;}"
        ".banner {background:#1A5C2A;color:white;text-align:center;padding:7px;font-size:10pt;font-weight:bold;letter-spacing:.5px;}"
        ".sec {background:#1a3a6b;color:white;font-size:8pt;font-weight:bold;padding:3px 8px;margin:10px 18px 4px;}"
        ".grid {display:grid;gap:4px;margin:0 18px 4px;}"
        ".g2 {grid-template-columns:1fr 1fr;} .g3 {grid-template-columns:1fr 1fr 1fr;}"
        ".field {border:1px solid #ccc;padding:3px 7px;min-height:24px;}"
        ".lbl {font-size:7pt;color:#777;display:block;} .val {font-size:10pt;font-weight:600;}"
        "table {width:100%;border-collapse:collapse;font-size:8.5pt;margin:0 0 0 0;}"
        "thead th {background:#1a3a6b;color:white;padding:5px 6px;text-align:left;}"
        "tbody td {border:1px solid #ddd;padding:3px 6px;}"
        ".leyenda {display:flex;gap:12px;margin:6px 18px;font-size:7.5pt;}"
        ".ley-item {display:flex;align-items:center;gap:4px;}"
        ".ley-box {width:14px;height:14px;border:1px solid #ccc;display:inline-block;}"
        ".obs {border:1px solid #ccc;padding:6px;min-height:36px;font-size:9.5pt;margin:0 18px;}"
        ".footer {margin:14px 18px 10px;padding-top:6px;border-top:1px solid #ddd;"
        "font-size:7.5pt;color:#888;display:flex;justify-content:space-between;}"
        "</style></head><body>"
        f"<div class='hdr'><h1>SETEL Seguridad &mdash; Libro de Mantenimiento</h1>"
        f"<div class='meta'><div>Parte: <strong>{ref}</strong></div>"
        f"<div>Contrato: {v('presupuesto')}</div>"
        f"<div>Aprobado: {dt_apro}</div></div></div>"
        "<div class='banner'>&#x2705; REVISADO Y APROBADO POR OFICINA</div>"
        "<div class='sec'>DATOS DEL CLIENTE</div>"
        f"<div class='grid g2'>"
        f"<div class='field'><span class='lbl'>RAZ&Oacute;N SOCIAL</span><span class='val'>{v('nomcom')}</span></div>"
        f"<div class='field'><span class='lbl'>N&ordm; CLIENTE</span><span class='val'>{v('cliente') or v('cliente_id')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>DIRECCI&Oacute;N</span><span class='val'>{v('direccion')}</span></div>"
        f"<div class='field'><span class='lbl'>POBLACI&Oacute;N</span><span class='val'>{v('poblacion')}</span></div>"
        f"<div class='field'><span class='lbl'>C.P.</span><span class='val'>{v('cp')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>TEL&Eacute;FONO</span><span class='val'>{v('tlfno')}</span></div>"
        f"<div class='field'><span class='lbl'>T&Eacute;CNICO</span><span class='val'>{v('tecnico')}</span></div>"
        f"<div class='field'><span class='lbl'>AVISO / CONTRATO</span><span class='val'>{v('aviso')} / {v('presupuesto') or v('contrato')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>VIA / VIDEO</span><span class='val'>{v('via')} / {v('video')}</span></div>"
        f"<div class='field'><span class='lbl'>IP / CAM IP</span><span class='val'>{v('ip')} / {v('camip')}</span></div>"
        f"<div class='field'><span class='lbl'>PUERTO / P2P</span><span class='val'>{v('puerto')} / {v('p2p')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>CLAVE ADMIN</span><span class='val'>{v('adm') or v('adm1')}</span></div>"
        f"<div class='field'><span class='lbl'>USUARIO</span><span class='val'>{v('usr')}</span></div>"
        f"<div class='field'><span class='lbl'>D&Iacute;AS GRABACI&Oacute;N</span><span class='val'>{v('dias')}</span></div></div>"
        "<div class='sec'>MATERIAL INSTALADO &mdash; COMPARATIVA CON PRESUPUESTO</div>"
        "<div class='leyenda'>"
        "<div class='ley-item'><div class='ley-box' style='background:#fff'></div> OK</div>"
        "<div class='ley-item'><div class='ley-box' style='background:#ffe0e0'></div> Devuelto / No inst.</div>"
        "<div class='ley-item'><div class='ley-box' style='background:#e0eeff'></div> En furgoneta</div>"
        "<div class='ley-item'><div class='ley-box' style='background:#fffbe0'></div> Extra (no presup.)</div>"
        "</div>"
        "<div style='margin:0 18px;'><table><thead><tr>"
        "<th style='width:28px'>#</th><th style='width:90px'>REF</th>"
        "<th>DESCRIPCI&Oacute;N</th><th style='width:55px;text-align:center'>PRESUP.</th>"
        "<th style='width:100px'>N&ordm; SERIE</th><th style='width:75px'>IP</th>"
        "<th>UBICACI&Oacute;N</th><th style='width:70px;text-align:center'>ESTADO</th>"
        f"</tr></thead><tbody>{filas_html}</tbody></table></div>"
        "<div class='sec'>OBSERVACIONES</div>"
        f"<div class='obs'>{v('obs')}</div>"
        + _html_firma_fotos(parte)
        + f"<div class='footer'>"
        "<span>SETEL Seguridad &mdash; T&eacute;cnicos de Servicios M&uacute;ltiples S.L. &mdash; Salamanca</span>"
        f"<span>Libro generado: {dt_apro}</span></div>"
        "</body></html>"
    )


@app.route("/api/debug-producto", methods=["GET"])
def debug_producto():
    """Diagnóstico: muestra los campos exactos que devuelve Stel Order para un producto."""
    barcode = request.args.get("barcode", "").strip()
    if not barcode:
        return "<h3>Uso: /api/debug-producto?barcode=REFERENCIA</h3><p>Pon la referencia de un producto que exista en Stel Order.</p>", 200
    try:
        rows = ""
        for param_name, param_val in [("barcode", barcode), ("reference", barcode), ("name", barcode)]:
            r = requests.get(f"{STEL_BASE_URL}/app/products",
                             headers=HEADERS,
                             params={param_name: param_val, "limit": 3},
                             timeout=10)
            rows += f"<tr><td><b>{param_name}={param_val}</b></td><td>HTTP {r.status_code}</td>"
            if r.status_code == 200:
                try:
                    data = r.json()
                    from flask import json as fjson
                    rows += f"<td><pre style='font-size:11px'>{fjson.dumps(data, ensure_ascii=False, indent=2)[:3000]}</pre></td>"
                except Exception as e:
                    rows += f"<td>Error JSON: {e}</td>"
            else:
                rows += f"<td>{r.text[:300]}</td>"
            rows += "</tr>"
        return f"""<html><body style='font-family:monospace;padding:20px'>
        <h2>Debug producto: {barcode}</h2>
        <table border=1 cellpadding=6 style='border-collapse:collapse;width:100%'>
        <tr><th>Parámetro</th><th>Status</th><th>Respuesta</th></tr>
        {rows}
        </table></body></html>""", 200
    except Exception as e:
        return f"<h3>Error: {e}</h3>", 500


# ── Inicio ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser, threading
    print("=" * 60)
    print("  SETEL Seguridad — Servidor local")
    print(f"  Ficha CCTV : http://localhost:5000/ficha")
    print(f"  Almacen    : http://localhost:5000/almacen")
    print(f"  Revision   : http://localhost:5000/revision")
    print("=" * 60)
    def abrir():
        import time; time.sleep(1.2)
        webbrowser.open("http://localhost:5000/ficha")
    threading.Thread(target=abrir, daemon=True).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
