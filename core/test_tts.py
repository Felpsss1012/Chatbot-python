import os

# DEFINIÇÃO DIRETA (ignora env var)
MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
SPEAKER_WAV = r"C:\Users\felip\Downloads\TCC\Assistente\Referencia.wav"
# SPEAKER_WAV = r"C:\Users\felip\Downloads\TCC\Assistente\model\XTTS-v2\samples\pt_sample.wav"   # FALLBACK
LANG = "pt"

print("MODEL =", MODEL)
print("SPEAKER_WAV =", SPEAKER_WAV)
print("LANG =", LANG)

# validação
if not os.path.exists(SPEAKER_WAV):
    raise FileNotFoundError(f"O arquivo de voz não existe: {SPEAKER_WAV}")

from TTS.api import TTS
tts = TTS(model_name=MODEL, progress_bar=True)

tts.tts_to_file(
    text="Eu tava jogando cleche Royale viado, e o cara me joga mega cavaleiro",
    file_path="out_test.wav",
    speaker_wav=SPEAKER_WAV,
    language="pt",
    temperature=0.3,   # mais natural e estável
    speed=1.0,         # 1.0 = normal
    length_penalty=1.0 # controle fino do ritmo
)



print("✔️ Arquivo gerado: out_test.wav")
