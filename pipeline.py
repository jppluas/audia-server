import os
import time
import traceback
import sys
import soundfile as sf
import sounddevice as sd
from pathlib import Path
import db
from motor_ia import MotorFonologico

motor = MotorFonologico()
BASE_DIR = Path(__file__).resolve().parent
AUDIOS_DIR = BASE_DIR / "audios"

BATERIA = [
    ("/m/", "mamá"), 
    ("/t/", "taza"), 
    ("/g/", "gato")
    # Descomentar el resto de la batería para pruebas completas
]

def estado_actual(session_id):
    """Lee el estado real y actualizado directo de la memoria principal de Flask."""
    estado_real = sys.modules['__main__']._session_state
    if estado_real.get("session_id") != session_id:
        return "cancelled" 
    return estado_real.get("status")

def actualizar_ui(session_id, clave, valor):
    """Escribe en la pantalla web usando el puntero real de memoria."""
    estado_real = sys.modules['__main__']._session_state
    if estado_real.get("session_id") == session_id:
        estado_real[clave] = valor

def run_pipeline(session_id, state_fantasma): 
    try:
        time.sleep(2.5) 
        
        actualizar_ui(session_id, "total_items", len(BATERIA))
        folder_path = db.get_recordings_dir(session_id)
        folder_path.mkdir(parents=True, exist_ok=True)
        resultados_items = []

        for i, (fonema, palabra) in enumerate(BATERIA):
            
            # === LÓGICA CLÍNICA DE REINTENTOS POR SILENCIO ===
            intentos_maximos = 3
            res = None
            audio_np = None
            
            for intento in range(intentos_maximos):
                while estado_actual(session_id) == "paused": time.sleep(0.5)
                if estado_actual(session_id) == "cancelled": return
                
                actualizar_ui(session_id, "current_item", i + 1)
                actualizar_ui(session_id, "current_word", palabra)
                actualizar_ui(session_id, "status", "playing")
                actualizar_ui(session_id, "no_voice_detected", intento > 0)
                
                nombre_limpio = db._normalize_word(palabra)
                ruta_audio = AUDIOS_DIR / f"{nombre_limpio}.wav"
                
                if ruta_audio.exists():
                    data, fs = sf.read(str(ruta_audio))
                    sd.play(data, fs)
                    duracion = len(data) / fs
                    pasos = int(duracion * 10) + 5
                    for _ in range(pasos):
                        time.sleep(0.1)
                        if estado_actual(session_id) == "cancelled":
                            sd.stop()
                            return
                else:
                    print(f"⚠️ ALERTA: Falta el archivo: {ruta_audio}")
                    time.sleep(2)
                
                if estado_actual(session_id) == "cancelled": return
                
                # =========================================================
                # FIX 2: Barrera si el usuario puso pausa DURANTE el audio.
                # Evita que el sistema sobrescriba la pausa con el "recording"
                # =========================================================
                while estado_actual(session_id) == "paused": 
                    time.sleep(0.5)
                
                if estado_actual(session_id) == "cancelled": return
                
                # Ahora sí es seguro abrir el micrófono
                actualizar_ui(session_id, "status", "recording")
                res, audio_np = motor.capturar_y_evaluar(palabra, fonema)
                
                if estado_actual(session_id) == "cancelled": return
                
                # Barrera final por si pausaron mientras el niño hablaba
                while estado_actual(session_id) == "paused": 
                    time.sleep(0.5)
                
                if res is not None:
                    break # Rompe los reintentos si el niño habló
                
                print(f"[{session_id}] Silencio detectado en '{palabra}'. Intento {intento+1}/{intentos_maximos}")
            
            actualizar_ui(session_id, "no_voice_detected", False)
            # =================================================
            
            item_data = {
                "item_index": i, "phoneme": fonema, "word_expected": palabra,
                "word_produced": None, "audio_path": None, "result": "not_evaluable",
                "error_type": None, "pff": 0.0, "alignment": None
            }

            if res is not None:
                filename = db.audio_filename(session_id, palabra)
                sf.write(str(folder_path / filename), audio_np, 16000)
                item_data.update({
                    "word_produced": res["word_produced"], "audio_path": f"{session_id}/{filename}",
                    "result": res["result"], "error_type": res["error_type"],
                    "pff": res["pff"], "alignment": res["alignment"]
                })
                
            resultados_items.append(item_data)
            db.save_item(session_id, item_data)

        if estado_actual(session_id) == "cancelled": return

        # === FASE FINAL ===
        actualizar_ui(session_id, "status", "analyzing")
        actualizar_ui(session_id, "current_word", None)
        
        agrupado = {}
        for item in resultados_items:
            if item["result"] != "not_evaluable":
                agrupado.setdefault(item["phoneme"], []).append(item)
                
        pff_por_fonema = []
        for fon, items in agrupado.items():
            promedio = sum(x["pff"] for x in items) / len(items) if items else 0
            nivel = "Normal" if promedio > 75 else "Seguimiento activo" if promedio >= 50 else "Atención requerida"
            errores = [x["error_type"] for x in items if x["error_type"]]
            predominante = max(set(errores), key=errores.count) if errores else "Ninguno"
            
            db.save_phoneme_summary(session_id, {"phoneme": fon, "pff": promedio, "level": nivel, "error_predominant": predominante})
            pff_por_fonema.append((fon, promedio, predominante))

        pffb_global = sum(p[1] for p in pff_por_fonema) / len(pff_por_fonema) if pff_por_fonema else 0
        nivel_global = "Normal" if pffb_global > 75 else "Seguimiento activo" if pffb_global >= 50 else "Atención requerida"
        
        db.close_session(session_id, pffb_global, nivel_global)

        actualizar_ui(session_id, "status", "generating_report")

        nota_c = _generar_nota_clinica(pffb_global, nivel_global, pff_por_fonema)
        nota_r = _generar_nota_representantes(pffb_global, nivel_global, pff_por_fonema)

        db.save_report(session_id, {"nota_clinica": nota_c, "nota_representantes": nota_r})
        
        actualizar_ui(session_id, "results", {
            "score": round(pffb_global, 2),
            "level": nivel_global
        })
        actualizar_ui(session_id, "status", "done")

    except Exception as e:
        print(f"\n❌ ERROR CRÍTICO EN EL PIPELINE: {e}")
        traceback.print_exc()
        actualizar_ui(session_id, "status", "error")
        db.close_session(session_id, 0.0, "Error del Sistema")


