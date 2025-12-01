Inverter (rodar 180° / mudar orientação) da Display MHS 3.5" no Raspberry Pi (via GPIO)

Visão geral
- Este README descreve como inverter/permanecer a rotação da Display MHS 3.5" (driver fb_ili9486, overlay mhs35) e ajustar o touch ADS7846.
- Testado em: Raspberry Pi 3 B+, Raspberry Pi OS (legacy, X11). Usuário de sessão: far.
- Sempre faça backup antes de editar /boot/config.txt.

Arquivos de backup que podem existir
- /boot/config.txt.bak
- /boot/config.txt.bak2
- /boot/config.txt.pre-try270
- /home/far/.xsessionrc.bak
- /home/far/.xsessionrc.disabled

Detecção (comandos para rodar antes de alterar)
grep -n "dtoverlay=mhs35" /boot/config.txt
dmesg | egrep -i 'fb_ili|fbtft|rotate|fbdev|fbcon' | tail -n 80
fbset -s
ls -l /dev/fb*
sudo -u far DISPLAY=:0 XAUTHORITY=/home/far/.Xauthority xrandr --listmonitors
sudo -u far DISPLAY=:0 XAUTHORITY=/home/far/.Xauthority xinput list-props "ADS7846 Touchscreen"

Como aplicar rotação PERMANENTE (seguro)
1) Backup do config:
sudo cp /boot/config.txt /boot/config.txt.bak

2) Substituir o valor de rotate (0/90/180/270). Exemplo para 180°:
sudo cp /boot/config.txt /boot/config.txt.pre-rotate180
sudo sed -i -E 's/(dtoverlay=mhs35:rotate=)[0-9]+/\1180/' /boot/config.txt   || sudo sh -c 'echo "dtoverlay=mhs35:rotate=180" >> /boot/config.txt'

3) Reiniciar para aplicar:
sudo reboot

Como testar rotação temporária (sem reiniciar)
# Nem sempre funciona em displays SPI/fbtft, mas funciona em displays HDMI/DRM:
sudo -u far DISPLAY=:0 XAUTHORITY=/home/far/.Xauthority xrandr --query
sudo -u far DISPLAY=:0 XAUTHORITY=/home/far/.Xauthority   xrandr --output <NOME_DA_SAIDA> --rotate inverted

Ajuste do TOUCH (ADS7846) - aplicar agora e persistente
Matrizes de transformação (Coordinate Transformation Matrix):
- 0° (normal): 1 0 0 0 1 0 0 0 1
- 90° (CW):      0 1 0 -1 0 1 0 0 1
- 180° (upside): -1 0 1 0 -1 1 0 0 1
- 270° (CCW):    0 -1 1 1 0 0 0 0 1

Aplicar imediatamente (após reboot e desktop rodando):
sudo -u far DISPLAY=:0 XAUTHORITY=/home/far/.Xauthority xinput set-prop "ADS7846 Touchscreen" "Coordinate Transformation Matrix" -1 0 1 0 -1 1 0 0 1
(Substitua a matriz pelos valores corretos se usar outra rotação.)

Tornar persistente (aplica no login X do usuário far):
cat <<'EOF' | sudo -u far tee /home/far/.xsessionrc
/usr/bin/xinput set-prop "ADS7846 Touchscreen" "Coordinate Transformation Matrix" -1 0 1 0 -1 1 0 0 1 || true
EOF
sudo chown far:far /home/far/.xsessionrc
sudo chmod 644 /home/far/.xsessionrc

Para remover persistência do touch:
rm /home/far/.xsessionrc
ou restaurar backup:
[ -f /home/far/.xsessionrc.bak ] && sudo cp /home/far/.xsessionrc.bak /home/far/.xsessionrc

Comandos de reversão / voltar ao que estava
# restaurar backup
sudo cp /boot/config.txt.bak /boot/config.txt
sudo reboot

# ou outro backup
sudo cp /boot/config.txt.pre-try270 /boot/config.txt
sudo reboot

Diagnóstico / troubleshooting rápido
- Tela preta após alteração: restaure o backup (/boot/config.txt.bak) e reinicie.
- Touch desalinhado: rode xinput list-props "ADS7846 Touchscreen" e verifique Coordinate Transformation Matrix; aplique a matriz correta.
- fbset geometry 480 320 -> landscape; 320 480 -> portrait.
- Veja dmesg: dmesg | egrep -i 'fb_ili|fbtft|rotate' | tail -n 80
- Framebuffer da tela normalmente aparece em /dev/fb1 e no dmesg como fb_ili9486.

Boas práticas
- Sempre faça backup antes de editar /boot/config.txt.
- Teste a matriz do touch somente após confirmar a rotação da tela.
- Documente alterações (use backups com nomes descritivos).
- Método descrito aplica para displays SPI/fbtft com dtoverlay=mhs35. Para DSI/HDMI use lcd_rotate/display_rotate conforme necessário.

