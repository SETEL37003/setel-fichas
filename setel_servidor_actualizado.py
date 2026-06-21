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
SALIDAS_DIR  = os.path.join(BASE_DIR, "salidas")
PARTES_DIR   = os.path.join(BASE_DIR, "partes")
os.makedirs(SALIDAS_DIR, exist_ok=True)
os.makedirs(PARTES_DIR,  exist_ok=True)


def _lista(data, *claves):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in claves:
            if k in data and isinstance(data[k], list):
                return data[k]
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
        r = requests.get(f"{STEL_BASE_URL}/app/products",
                         headers=HEADERS,
                         params={"barcode": barcode, "limit": 5},
                         timeout=10)
        items = _lista(r.json(), "data", "products", "items")
        if not items:
            r2 = requests.get(f"{STEL_BASE_URL}/app/products",
                              headers=HEADERS,
                              params={"reference": barcode, "limit": 5},
                              timeout=10)
            items = _lista(r2.json(), "data", "products", "items")
        if items:
            p = items[0]
            nombre     = p.get("name") or p.get("description") or ""
            referencia = p.get("reference") or p.get("barcode") or barcode
            return jsonify({"found": True, "nombre": nombre, "referencia": referencia,
                            "item_id": p.get("id"), "producto": p})
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
            r = requests.get(f"{STEL_BASE_URL}/app/clients",
                             headers=HEADERS,
                             params={"limit": 200, "sort": "name", "order": "asc"},
                             timeout=10)
            if r.status_code == 200:
                items = _lista(r.json(), "data", "clients", "items")
                nombre_lower = nombre.lower()
                clientes = [
                    c for c in items
                    if nombre_lower in (c.get("name") or "").lower()
                    or nombre_lower in (c.get("legal-name") or "").lower()
                ][:15]
        resultado = []
        for c in clientes[:15]:
            addr = c.get("main-address") or {}
            num_cli = (c.get("referencia") or c.get("reference") or
                       c.get("client-number") or str(c.get("id", "")))
            resultado.append({
                "id":      str(c.get("id", "")),
                "num_cli": num_cli,
                "nombre":  c.get("legal-name") or c.get("name") or "",
                "dir":     addr.get("address-data") or addr.get("formatted-address") or "",
                "pobl":    addr.get("city-town") or addr.get("city") or "",
                "cp":      addr.get("postal-code") or "",
                "tlfno":   c.get("phone") or c.get("phone2") or "",
                "email":   c.get("email") or "",
            })
        return jsonify({"clientes": resultado})
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Sin conexion a Stel Order"}), 503
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
        f"<div class='meta'><div>Parte: <strong>{v('contrato')}</strong></div>"
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
        f"<div class='field'><span class='lbl'>CLAVE ADMIN</span><span class='val'>{v('adm1')}</span></div>"
        f"<div class='field'><span class='lbl'>CABLE</span><span class='val'>{v('cable')}</span></div></div>"
        "<div class='sec'>MATERIAL INSTALADO</div>"
        "<div style='margin:0 18px;'><table><thead><tr>"
        "<th style='width:28px'>#</th><th style='width:100px'>REFERENCIA</th>"
        "<th>DESCRIPCI&Oacute;N</th><th style='width:110px'>N&ordm; SERIE</th>"
        "<th style='width:80px'>IP</th><th>UBICACI&Oacute;N</th>"
        f"</tr></thead><tbody>{filas_mat}</tbody></table></div>"
        "<div class='sec'>OBSERVACIONES</div>"
        f"<div class='obs'>{v('obs')}</div>"
        f"<div class='footer'>"
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
    parte_local = {
        "referencia":  parte_ref_local,
        "fecha":       datetime.now().isoformat(),
        "estado":      "pendiente",
        "sal_ref":     data.get("sal_ref", ""),
        "presupuesto": data.get("contrato", ""),
        "tecnico":     tecnico,
        "nomcom":      data.get("nomcom") or data.get("nombre") or "",
        "cliente_id":  "",
        "direccion":   data.get("direccion") or data.get("dir") or "",
        "poblacion":   data.get("poblacion") or data.get("pobl") or "",
        "cp":          data.get("cp", ""),
        "tlfno":       data.get("tlfno", ""),
        "obs":         data.get("obs", ""),
        "adm1":        data.get("adm1", ""),
        "cable":       data.get("cable", ""),
        "material":    material,
        "wo_id":       None,
        "wo_ref":      None,
    }

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
    path = os.path.join(SALIDAS_DIR, f"{ref}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, "referencia": ref})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
                    "referencia": d.get("referencia", os.path.basename(fp).replace(".json","")),
                    "fecha":      d.get("fecha", ""),
                    "presupuesto": d.get("presupuesto", ""),
                    "tecnico":    d.get("tecnico", ""),
                    "items":      len(d.get("items", [])),
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
                    "estado":      d.get("estado", "pendiente"),
                    "presupuesto": d.get("presupuesto", ""),
                    "sal_ref":     d.get("sal_ref", ""),
                    "n_items":     len(d.get("material", [])),
                    "wo_ref":      d.get("wo_ref", ""),
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
        f"<div class='field'><span class='lbl'>N&ordm; CLIENTE</span><span class='val'>{v('cliente_id')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>DIRECCI&Oacute;N</span><span class='val'>{v('direccion')}</span></div>"
        f"<div class='field'><span class='lbl'>POBLACI&Oacute;N</span><span class='val'>{v('poblacion')}</span></div>"
        f"<div class='field'><span class='lbl'>C.P.</span><span class='val'>{v('cp')}</span></div></div>"
        f"<div class='grid g3'>"
        f"<div class='field'><span class='lbl'>TEL&Eacute;FONO</span><span class='val'>{v('tlfno')}</span></div>"
        f"<div class='field'><span class='lbl'>T&Eacute;CNICO</span><span class='val'>{v('tecnico')}</span></div>"
        f"<div class='field'><span class='lbl'>CLAVE ADMIN</span><span class='val'>{v('adm1')}</span></div></div>"
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
        f"<div class='footer'>"
        "<span>SETEL Seguridad &mdash; T&eacute;cnicos de Servicios M&uacute;ltiples S.L. &mdash; Salamanca</span>"
        f"<span>Libro generado: {dt_apro}</span></div>"
        "</body></html>"
    )


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
