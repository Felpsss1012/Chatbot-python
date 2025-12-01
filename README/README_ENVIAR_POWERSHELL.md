# 📦 Enviando arquivos para o Raspberry Pi via PowerShell

Este guia explica como **enviar o projeto (cliente.py, IDLE.gif, speek.gif, etc.)** do seu PC Windows para o Raspberry Pi, usando apenas o **PowerShell**.

---

## ⚙️ Pré-requisitos

- O Raspberry Pi e o PC **devem estar na mesma rede local**.
- O Raspberry Pi deve ter o **SSH habilitado** (pode ser ativado via Raspberry Pi Imager ou `sudo raspi-config` → Interface Options → SSH → Enable).
- O Windows precisa ter o **OpenSSH** instalado (vem por padrão no Windows 10/11).

---

## 📁 Estrutura esperada do projeto

Na sua pasta do projeto (no PC), você deve ter pelo menos estes arquivos:

```
cliente.py
IDLE.gif
speek.gif
```

---

## 🧠 Variáveis básicas

Antes de enviar, anote:

| Variável | Descrição | Exemplo |
|-----------|------------|---------|
| `PiUser`  | Usuário do Raspberry Pi | `pi` |
| `PiHost`  | IP do Raspberry Pi | `[IP do cliente]` |
| `RemoteDir` | Caminho de destino no Pi | `/home/pi/project` |
| `ServerIP` | IP do servidor (PC) que o cliente vai usar | `[IP do server]` |

---

## 🚀 Enviando os arquivos (comando PowerShell)

Abra o **PowerShell** no diretório do projeto e rode:

```powershell
# Enviar os arquivos cliente.py e GIFs para o Raspberry
scp .\cliente.py .\IDLE.gif .\speek.gif pi@[IP do cliente]:/home/pi/project/
```

> 💡 Substitua `pi@[IP do cliente]` e `/home/pi/project/` conforme o seu setup.

Se você usa chave SSH:

```powershell
scp -i C:\Users\SeuUsuario\.ssh\id_ed25519 .\cliente.py .\IDLE.gif .\speek.gif pi@[IP do cliente]:/home/pi/project/
```

---

## 🧩 Executando o cliente no Raspberry Pi

Conecte ao Pi via SSH:

```powershell
ssh pi@[IP do cliente]
```

No terminal do Raspberry:

```bash
cd /home/pi/project
python3 cliente.py --server [IP do server]
```

Se quiser rodar **em segundo plano** e deixar a GUI aparecer no monitor do Pi:

```bash
DISPLAY=:0 nohup python3 cliente.py --server [IP do server] > cliente.log 2>&1 &
```

---

## 🔁 Script PowerShell opcional (automático)

Se quiser automatizar, crie um arquivo chamado `quick-deploy.ps1` com o conteúdo abaixo:

```powershell
$PiUser = "pi"
$PiHost = "[IP do server]"
$RemoteDir = "/home/pi/project"
$ServerIP = "[IP do server]"

scp .\cliente.py .\IDLE.gif .\speek.gif $PiUser@$PiHost:$RemoteDir/
ssh $PiUser@$PiHost "cd $RemoteDir && DISPLAY=:0 nohup python3 cliente.py --server $ServerIP > /home/pi/cliente.log 2>&1 &"

Write-Host "✅ Arquivos enviados e cliente iniciado no Raspberry Pi."
```

Para rodar o script:

```powershell
.\quick-deploy.ps1
```

---

## 🧰 Dicas úteis

- Se der erro de permissão no áudio, adicione o usuário ao grupo `audio`:

```bash
sudo usermod -aG audio pi
```

- Para instalar dependências no Pi (caso faltem):

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-tk python3-pil.imagetk python3-pygame alsa-utils mpv
sudo pip3 install --no-cache-dir pillow
```

- Logs do cliente se você rodar com `nohup`:

```bash
tail -f /home/far/cliente.log
```

---

## 💾 Resumo rápido

| Tarefa | Comando |
|--------|----------|
| Enviar arquivos | `scp .\cliente.py .\IDLE.gif .\speek.gif far@[IP do cliente]:/home/far/chatbot/` |
| Conectar ao Pi | `ssh pi@[IP do cliente]` |
| Rodar cliente | `python3 /home/far/chatbot/cliente.py --server [IP do cliente]` |
| Rodar com GUI (em background) | `DISPLAY=:0 nohup python3 /home/par/chatbot/cliente.py --server [IP do cliente] &` |

---
 