# ── Base de conocimiento clínico por fonema ───────────────────────────────────
_CONOCIMIENTO_FONEMA = {
    "/m/": {
        "tipo": "nasal bilabial",
        "omision": (
            "La omisión de /m/ puede indicar dificultad para sostener el cierre labial. "
            "Se recomienda estimular con bombardeo auditivo de palabras con /m/ inicial "
            "y ejercicios de cierre labial (soplar, besar objetos). Priorizar posición inicial."
        ),
        "sustitucion": (
            "La sustitución de /m/ suele reflejar confusión entre nasales. "
            "Trabajar discriminación auditiva /m/-/n/ y resonancia nasal frente a espejo. "
            "Contrastar pares mínimos: 'mamá/nana', 'mano/nano'."
        ),
        "padres_omision": "Pida a su niño que cierre los labios al decir 'mmm' como si oliera algo rico. Practiquen juntos palabras como mamá, mano, mesa.",
        "padres_sustitucion": "Digan juntos 'mamá' y 'nana' alternando, notando que para la 'M' los labios se juntan y para la 'N' la lengua sube.",
    },
    "/p/": {
        "tipo": "oclusiva bilabial sorda",
        "omision": (
            "La omisión de /p/ es frecuente en posición final. Reforzar conciencia del "
            "cierre labial y el golpe de aire con velas o papel tissue. Trabajar primero "
            "en posición inicial (papá, pato) y luego en posición final (top, cap)."
        ),
        "sustitucion": (
            "La sustitución /p/→/b/ indica dificultad para diferenciar sordas y sonoras. "
            "Usar pares mínimos poca/boca, pala/bala. Verificar vibración laríngea "
            "con la mano en la garganta para distinguir /p/ (sin vibración) de /b/."
        ),
        "padres_omision": "Soplen juntos una vela sin apagarla diciendo 'p-p-p'. Luego digan 'papá', 'pato', 'piso' exagerando el golpe de aire al inicio.",
        "padres_sustitucion": "Pongan la mano en la garganta: con 'b' vibra, con 'p' no. Jueguen alternando 'poca/boca', 'pala/bala' sintiendo la diferencia.",
    },
    "/b/": {
        "tipo": "oclusiva bilabial sonora",
        "omision": (
            "La omisión de /b/ requiere atención en posición inicial. Trabajar con "
            "palabras de alta frecuencia: boca, bota, bebé. Verificar si la omisión "
            "ocurre también en posición intervocálica (proceso normal en español)."
        ),
        "sustitucion": (
            "La sustitución /b/→/p/ (desonorización) es frecuente hasta los 4 años. "
            "Trabajar consciencia de vibración laríngea y pares mínimos boca/poca. "
            "Suele resolverse espontáneamente; derivar si persiste después de los 4 años."
        ),
        "padres_omision": "Practiquen 'boca', 'bota', 'bebé' con énfasis en el sonido inicial. Jueguen a encontrar objetos que empiecen con 'b' en casa.",
        "padres_sustitucion": "La 'b' vibra en la garganta, la 'p' no. Toque su garganta al decir 'boca' y luego 'poca'. Pida a su niño que imite sintiendo esa vibración.",
    },
    "/t/": {
        "tipo": "oclusiva dental sorda",
        "omision": (
            "La omisión de /t/ en posición inicial es inusual y requiere atención. "
            "Trabajar posición de lengua detrás de incisivos superiores con espejo. "
            "Usar palabras: taza, tela, topo."
        ),
        "sustitucion": (
            "La sustitución /t/→/d/ indica dificultad sorda/sonora. "
            "La sustitución /t/→/k/ (posteriorización) es infrecuente y requiere "
            "trabajo de fronting con pares mínimos taza/casa. Verificar cuál de "
            "los dos patrones predomina para orientar la intervención."
        ),
        "padres_omision": "Frente a un espejo, muéstrele que la lengua toca detrás de los dientes al decir 'ta'. Practiquen 'taza', 'tela', 'topo'.",
        "padres_sustitucion": "Si dice 'daza' por 'taza': ponga su mano en la garganta, la 't' no vibra. Si dice 'kaza': la 't' se hace adelante con la lengua, no atrás.",
    },
    "/d/": {
        "tipo": "oclusiva dental sonora",
        "omision": (
            "La omisión de /d/ intervocálica es un proceso normal en español hasta los 4 años. "
            "En posición inicial requiere atención antes. Trabajar con dado, dedo, diente."
        ),
        "sustitucion": (
            "La sustitución /d/→/t/ (desonorización) es el error más frecuente. "
            "Trabajar percepción de vibración laríngea y pares mínimos dedo/teto, dado/tato. "
            "Evaluar si ocurre solo intervocálicamente (proceso normal) o en todos los contextos."
        ),
        "padres_omision": "Practiquen 'dado', 'dedo', 'diente' marcando bien el sonido inicial. Si omite la 'd' en medio de palabra (como 'naa' por 'nada'), es frecuente a esta edad.",
        "padres_sustitucion": "Si dice 'tedo' por 'dedo', la diferencia es la vibración. Digan juntos 'dedo' tocando la garganta para sentir que la 'd' vibra.",
    },
    "/k/": {
        "tipo": "oclusiva velar sorda",
        "omision": (
            "La omisión de /k/ indica dificultad para elevar el postdorso lingual. "
            "Trabajar con juegos de gárgaras para activar la zona posterior de la lengua. "
            "Bombardeo auditivo con: casa, coco, cuna, carro."
        ),
        "sustitucion": (
            "La sustitución /k/→/t/ es fronting velar, frecuente hasta los 3.5 años. "
            "Trabajar discriminación auditiva k/t, pares mínimos casa/tasa, coco/toco. "
            "Explicar que la 'k' se hace 'atrás' con la lengua. Resolución espontánea "
            "esperada antes de los 4 años; derivar si persiste."
        ),
        "padres_omision": "Hagan gárgaras juntos para activar la parte trasera de la lengua. Luego digan 'ca-ca-ca' exagerando. Practiquen: casa, coche, cuna.",
        "padres_sustitucion": "Si dice 'tasa' por 'casa': explíquele que la 'c/k' se hace con la parte de atrás de la lengua, como haciendo gárgaras. Practiquen 'coco' y 'toco' alternando.",
    },
    "/g/": {
        "tipo": "oclusiva velar sonora",
        "omision": (
            "La omisión de /g/ es análoga a /k/. Verificar si ocurre solo en posición "
            "intervocálica (aproximación normal en español) o en todos los contextos. "
            "Trabajar junto con /k/ por similitud articulatoria."
        ),
        "sustitucion": (
            "La sustitución /g/→/d/ es fronting velar sonoro. Trabajar junto con /k/→/t/. "
            "Pares mínimos: gato/dato, goma/doma. Resolución esperada antes de los 4 años."
        ),
        "padres_omision": "Similar a la 'c/k' pero con voz. Practiquen 'gato', 'goma', 'agua' exagerando el sonido. La lengua va atrás igual que en la 'c'.",
        "padres_sustitucion": "Si dice 'dato' por 'gato': la 'g' se hace igual que la 'c' pero con vibración. Practiquen gato/dato y coco/gogo alternando.",
    },
    "/f/": {
        "tipo": "fricativa labiodental",
        "omision": (
            "La omisión de /f/ indica dificultad en la coordinación labio-dental. "
            "Trabajar posición articulatoria: incisivos superiores sobre labio inferior, "
            "soplando suavemente. Usar espejo y papel tissue."
        ),
        "sustitucion": (
            "La sustitución /f/→/p/ (stopping) es frecuente hasta los 3 años. "
            "Trabajar flujo de aire continuo frente a vela o papel: la 'f' sopla sin cortar, "
            "la 'p' corta el aire. Pares mínimos: foca/poca, feo/peo."
        ),
        "padres_omision": "Ponga los dientes de arriba sobre el labio de abajo y sople suave: ese es el sonido 'f'. Practiquen frente al espejo con 'foca', 'foco', 'feo'.",
        "padres_sustitucion": "Si dice 'poca' por 'foca': la 'f' sopla aire continuo (como el viento), la 'p' lo corta. Soplen juntos una vela sin apagarla diciendo 'ffff'.",
    },
    "/n/": {
        "tipo": "nasal alveolar",
        "omision": (
            "La omisión de /n/ en posición final es frecuente. Trabajar con palabras "
            "que terminan en /n/: pan, tren, camión. Verificar audición periférica si "
            "el error es sistemático en todas las posiciones."
        ),
        "sustitucion": (
            "La sustitución /n/→/m/ indica confusión de punto articulatorio entre nasales. "
            "Trabajar diferenciación táctil: /m/ cierra labios, /n/ lengua al paladar. "
            "Pares mínimos: nada/mada, nene/meme."
        ),
        "padres_omision": "Practiquen palabras que terminan en 'n': pan, tren, limón, camión. Exageren el final 'n' al pronunciarlas.",
        "padres_sustitucion": "Para la 'n' la lengua sube al paladar, para la 'm' los labios se cierran. Practiquen tocando labios vs. paladar al decir 'mamá' y 'nana'.",
    },
    "/l/": {
        "tipo": "lateral alveolar",
        "omision": (
            "La omisión de /l/ tiene alto impacto en inteligibilidad. Requiere atención "
            "prioritaria. Trabajar posición alveolar de lengua y flujo lateral del aire. "
            "Palabras objetivo: luna, lago, llave, pelota."
        ),
        "sustitucion": (
            "La sustitución /l/→/r/ o /l/→/d/ son los errores más comunes. "
            "Diferenciar /l/ (lengua estática en alveolar, aire por lados) de /r/ "
            "(lengua vibra). Si persiste después de los 4.5 años, derivar a fonoaudiología."
        ),
        "padres_omision": "Ponga la lengua tocando el paladar justo detrás de los dientes y diga 'la-la-la'. Practiquen: luna, lago, llave. Es importante trabajarlo pronto.",
        "padres_sustitucion": "Si dice 'runa' por 'luna': la 'l' tiene la lengua quieta tocando arriba, la 'r' vibra. Digan 'la-la-la' lentamente con la lengua pegada al paladar.",
    },
}

