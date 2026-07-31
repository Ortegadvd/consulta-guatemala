"""
app.py — Consulta Crediticia Guatemala
App Flask para consultar el análisis crediticio desde celular.
"""

from flask import Flask, render_template, request, jsonify
import json
from datetime import datetime
import pymysql
from dateutil.relativedelta import relativedelta

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Conexión MySQL
# ---------------------------------------------------------------------------

DB_CONFIG = {
    "host":    "maxi-prod-instance-1.csa4gsaishoe.us-east-1.rds.amazonaws.com",
    "user":    "dovoedo.ortega",
    "passwd":  "aWg!MbJ?0oTO$LIavtkutWtt",
    "db":      "buro-credito-prod",
    "port":    3306,
    "charset": "utf8mb4",
    "connect_timeout": 30,
}

# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

QUERY = """
WITH
flujos AS (
  SELECT f.id, f.estatus, f.pedirNip, f.aprobado, f.mensaje, f.reglasAplicadas
  FROM Flujo f
),
formulario_ult AS (
  SELECT * FROM (
    SELECT fc.*,
      ROW_NUMBER() OVER (
        PARTITION BY fc.idFlujo
        ORDER BY COALESCE(fc.ts_alta_audit, '1900-01-01 00:00:00') DESC, fc.id DESC
      ) AS rn
    FROM FormularioCaptura fc
  ) x WHERE rn = 1
),
konan_ult AS (
  SELECT * FROM (
    SELECT bk.*,
      ROW_NUMBER() OVER (
        PARTITION BY bk.idFlujo
        ORDER BY COALESCE(bk.fechaHoraConsulta, '1900-01-01 00:00:00') DESC, bk.id DESC
      ) AS rn
    FROM bitacora_consulta_konan bk
  ) x WHERE rn = 1
),
buro_clasificada AS (
  SELECT cb.*,
    CASE
      WHEN TRIM(CAST(cb.tipoDocumento AS CHAR)) = '11'  THEN 'Buro_11_historial'
      WHEN TRIM(CAST(cb.tipoDocumento AS CHAR)) = '164' THEN 'Buro_164_localizador'
      ELSE 'Buro_otro'
    END AS categoria_buro
  FROM ConsultaBuro cb
),
buro_ranked AS (
  SELECT bc.*,
    ROW_NUMBER() OVER (
      PARTITION BY bc.idFlujo, bc.categoria_buro
      ORDER BY COALESCE(bc.fechaHoraConsulta, '1900-01-01 00:00:00') DESC, bc.id DESC
    ) AS rn
  FROM buro_clasificada bc
),
buro_pivot AS (
  SELECT
    br.idFlujo,
    MAX(CASE WHEN br.categoria_buro = 'Buro_11_historial'    AND br.rn = 1 THEN br.responseBuro    END) AS buro11_responseBuro,
    MAX(CASE WHEN br.categoria_buro = 'Buro_11_historial'    AND br.rn = 1 THEN br.consultaExitosa END) AS buro11_consultaExitosa,
    MAX(CASE WHEN br.categoria_buro = 'Buro_164_localizador' AND br.rn = 1 THEN br.responseBuro    END) AS buro164_responseBuro,
    MAX(CASE WHEN br.categoria_buro = 'Buro_164_localizador' AND br.rn = 1 THEN br.consultaExitosa END) AS buro164_consultaExitosa
  FROM buro_ranked br
  GROUP BY br.idFlujo
),
orig_via_unykoo AS (
  SELECT
    cb.idUnykoo AS buro_flujo_id,
    of2.fechaCreacion AS flujo_fechaCreacion,
    cb.fechaHora AS buro_fechaHora,
    CONCAT(usr.primer_nombre, IFNULL(CONCAT(' ', usr.segundo_nombre), ''), ' ', usr.apellido_paterno,
           IFNULL(CONCAT(' ', usr.apellido_materno), '')) AS nombre_usuario_creacion,
    suc.nombre  AS nombre_sucursal_consulta,
    dist.nombre AS nombre_distribuidor_consulta
  FROM `originador-dev`.consulta_buro cb
  JOIN `originador-dev`.originacion_consulta_buro ocb ON ocb.idConsultaBuro = cb.id
  JOIN `originador-dev`.originacion_flujo         of2 ON of2.id             = ocb.idOriginacionFlujo
  JOIN `maxi-prod`.usuario    usr  ON of2.fk_usuario_creacion = usr.pk_usuario
  JOIN `maxi-prod`.sucursal   suc  ON usr.fk_sucursal         = suc.pk_sucursal
  JOIN `maxi-prod`.distribuidor dist ON suc.fk_distribuidor   = dist.pk_distribuidor
  WHERE cb.idUnykoo IS NOT NULL
),
orig_via_dpi AS (
  SELECT * FROM (
    SELECT
      bfc.idFlujo AS buro_flujo_id,
      of2.fechaCreacion AS flujo_fechaCreacion,
      bu_d.fechaHora AS buro_fechaHora,
      CONCAT(usr.primer_nombre, IFNULL(CONCAT(' ', usr.segundo_nombre), ''), ' ', usr.apellido_paterno,
             IFNULL(CONCAT(' ', usr.apellido_materno), '')) AS nombre_usuario_creacion,
      suc.nombre  AS nombre_sucursal_consulta,
      dist.nombre AS nombre_distribuidor_consulta,
      ROW_NUMBER() OVER (
        PARTITION BY bfc.idFlujo
        ORDER BY ABS(TIMESTAMPDIFF(SECOND,
          COALESCE(bfc.ts_alta_audit, '1900-01-01'),
          COALESCE(ofc.fechaHora,     '1900-01-01')
        ))
      ) AS rn
    FROM `buro-credito-prod`.FormularioCaptura bfc
    JOIN `originador-dev`.originacion_formulario_captura ofc
         ON JSON_UNQUOTE(JSON_EXTRACT(ofc.formularioCapturaJson, '$.docIdent')) = bfc.dpi
    JOIN `originador-dev`.originacion_flujo of2
         ON of2.idOriginacionFormularioCaptura = ofc.id
         AND of2.fk_usuario_creacion IS NOT NULL
    LEFT JOIN `originador-dev`.originacion_consulta_buro ocb_d ON ocb_d.id = of2.idOriginacionConsultaBuro
    LEFT JOIN `originador-dev`.consulta_buro              bu_d ON bu_d.id  = ocb_d.idConsultaBuro
    JOIN `maxi-prod`.usuario    usr  ON of2.fk_usuario_creacion = usr.pk_usuario
    JOIN `maxi-prod`.sucursal   suc  ON usr.fk_sucursal         = suc.pk_sucursal
    JOIN `maxi-prod`.distribuidor dist ON suc.fk_distribuidor   = dist.pk_distribuidor
    WHERE bfc.idFlujo NOT IN (SELECT buro_flujo_id FROM orig_via_unykoo)
  ) x WHERE rn = 1
),
orig_info AS (
  SELECT buro_flujo_id, flujo_fechaCreacion, buro_fechaHora,
         nombre_usuario_creacion, nombre_sucursal_consulta, nombre_distribuidor_consulta
  FROM orig_via_unykoo
  UNION ALL
  SELECT buro_flujo_id, flujo_fechaCreacion, buro_fechaHora,
         nombre_usuario_creacion, nombre_sucursal_consulta, nombre_distribuidor_consulta
  FROM orig_via_dpi
)
SELECT
  f.id AS flujo_id,
  f.estatus AS flujo_estatus,
  COALESCE(f.mensaje, f.reglasAplicadas) AS flujo_dictamen,
  oi.flujo_fechaCreacion,
  oi.buro_fechaHora,
  oi.nombre_usuario_creacion,
  oi.nombre_sucursal_consulta,
  oi.nombre_distribuidor_consulta,
  fc.dpi AS formulario_dpi,
  CONCAT(fc.primerNombre, IFNULL(CONCAT(' ', fc.segundoNombre), ''), ' ', fc.apellidoPaterno,
         IFNULL(CONCAT(' ', fc.apellidoMaterno), '')) AS formulario_NombreCompleto,
  fc.fechaNacimiento AS formulario_fechaNacimiento,
  fc.json AS formulario_json,
  bp.buro11_responseBuro,
  bp.buro11_consultaExitosa,
  bp.buro164_responseBuro,
  bk.responseKonan AS konan_responseKonan,
  bk.reason AS konan_reason,
  CASE
    WHEN COALESCE(bp.buro11_consultaExitosa,0)>=1 AND COALESCE(bp.buro164_consultaExitosa,0)>=1 THEN 'OK_2_PRODUCTOS'
    WHEN COALESCE(bp.buro11_consultaExitosa,0)>=1 AND COALESCE(bp.buro164_consultaExitosa,0)=0  THEN 'FALTA_164'
    WHEN COALESCE(bp.buro11_consultaExitosa,0)=0  AND COALESCE(bp.buro164_consultaExitosa,0)>=1 THEN 'FALTA_11'
    ELSE 'SIN_BURO_CLASIFICADO'
  END AS diagnostico_productos_buro
FROM flujos f
LEFT JOIN formulario_ult fc ON fc.idFlujo = f.id
LEFT JOIN buro_pivot     bp ON bp.idFlujo = f.id
LEFT JOIN konan_ult      bk ON bk.idFlujo = f.id
LEFT JOIN orig_info      oi ON oi.buro_flujo_id = f.id
ORDER BY f.id DESC
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def safe_json(raw):
    if not raw:
        return {}
    try:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except:
        return {}

def parse_fecha(val):
    if not val:
        return None
    s = str(val).strip()[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            pass
    return None

def fmt_fecha(val):
    d = parse_fecha(val)
    return d.strftime("%d/%m/%Y") if d else "—"

def fmt_q(valor):
    if valor is None or valor == "":
        return "—"
    try:
        return f"Q{float(valor):,.2f}"
    except:
        return str(valor)

def calculate_age(fecha_nac, fecha_ref):
    if not fecha_nac or not fecha_ref:
        return None
    try:
        age = fecha_ref.year - fecha_nac.year
        if (fecha_ref.month, fecha_ref.day) < (fecha_nac.month, fecha_nac.day):
            age -= 1
        return age
    except:
        return None

def parse_razones(razones_raw):
    if not razones_raw or not isinstance(razones_raw, str):
        return []
    return [p.strip() for p in razones_raw.split("-") if p.strip()]

def score_nivel(score):
    try:
        s = int(score)
        if s >= 700:   return "excelente", "EXCELENTE"
        elif s >= 550: return "bueno", "BUENO"
        elif s >= 400: return "regular", "REGULAR"
        else:          return "riesgo", "ALTO RIESGO"
    except:
        return "sin-dato", "—"

def dias_mora_label(dias):
    if dias is None:
        return "—"
    try:
        d = int(dias)
        if d == 0:     return "Al día"
        elif d <= 59:  return f"{d} días (30-59)"
        elif d <= 89:  return f"{d} días (60-89)"
        elif d <= 119: return f"{d} días (90-119)"
        elif d <= 149: return f"{d} días (120-149)"
        elif d <= 179: return f"{d} días (150-179)"
        else:          return f"{d} días (180+)"
    except:
        return str(dias)

def mop_label(mop):
    labels = {0:"Al día",1:"30-59 días",2:"60-89 días",3:"90-119 días",
              4:"120-149 días",5:"150-179 días",6:"180+ días"}
    try:
        return labels.get(int(mop), str(mop))
    except:
        return str(mop)

# ---------------------------------------------------------------------------
# Procesamiento de datos
# ---------------------------------------------------------------------------

def procesar_registro(db):
    fj = safe_json(db.get("formulario_json"))

    # Dirección capturada
    partes = [str(fj.get(k) or "").strip() for k in ["numero","calle","colonia","zona"]]
    direccion = " ".join(p for p in partes if p)

    b11_raw = db.get("buro11_responseBuro")
    b11_data = safe_json(b11_raw)
    reporte = {}
    try:
        reporte = b11_data["ReporteResponse"]["ReporteResult"]["reporteCredito"]
    except:
        pass

    # Datos generales buró
    dg = reporte.get("datosGenerales", {}) or {}
    genero = (dg.get("genero") or {}).get("content")
    nombre_buro = dg.get("nombreCompleto")
    ec = dg.get("estadoCivil") or {}
    ESTADO_CIVIL_MAP = {"00":"No especificado","S":"Soltero","C":"Casado",
                        "D":"Divorciado","V":"Viudo","U":"Unión libre"}
    estado_civil = ec.get("content") or ESTADO_CIVIL_MAP.get(str(ec.get("codigo","")))

    # Fecha reporte
    fecha_reporte_dt = None
    fecha_reporte = hora_reporte = None
    try:
        fr = reporte["encabezado"]["fechaReporte"]["content"]
        fecha_reporte_dt = datetime.strptime(fr, "%Y-%m-%d %H:%M:%S")
        fecha_reporte = fecha_reporte_dt.strftime("%d/%m/%Y")
        hora_reporte  = fecha_reporte_dt.strftime("%H:%M:%S")
    except:
        pass

    # Localización buró
    municipio_buro = departamento_buro = direccion_buro = None
    try:
        dirs_tel = reporte.get("localizacion", {}).get("direccionYTelefono", [])
        if isinstance(dirs_tel, dict): dirs_tel = [dirs_tel]
        for dt in dirs_tel:
            if (dt.get("tipo") or {}).get("content") == "RESIDENCIAL":
                dir_obj = dt.get("direccion") or {}
                departamento_buro = (dir_obj.get("divisionGeografica1") or {}).get("content")
                municipio_buro    = (dir_obj.get("divisionGeografica2") or {}).get("content")
                direccion_buro    = dir_obj.get("desc")
                break
    except:
        pass

    # Score e ingreso
    score = razon1 = razon2 = ingreso = None
    try:
        modelos = reporte.get("modelosAnalisis", {}).get("modelo", [])
        if isinstance(modelos, dict): modelos = [modelos]
        for m in modelos:
            codigo = (m.get("producto") or {}).get("codigo")
            if codigo == 133:
                score = m.get("resultado")
                razones = parse_razones(m.get("razones",""))
                razon1 = razones[0] if len(razones) > 0 else None
                razon2 = razones[1] if len(razones) > 1 else None
            elif codigo == 222:
                ingreso = m.get("resultado")
    except:
        pass

    # MOPs
    mops = {f"mop{i}": 0 for i in range(1,7)}
    total_vectores = 0
    obligaciones_raw = []
    try:
        obs = reporte.get("comportamientoObligaciones", {}).get("obligacion", [])
        if isinstance(obs, dict): obs = [obs]
        obligaciones_raw = obs
        for ob in obs:
            comp = ob.get("comportamientoPago", {})
            comps = comp if isinstance(comp, list) else [comp]
            for cp in comps:
                if not cp or "vectorHistorico" not in cp: continue
                total_vectores += 1
                items = cp["vectorHistorico"].get("item", [])
                if isinstance(items, dict): items = [items]
                for it in items[:6]:
                    try:
                        v = int(it.get("content"))
                        if 1 <= v <= 6:
                            mops[f"mop{v}"] += 1
                    except:
                        pass
    except:
        pass

    # Consultas
    consultas = []
    total_consultas = 0
    try:
        craw = reporte.get("listaConsultas", {}).get("consulta", [])
        if isinstance(craw, dict): craw = [craw]
        if fecha_reporte_dt:
            fecha_limite = fecha_reporte_dt - relativedelta(months=1)
            filtradas = []
            for c in craw:
                try:
                    fdt = datetime.strptime(c.get("fecha",""), "%Y-%m-%d")
                    if fecha_limite <= fdt <= fecha_reporte_dt:
                        filtradas.append(c)
                except:
                    pass
            filtradas.sort(key=lambda x: x.get("fecha",""), reverse=True)
        else:
            filtradas = sorted(craw, key=lambda x: x.get("fecha",""), reverse=True)
        total_consultas = len(filtradas)
        consultas = filtradas[:12]
    except:
        pass

    # Cuentas
    cuentas = []
    for ob in obligaciones_raw:
        base = {
            "entidad":       (ob.get("entidadInformante") or {}).get("content"),
            "tipo":          (ob.get("tipo") or {}).get("content"),
            "sector":        ob.get("sector"),
            "garantia":      (ob.get("garantia") or {}).get("content"),
            "periodo":       (ob.get("periodoPago") or {}).get("content"),
            "apertura":      fmt_fecha(ob.get("fechaApertura")),
            "vencimiento":   fmt_fecha(ob.get("fecVencimiento")),
            "actualizacion": fmt_fecha(ob.get("fechaActualizacion")),
            "consecutivo":   ob.get("creditoConsecutivo"),
            "tipoObs":       ob.get("tipoObs") or "",
        }
        estatus = "Cerrada" if "Cerrada" in base["tipoObs"] else "Vigente"
        cp_raw = ob.get("comportamientoPago")
        comps  = cp_raw if isinstance(cp_raw, list) else ([cp_raw] if isinstance(cp_raw, dict) else [])
        for cp in comps:
            if not cp: continue
            vh    = cp.get("vectorHistorico") or {}
            items = vh.get("item") or []
            if isinstance(items, dict): items = [items]
            mop_actual = items[0].get("content") if items else None
            ultimo_mes = f"{items[0].get('mes','')}/{items[0].get('anio','')}" if items else None
            mop_counts = {f"mop{v}": 0 for v in range(7)}
            for it in items:
                try:
                    k = f"mop{int(it.get('content'))}"
                    if k in mop_counts: mop_counts[k] += 1
                except: pass

            # Vector histórico completo para sección 8
            vector_completo = []
            for it in items:
                vector_completo.append({
                    "mes":     it.get("mes"),
                    "anio":    it.get("anio"),
                    "content": it.get("content"),
                })

            dias_int = 0
            try: dias_int = int(cp.get("diasMora") or 0)
            except: pass

            if "CASTIGADA" in ((cp.get("estado") or {}).get("content","")).upper() or dias_int >= 180:
                mora_nivel = "critico"
            elif dias_int >= 90:
                mora_nivel = "alto"
            elif dias_int >= 30:
                mora_nivel = "moderado"
            else:
                mora_nivel = "ok"

            cuentas.append({
                **base,
                "estatus":        estatus,
                "estado":         (cp.get("estado") or {}).get("content",""),
                "moneda":         (cp.get("moneda") or {}).get("content"),
                "cuota":          fmt_q(cp.get("cuota")),
                "limite":         fmt_q(cp.get("limite")),
                "saldo_actual":   fmt_q(cp.get("saldoActual")),
                "saldo_mora":     fmt_q(cp.get("saldoMora")),
                "dias_mora":      dias_mora_label(cp.get("diasMora")),
                "mop_actual":     mop_label(mop_actual) if mop_actual is not None else "—",
                "ultimo_mes":     ultimo_mes or "—",
                "mora_nivel":     mora_nivel,
                "mop_resumen":    ", ".join(f"MOP{v}={mop_counts[f'mop{v}']}" for v in range(7) if mop_counts[f"mop{v}"] > 0),
                "vector_completo": vector_completo,
                **mop_counts,
            })

    vigentes = [c for c in cuentas if c["estatus"] == "Vigente"]
    cerradas  = [c for c in cuentas if c["estatus"] == "Cerrada"]

    # KONAN
    konan_raw = safe_json(db.get("konan_responseKonan"))
    if "resultado" in konan_raw:
        wo = konan_raw.get("resultado", {}).get("workflow_output", {})
    else:
        wo = konan_raw.get("workflow_output", {})
    calc = wo.get("calculated_features", {})
    output_label = wo.get("output_label")
    konan_reason = wo.get("reason") or db.get("konan_reason")
    reason_id    = (calc.get("show_reason_ID") or {}).get("reason_id")

    konan_tags_raw = calc.get("KONAN_TAGS", []) or []
    DECISION_ORDER = ["ID1","ID16","ID17","ID18","ID19","ID20","ID21",
                      "ID3","ID4","ID5","ID6","ID7","ID8","ID9","ID10","ID11","ID12"]
    def tag_id(t): return t.split(" ")[0].strip() if t else ""
    def drank(t):
        tid = tag_id(t)
        return DECISION_ORDER.index(tid) if tid in DECISION_ORDER else 999
    if isinstance(konan_tags_raw, list) and konan_tags_raw:
        winner_id = f"ID{reason_id}" if reason_id is not None else None
        winner    = next((t for t in konan_tags_raw if tag_id(t) == winner_id), None)
        rest      = sorted([t for t in konan_tags_raw if t != winner], key=drank)
        konan_tags = ([winner] if winner else []) + rest
    else:
        konan_tags = []

    # Resumen ejecutivo
    n_mora     = sum(1 for c in vigentes if c["mora_nivel"] != "ok")
    n_criticos = sum(1 for c in vigentes if c["mora_nivel"] == "critico")
    total_mora_val = 0.0
    total_saldo_val = 0.0
    for c in vigentes:
        try: total_mora_val  += float(str(c["saldo_mora"]).replace("Q","").replace(",","") or 0)
        except: pass
        try: total_saldo_val += float(str(c["saldo_actual"]).replace("Q","").replace(",","") or 0)
        except: pass

    output_aprobado = "aprobado" in (output_label or "").lower()
    score_invalido  = score is None
    if output_aprobado and score_invalido:
        recomendacion = ("amarillo", "APROBADO — Sin historial suficiente, evaluar manualmente")
    elif output_aprobado:
        if n_criticos > 0:
            recomendacion = ("naranja", "APROBADO por Konan — Cuentas críticas, revisar antes de desembolsar")
        elif n_mora > 0:
            recomendacion = ("naranja", "APROBADO por Konan — Mora activa, evaluar con cuidado")
        else:
            recomendacion = ("verde", "APROBADO ✓")
    else:
        if n_criticos > 0:
            recomendacion = ("rojo", "NO RECOMENDADO — Cuentas críticas activas")
        elif score and int(score or 999) < 400:
            recomendacion = ("rojo", "NO RECOMENDADO — Score bajo (menor a 400)")
        elif n_mora > 0:
            recomendacion = ("naranja", "PRECAUCIÓN — Mora activa")
        else:
            recomendacion = ("amarillo", "RECHAZADO por Konan")

    # Fechas y edad
    fecha_nac_dt  = parse_fecha(fj.get("fechaNacimiento") or db.get("formulario_fechaNacimiento"))
    fecha_buro_dt = parse_fecha(db.get("buro_fechaHora"))
    edad          = calculate_age(fecha_nac_dt, fecha_buro_dt)
    score_cls, score_txt = score_nivel(score)

    return {
        # Identidad
        "dpi":            str(fj.get("dpi") or db.get("formulario_dpi") or "—"),
        "nombre":         db.get("formulario_NombreCompleto") or nombre_buro or "—",
        "fecha_nac":      fmt_fecha(fj.get("fechaNacimiento") or db.get("formulario_fechaNacimiento")),
        "edad":           edad,
        "genero":         genero or "—",
        "estado_civil":   estado_civil or "—",
        "zona":           fj.get("zona") or "—",
        "colonia":        fj.get("colonia") or "—",
        "municipio":      fj.get("municipio") or "—",
        "departamento":   fj.get("departamento") or "—",
        "direccion":      direccion or "—",
        "fecha_reporte":  fecha_reporte or "—",
        "hora_reporte":   hora_reporte or "—",
        "sucursal":       db.get("nombre_sucursal_consulta") or "—",
        "distribuidor":   db.get("nombre_distribuidor_consulta") or "—",
        "usuario":        db.get("nombre_usuario_creacion") or "—",
        "diagnostico":    db.get("diagnostico_productos_buro") or "—",
        # Score
        "score":          score,
        "score_cls":      score_cls,
        "score_txt":      score_txt,
        "razon1":         razon1 or "—",
        "razon2":         razon2 or "—",
        "ingreso":        fmt_q(ingreso),
        "output_label":   output_label or "—",
        "konan_reason":   konan_reason or "—",
        "flujo_estatus":  db.get("flujo_estatus") or "—",
        "flujo_dictamen": db.get("flujo_dictamen") or "—",
        # MOPs
        "total_vectores": total_vectores,
        "mops":           mops,
        # Cuentas
        "vigentes":       vigentes,
        "cerradas":       cerradas,
        "total_mora":     fmt_q(total_mora_val),
        "total_saldo":    fmt_q(total_saldo_val),
        # Consultas
        "consultas":      consultas,
        "total_consultas": total_consultas,
        # KONAN
        "konan_tags":     konan_tags,
        "reason_id":      reason_id,
        # Resumen
        "n_vigentes":     len(vigentes),
        "n_mora":         n_mora,
        "n_criticos":     n_criticos,
        "n_cerradas":     len(cerradas),
        "mop6_global":    mops["mop6"],
        "n_konan":        len(konan_tags),
        "recomendacion":  recomendacion,
    }

# ---------------------------------------------------------------------------
# Rutas Flask
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/consultar", methods=["POST"])
def consultar():
    dpi = (request.json or {}).get("dpi", "").strip()
    if not dpi:
        return jsonify({"error": "DPI requerido"}), 400

    try:
        conn   = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute(QUERY)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        return jsonify({"error": f"Error de conexión: {str(e)}"}), 500

    encontrados = []
    for row in rows:
        fj = safe_json(row.get("formulario_json"))
        dpi_row = str(fj.get("dpi") or row.get("formulario_dpi") or "").strip()
        if dpi_row == dpi:
            encontrados.append(row)

    if not encontrados:
        return jsonify({"error": f"No se encontró ningún registro con DPI: {dpi}"}), 404

    # Priorizar flujo con OK_2_PRODUCTOS (tiene buro11 + buro164 completos)
    ok2 = [r for r in encontrados if r.get("diagnostico_productos_buro") == "OK_2_PRODUCTOS"]
    if ok2:
        registro = ok2[0]  # Query viene DESC, el primero es el más reciente
        aviso = None
    else:
        registro = encontrados[0]
        diagnosticos = list(set(r.get("diagnostico_productos_buro") for r in encontrados))
        aviso = f"No se encontró flujo con OK_2_PRODUCTOS. Diagnósticos disponibles: {', '.join(str(d) for d in diagnosticos)}. La información puede estar incompleta."

    try:
        resultado = procesar_registro(registro)
        if aviso:
            resultado["aviso"] = aviso
        return jsonify({"ok": True, "data": resultado})
    except Exception as e:
        return jsonify({"error": f"Error procesando datos: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
