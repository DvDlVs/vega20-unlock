#!/bin/bash
set -uo pipefail

# vega20-unlock — instala o serviço systemd para aplicar o OC em todo boot
# Uso: sudo ./install.sh
# Remover: sudo ./scripts/restore.sh (desinstala o serviço)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="vega20-unlock"
INSTALL_DIR="/opt/vega20-unlock"

if [ "$(id -u)" != "0" ]; then
    echo "Rode como root: sudo ./install.sh" >&2
    exit 1
fi

# 1. Espelha o repo para um local estável
echo "--- Instalando em $INSTALL_DIR ---"
mkdir -p "$INSTALL_DIR/scripts"
cp -r "$SCRIPT_DIR/pp_tables" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/scripts/apply.sh" "$INSTALL_DIR/scripts/apply.sh"
cp "$SCRIPT_DIR/scripts/profile.conf" "$INSTALL_DIR/scripts/profile.conf"
chmod +x "$INSTALL_DIR/scripts/apply.sh"

APPLY_SCRIPT="$INSTALL_DIR/scripts/apply.sh"

# 2. Cria o serviço systemd
cat > /etc/systemd/system/$SERVICE_NAME.service <<EOF
[Unit]
Description=vega20-unlock — AMD Vega 20 overdrive unlock
After=systemd-modules-load.service
Wants=systemd-modules-load.service

[Service]
Type=oneshot
ExecStart=$APPLY_SCRIPT
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
EOF

# 3. Habilita
systemctl daemon-reload
systemctl enable $SERVICE_NAME
echo ""
echo "[OK] Serviço $SERVICE_NAME instalado e habilitado."
echo "     O OC será aplicado a cada boot usando o perfil em"
echo "     $INSTALL_DIR/scripts/profile.conf"
echo "     Ajuste esse perfil com o dashboard (oc_dash.py, tecla S) ou manualmente."