_INTERPRETACION_CLINICA = {
    "Normal": (
        "El perfil fonológico es consistente con el desarrollo esperado para el rango etario. "
        "No se requiere intervención activa. Seguimiento rutinario."
    ),
    "Seguimiento activo": (
        "El perfil presenta errores que no configuran riesgo severo pero ameritan monitoreo. "
        "Re-evaluación recomendada en 3 meses. Considerar derivación si los errores afectan "
        "la inteligibilidad o persisten sin mejoría."
    ),
    "Atención requerida": (
        "El perfil evidencia dificultades significativas en múltiples fonemas con impacto "
        "en la inteligibilidad. Se recomienda derivación a evaluación fonoaudiológica completa "
        "para diagnóstico diferencial y planificación de intervención."
    ),
}

_INTERPRETACION_PADRES = {
    "Normal": "La pronunciación de su niño/a está dentro de lo esperado. Continúe con lectura de cuentos y conversación cotidiana.",
    "Seguimiento activo": "Se recomienda una nueva evaluación en 3 meses para verificar la evolución.",
    "Atención requerida": "Se recomienda consultar con un fonoaudiólogo para orientación personalizada.",
}


def _generar_nota_clinica(pffb: float, nivel: str, pff_por_fonema: list) -> str:
    partes = []
    partes.append(
        f"Cribado fonológico completado con PFFB de {pffb:.2f}% (nivel: {nivel})."
    )

    con_error = [(f, p, e) for f, p, e in pff_por_fonema if p < 100]

    if not con_error:
        partes.append("No se detectaron errores fonémicos en los fonemas evaluados.")
    else:
        for fon, pff, error in con_error:
            info = _CONOCIMIENTO_FONEMA.get(fon)
            if not info:
                continue
            error_lower = (error or "").lower()
            if "omis" in error_lower:
                consejo = info.get("omision", "")
            elif "sustit" in error_lower:
                consejo = info.get("sustitucion", "")
            else:
                consejo = (
                    f"Se detectó {error} en {fon} ({info['tipo']}). "
                    "Se recomienda evaluación articulatoria detallada."
                )
            if consejo:
                partes.append(f"{fon} — PFF {pff:.2f}%: {consejo}")

    partes.append(_INTERPRETACION_CLINICA.get(nivel, ""))
    return "\n\n".join(p for p in partes if p)


