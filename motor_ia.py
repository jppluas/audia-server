import os
import torch
import numpy as np
import platform
import sounddevice as sd
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor
from phonemizer import phonemize
from phonemizer.backend.espeak.wrapper import EspeakWrapper

# 1. Blindaje de eSpeak para Windows
if platform.system() == "Windows":
    espeak_install_path = r'C:\Program Files\eSpeak NG'
    if espeak_install_path not in os.environ.get('PATH', ''):
        os.environ['PATH'] = espeak_install_path + os.pathsep + os.environ.get('PATH', '')
    EspeakWrapper.set_library(os.path.join(espeak_install_path, 'libespeak-ng.dll'))

MATCH_SCORE, MISMATCH_SCORE, GAP_PENALTY = 2, -1, -2

def alinear_nw(esperado, producido):
    n, m = len(esperado), len(producido)
    score_matrix = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1): score_matrix[i][0] = i * GAP_PENALTY
    for j in range(m + 1): score_matrix[0][j] = j * GAP_PENALTY
        
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            match = score_matrix[i-1][j-1] + (MATCH_SCORE if esperado[i-1] == producido[j-1] else MISMATCH_SCORE)
            score_matrix[i][j] = max(match, score_matrix[i-1][j] + GAP_PENALTY, score_matrix[i][j-1] + GAP_PENALTY)
            
    align_esp, align_prod, ops = [], [], []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and (score_matrix[i][j] == score_matrix[i-1][j-1] + (MATCH_SCORE if esperado[i-1] == producido[j-1] else MISMATCH_SCORE)):
            align_esp.append(esperado[i-1]); align_prod.append(producido[j-1])
            ops.append("C" if esperado[i-1] == producido[j-1] else f"S(/{esperado[i-1]}/->/{producido[j-1]}/)")
            i -= 1; j -= 1
        elif i > 0 and (j == 0 or score_matrix[i][j] == score_matrix[i-1][j] + GAP_PENALTY):
            align_esp.append(esperado[i-1]); align_prod.append("-")
            ops.append(f"O(/{esperado[i-1]}/)")
            i -= 1
        else:
            align_esp.append("-"); align_prod.append(producido[j-1])
            ops.append("I")
            j -= 1
    return align_esp[::-1], align_prod[::-1], ops[::-1]

class MotorFonologico:
    def __init__(self):
        print("[Motor IA] Cargando VAD y Wav2Vec 2.0 XLS-R...")
        self.model_vad, self.utils = torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)
        self.VADIterator = self.utils[3]
        self.id_modelo = "facebook/wav2vec2-large-xlsr-53-spanish"
        self.processor = Wav2Vec2Processor.from_pretrained(self.id_modelo)
        self.model_stt = Wav2Vec2ForCTC.from_pretrained(self.id_modelo)
        print("[Motor IA] ✅ Listo.")

    def capturar_y_evaluar(self, palabra_esperada, fonema_objetivo):
        import threading
        vad_iterator = self.VADIterator(self.model_vad, threshold=0.3, sampling_rate=16000, min_silence_duration_ms=600, speech_pad_ms=400)
        audio_buffer = []
        started, ended = threading.Event(), threading.Event()
        
        def callback(indata, frames, time, status):
            chunk = indata.flatten().astype(np.float32)
            audio_buffer.append(chunk)
            evento = vad_iterator(torch.FloatTensor(chunk), return_seconds=True)
            if evento:
                if 'start' in evento: started.set()
                elif 'end' in evento: ended.set()
                
        with sd.InputStream(samplerate=16000, channels=1, blocksize=512, dtype='float32', callback=callback):
            if not started.wait(timeout=5.0):
                return None, None # Timeout (El niño no habló)
            ended.wait(timeout=6.0)
            
        audio_numpy = np.concatenate(audio_buffer)
        
        inputs = self.processor(audio_numpy, sampling_rate=16000, return_tensors="pt").input_values
        with torch.no_grad():
            logits = self.model_stt(inputs).logits
        transcripcion = self.processor.batch_decode(torch.argmax(logits, dim=-1))[0].lower()
        if not transcripcion.strip(): transcripcion = "[sin respuesta]"

        # 2. Arreglo de la letra "g" internacional
        fon_esp = phonemize(palabra_esperada, language='es', strip=True, backend='espeak').replace(" ", "").replace("ɡ", "g")
        fon_prod = "-" if transcripcion == "[sin respuesta]" else phonemize(transcripcion, language='es', strip=True, backend='espeak').replace(" ", "").replace("ɡ", "g")
        
        if fon_prod == "-":
            esp_al = list(fon_esp)
            prod_al = ["-"] * len(fon_esp)
            ops = [f"O(/{f}/)" for f in fon_esp]
        else:
            esp_al, prod_al, ops = alinear_nw(fon_esp, fon_prod)

        # 3. Arreglo del 0% Matemático (Remoción de barras diagonales)
        fon_obj_limpio = fonema_objetivo.replace("/", "")
        aciertos = 0
        total_apariciones = 0
        errores_del_objetivo = []

        for i, f in enumerate(esp_al):
            if f == fon_obj_limpio:
                total_apariciones += 1
                if ops[i] == "C":
                    aciertos += 1
                else:
                    errores_del_objetivo.append(ops[i])
        
        pff = (aciertos / total_apariciones) * 100 if total_apariciones > 0 else 0

        if pff == 100:
            error_type = None
            resultado_final = "correct"
        else:
            resultado_final = "error"
            sustituciones = sum(1 for op in errores_del_objetivo if op.startswith('S'))
            omisiones = sum(1 for op in errores_del_objetivo if op.startswith('O'))
            error_type = "Sustitución" if sustituciones >= omisiones and sustituciones > 0 else "Omisión" if omisiones > 0 else "Distorsión"

        resultado = {
            "palabra_esperada": palabra_esperada, "word_produced": transcripcion,
            "pff": pff, "error_type": error_type, "result": resultado_final,
            "alignment": {"esperado": esp_al, "producido": prod_al, "ops": ops}
        }
        return resultado, audio_numpy