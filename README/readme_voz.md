
# Guia de Configuração de Voz – XTTS‑v2  
Documento: **readme_voz.md**

Este guia explica como configurar, personalizar e alternar vozes no modelo **XTTS‑v2** do Coqui TTS, incluindo uso de voz personalizada, samples oficiais, e perfis de voz.

---

# 🎙️ 1. Usando uma Voz Personalizada (Recomendada)

Para usar seu próprio arquivo de voz como referência:

```python
SPEAKER_WAV = r"C:\Users\felip\Downloads\TCC\Assistente\Referencia.wav"
LANG = "pt"
```

Requisitos do arquivo:
- Formato **WAV REAL** (RIFF)
- 16 kHz ou 22 kHz
- Mono ou Stereo
- 3–6 segundos de fala normal
- Sem ruído excessivo

---

# 🎧 2. Usando a Voz Feminina Original do XTTS (Fallback)

Caso queira voltar para a voz feminina oficial:

```python
# SPEAKER_WAV = r"C:\Users\felip\Downloads\TCC\Assistente\model\XTTS-v2\samples\pt_sample.wav"
```

---

# 🔧 3. Parâmetros Disponíveis no XTTS‑v2

O método `tts_to_file` aceita:

| Parâmetro | Descrição |
|----------|-----------|
| `speaker_wav` | Arquivo de referência da voz |
| `language` | Língua da fala gerada |
| `temperature` | Naturalidade / variação da fala |
| `speed` | Velocidade (1.0 = normal) |
| `length_penalty` | Ajusta ritmo e duração |

⚠️ **IMPORTANTE:**  
Os parâmetros antigos `gpt_cond_temperature` e `gpt_cond_len` **não existem mais** no XTTS‑v2 → não use.

---

# 🎛️ 4. Exemplo Base do `tts_to_file` (sem erro)

```python
tts.tts_to_file(
    text="Testando personalização de voz no XTTS",
    file_path="out_test.wav",
    speaker_wav=SPEAKER_WAV,
    language=LANG,
    temperature=0.3,
    speed=1.0,
    length_penalty=1.0
)
```

---

# 🔊 5. Perfis de Voz Prontos

Abaixo estão perfis prontos que você pode aplicar diretamente.

---

## 🟦 Perfil 1 — Voz Masculina Grave

```python
temperature = 0.25
speed = 0.9
length_penalty = 1.05
```

---

## 🟦 Perfil 2 — Voz Jovem / Aguda

```python
temperature = 0.3
speed = 1.1
```

---

## 🟦 Perfil 3 — Voz Natural (Assistente Virtual)

```python
temperature = 0.2
speed = 1.0
length_penalty = 1.0
```

---

## 🟦 Perfil 4 — Voz Expressiva

```python
temperature = 0.5
speed = 1.0
```

---

# 🗂️ 6. Alternando Entre Perfis no Projeto

Você pode adicionar uma seleção simples:

```python
VOICE_PROFILE = "minha_voz"

if VOICE_PROFILE == "minha_voz":
    SPEAKER_WAV = r"C:\Users\felip\Downloads\TCC\Assistente\Referencia.wav"
elif VOICE_PROFILE == "feminina":
    SPEAKER_WAV = r"C:\Users\felip\Downloads\TCC\Assistente\model\XTTS-v2\samples\pt_sample.wav"
elif VOICE_PROFILE == "grave":
    temperature = 0.25
    speed = 0.9
elif VOICE_PROFILE == "aguda":
    speed = 1.1
```

---

# 🛠️ 7. Recomendações Importantes

- Prefira gravações limpas sem eco.
- Quanto melhor a referência, melhor a voz final.
- Evite arquivos MP3 → sempre use WAV.
- Para melhorar: equalizar, reduzir ruído, normalizar volume.

---

# 📌 8. Ferramentas Úteis

### Para converter áudio:
https://convertio.co/pt/audio-converter/

### Para gravar WAV diretamente:
https://online-voice-recorder.com/

### Para editar / limpar ruído:
https://twistedwave.com/online

---