def _generar_nota_representantes(pffb: float, nivel: str, pff_por_fonema: list) -> str:
    partes = []

    if nivel == "Normal":
        partes.append(f"Su niño/a obtuvo {pffb:.2f}% en la evaluación de pronunciación, dentro del rango esperado para su edad.")
    elif nivel == "Seguimiento activo":
        partes.append(f"Su niño/a obtuvo {pffb:.2f}% en la evaluación. Pronuncia bien la mayoría de los sonidos; los siguientes merecen refuerzo en casa:")
    else:
        partes.append(f"Su niño/a obtuvo {pffb:.2f}% en la evaluación. Se detectaron dificultades en los siguientes sonidos:")

    con_error = [(f, p, e) for f, p, e in pff_por_fonema if p < 100]
    for fon, pff, error in con_error:
        info = _CONOCIMIENTO_FONEMA.get(fon)
        if not info:
            continue
        error_lower = (error or "").lower()
        if "omis" in error_lower:
            consejo = info.get("padres_omision", "")
        elif "sustit" in error_lower:
            consejo = info.get("padres_sustitucion", "")
        else:
            consejo = info.get("padres_omision", "")
        if consejo:
            partes.append(f"Sonido {fon}: {consejo}")

    partes.append(_INTERPRETACION_PADRES.get(nivel, ""))
    return "\n\n".join(p for p in partes if p)
