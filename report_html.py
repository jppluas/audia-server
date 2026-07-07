"""
Audia — report_html.py
Fuente única de verdad del HTML del informe de evaluación.

tipo="clinico"        — informe completo para el especialista
tipo="representantes" — informe simplificado para padres/cuidadores

Secciones clínico:
  1. Identificación
  2. Anamnesis
  3. Resultado global
  4. Desempeño por fonema (con error predominante)
  5. Detalle por palabra (con tipo de error)
  6. Nota clínica

Secciones representantes:
  1. Identificación
  2. Anamnesis
  3. Resultado global
  4. Desempeño por fonema (solo nivel, sin error predominante)
  5. Detalle por palabra (sin tipo de error)
  6. Nota para representantes
"""

from __future__ import annotations


def generate_report_html(data: dict, tipo: str = "clinico") -> str:
    s               = data["session"]
    items           = data.get("items") or []
    phoneme_summary = data.get("phoneme_summary") or []
    report          = data.get("report") or {}

    # ── Helpers ──────────────────────────────────────────────────────────
    def gender_label(g):
        return {"F": "Femenino", "M": "Masculino"}.get(g, "Otro")

    def age_label(months):
        if not months:
            return "—"
        return f"{months // 12} años {months % 12} meses"

    def fmt(val):
        """Redondea a 2 decimales."""
        if val is None:
            return "—"
        try:
            return f"{float(val):.2f}"
        except (ValueError, TypeError):
            return str(val)

    def pffb_color(pffb):
        if pffb is None:
            return "#4A5568"
        return "#2A9D8F" if pffb > 75 else "#92600A" if pffb >= 50 else "#C0392B"

    def pffb_interp(pffb):
        if pffb is None:
            return "—"
        if pffb > 75:
            return "Sin acción inmediata. Seguimiento rutinario."
        if pffb >= 50:
            return "Monitoreo. Re-evaluar en 3 meses."
        return "Derivación a psicólogo o fonoaudiólogo recomendada."

    def result_color(result):
        if result == "correct":       return "#2A9D8F"
        if result == "not_evaluable": return "#A0AEC0"
        return "#C0392B"

    es_rep = (tipo == "representantes")

    # ── Sección 4: Desempeño por fonema ──────────────────────────────────
    phonemes_rows = ""
    for p in phoneme_summary:
        c = "#2A9D8F" if p["pff"] >= 75 else "#92600A" if p["pff"] >= 50 else "#C0392B"
        if es_rep:
            # Para padres: solo fonema y nivel
            phonemes_rows += f"""
        <tr>
          <td><strong>{_esc(p['phoneme'])}</strong></td>
          <td>{p['level']}</td>
        </tr>"""
        else:
            phonemes_rows += f"""
        <tr>
          <td><strong>{_esc(p['phoneme'])}</strong></td>
          <td style="color:{c}; font-weight:700;">{fmt(p['pff'])}%</td>
          <td>{p['level']}</td>
          <td>{p.get('error_predominant') or 'Ninguno'}</td>
        </tr>"""

    if phonemes_rows:
        if es_rep:
            phonemes_section = f"""
    <h2>4. Desempeño por fonema</h2>
    <table class="t">
      <thead><tr>
        <th>Fonema</th><th>Nivel</th>
      </tr></thead>
      <tbody>{phonemes_rows}</tbody>
    </table>"""
        else:
            phonemes_section = f"""
    <h2>4. Desempeño por fonema</h2>
    <table class="t">
      <thead><tr>
        <th>Fonema</th><th>PFF%</th><th>Nivel</th><th>Error predominante</th>
      </tr></thead>
      <tbody>{phonemes_rows}</tbody>
    </table>"""
    else:
        phonemes_section = ""

    # ── Sección 5: Detalle por palabra ────────────────────────────────────
    items_rows = ""
    for item in items:
        rc = result_color(item.get("result", ""))
        result_str = "Correcto" if item.get("result") == "correct" \
                else "No evaluable" if item.get("result") == "not_evaluable" \
                else "Error"
        if es_rep:
            # Para padres: sin columna tipo de error
            items_rows += f"""
        <tr>
          <td><strong>{_esc(item['word_expected'])}</strong>
              <span class="mono gray">{_esc(item['phoneme'])}</span></td>
          <td class="mono">{_esc(item.get('word_produced') or '—')}</td>
          <td style="color:{rc}; font-weight:600;">{result_str}</td>
        </tr>"""
        else:
            error_str = item.get("error_type") or ("—" if item.get("result") != "correct" else "")
            items_rows += f"""
        <tr>
          <td><strong>{_esc(item['word_expected'])}</strong>
              <span class="mono gray">{_esc(item['phoneme'])}</span></td>
          <td class="mono">{_esc(item.get('word_produced') or '—')}</td>
          <td style="color:{rc}; font-weight:600;">{result_str}</td>
          <td>{_esc(error_str)}</td>
        </tr>"""

    if items_rows:
        if es_rep:
            items_section = f"""
    <h2>5. Detalle por palabra</h2>
    <table class="t">
      <thead><tr>
        <th>Palabra esperada</th><th>Producción del niño</th><th>Resultado</th>
      </tr></thead>
      <tbody>{items_rows}</tbody>
    </table>"""
        else:
            items_section = f"""
    <h2>5. Detalle por palabra</h2>
    <table class="t">
      <thead><tr>
        <th>Palabra esperada</th><th>Producción del niño</th>
        <th>Resultado</th><th>Tipo de error</th>
      </tr></thead>
      <tbody>{items_rows}</tbody>
    </table>"""
    else:
        items_section = ""

    # ── Sección 6: Nota ───────────────────────────────────────────────────
    if es_rep:
        _texto = report.get("nota_representantes") or ""
        _parrafos = "".join(f"<p>{_esc(p)}</p>" for p in _texto.split("\n\n") if p.strip())
        nota_section = f"""
    <h2>6. Nota para representantes</h2>
    <div class="note">{_parrafos}</div>
    """ if _parrafos else ""
    else:
        _texto = report.get("nota_clinica") or ""
        _parrafos = "".join(f"<p>{_esc(p)}</p>" for p in _texto.split("\n\n") if p.strip())
        nota_section = f"""
    <h2>6. Nota clínica</h2>
    <div class="note">{_parrafos}</div>
    """ if _parrafos else ""

    # ── Anamnesis ─────────────────────────────────────────────────────────
    anamnesis_rows = [
        ("Historial de otitis",               "Sí" if s.get("anamnesis_otitis") else "No"),
        ("Diagnóstico auditivo",              s.get("anamnesis_hearing_dx") or "Ninguno"),
        ("Idioma(s) en el hogar",             s.get("anamnesis_home_language") or "Español"),
        ("Antecedentes familiares del habla", "Sí" if s.get("anamnesis_family_history") else "No"),
        ("Terapia de lenguaje previa",        "Sí" if s.get("anamnesis_prior_therapy") else "No"),
    ]
    raw_notes = s.get("notes") or ""
    if "Obs: " in raw_notes:
        obs = raw_notes.split("Obs: ", 1)[1]
        anamnesis_rows.append(("Observaciones", obs))

    anamnesis_html = "".join(
        f"<tr><td class='gray'>{k}</td><td><strong>{_esc(v)}</strong></td></tr>"
        for k, v in anamnesis_rows
    )

    color     = pffb_color(s.get("pffb"))
    pffb_val  = s.get("pffb")
    level_val = s.get("level") or "—"
    session_id = s.get("session_id", "")
    started    = (s.get("started_at") or "")[:16].replace("T", " ")
    titulo     = "Informe para representantes" if es_rep else "Informe clínico"

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <title>Audia — {titulo}</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
      font-size: 11pt; color: #1A202C;
      padding: 20mm 18mm;
      background: #fff;
    }}
    h1  {{ font-size: 17pt; font-weight: 800; color: #1B3A5C; margin-bottom: 2px; }}
    .sid {{ font-size: 9pt; color: #A0AEC0; font-family: monospace; margin-bottom: 18px; }}
    h2  {{ font-size: 11.5pt; font-weight: 700; color: #1B3A5C;
           margin: 20px 0 8px;
           border-bottom: 1.5px solid #E2E8F0; padding-bottom: 4px; }}
    .meta-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 24px; margin-bottom: 6px; }}
    .meta-key  {{ font-size: 8.5pt; color: #A0AEC0; }}
    .meta-val  {{ font-size: 10pt; font-weight: 600; }}
    .result-box {{
      text-align: center; padding: 14px 20px;
      background: #F7FAFC; border: 1.5px solid #E2E8F0;
      border-radius: 8px; margin: 10px 0;
    }}
    .r-level {{ font-size: 13pt; font-weight: 800; color: {color}; }}
    .r-pffb  {{ font-size: 24pt; font-weight: 800; color: {color}; line-height: 1.1; }}
    .r-interp{{ font-size: 9.5pt; color: {color}; margin-top: 4px; }}
    .t {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; margin-top: 4px; }}
    .t th {{
      background: #EBF4FF; color: #1B3A5C; font-weight: 600;
      padding: 6px 8px; text-align: left;
      border-bottom: 1.5px solid #C3DAFE;
    }}
    .t td {{ padding: 5px 8px; border-bottom: 1px solid #F0F4F8; vertical-align: top; }}
    .t tr:last-child td {{ border-bottom: none; }}
    .ana-t {{ width: 100%; border-collapse: collapse; font-size: 9.5pt; }}
    .ana-t td {{ padding: 4px 0; vertical-align: top; }}
    .ana-t td:first-child {{ width: 46%; padding-right: 12px; }}
    .note {{
      background: #F7FAFC; border-radius: 6px;
      padding: 10px 14px; font-size: 9.5pt;
      line-height: 1.65; color: #4A5568; margin-top: 4px;
    }}
    .note p {{ margin-bottom: 8px; }}
    .note p:last-child {{ margin-bottom: 0; }}
    .disclaimer {{
      font-size: 8pt; color: #A0AEC0; font-style: italic;
      text-align: center; margin-top: 28px; padding-top: 14px;
      border-top: 1px solid #E2E8F0; line-height: 1.5;
    }}
    .mono  {{ font-family: 'Courier New', monospace; }}
    .gray  {{ color: #A0AEC0; }}
    @page {{ margin: 20mm 18mm; }}
    @media print {{
      body {{ padding: 0; }}
      button {{ display: none; }}
    }}
  </style>
</head>
<body>

  <h1>{titulo}</h1>
  <p class="sid">Sesión #{session_id} &nbsp;·&nbsp; {started}</p>

  <h2>1. Identificación</h2>
  <div class="meta-grid">
    <div><div class="meta-key">Fecha de nacimiento</div>
         <div class="meta-val">{_esc(s.get('child_dob','—'))}</div></div>
    <div><div class="meta-key">Edad</div>
         <div class="meta-val">{age_label(s.get('child_age_months'))}</div></div>
    <div><div class="meta-key">Género</div>
         <div class="meta-val">{gender_label(s.get('child_gender',''))}</div></div>
    <div><div class="meta-key">Fecha de evaluación</div>
         <div class="meta-val">{(s.get('started_at') or '')[:10]}</div></div>
  </div>

  <h2>2. Anamnesis</h2>
  <table class="ana-t"><tbody>{anamnesis_html}</tbody></table>

  <h2>3. Resultado global</h2>
  <div class="result-box">
    <div class="r-level">{_esc(level_val)}</div>
    <div class="r-pffb">{fmt(pffb_val)}%</div>
    <div class="r-interp">{pffb_interp(pffb_val)}</div>
  </div>

  {phonemes_section}
  {items_section}
  {nota_section}

  <p class="disclaimer">
    Los resultados de este cribado no constituyen un diagnóstico clínico
    y deben ser interpretados por un profesional de la salud.
  </p>

</body>
</html>"""


def _esc(text) -> str:
    if text is None:
        return "—"
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
