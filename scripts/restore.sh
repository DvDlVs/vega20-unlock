#!/bin/bash
set -uo pipefail

# vega20-unlock — restaura o estado original (remove o soft unlock)
# Uso: sudo ./scripts/restore.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

find_amdgpu() {
    for card in /sys/class/drm/card*; do
        [ -d "$card/device/hwmon" ] || continue
        drv="$(basename "$(readlink -f "$card/device/driver" 2>/dev/null)" 2>/dev/null)"
        if [ "$drv" = "amdgpu" ]; then
            echo "$card/device"
            return 0
        fi
    done
}

PP_DIR="$(find_amdgpu)"
[ -n "$PP_DIR" ] || { echo "ERROR: sem device amdgpu" >&2; exit 1; }
PP="$PP_DIR/pp_table"
OD="$PP_DIR/pp_od_clk_voltage"

echo "=== vega20-unlock — restauração ==="
echo ""

# 1. Restaura a tabela stock em memória
echo "--- Restaurando tabela stock ---"
cat "$SCRIPT_DIR/pp_tables/stock.pp" > "$PP" 2>/dev/null && echo "[OK] restaurada em memória (aplica totalmente após reboot)"
sleep 2

# 2. Desativa serviço persistente, se instalado
echo ""
echo "--- Removendo serviço systemd (se instalado) ---"
systemctl disable vega20-unlock 2>/dev/null && echo "  [service desabilitado]" || echo "  [nenhum serviço vega20-unlock]"
rm -f /etc/systemd/system/vega20-unlock.service 2>/dev/null
systemctl daemon-reload 2>/dev/null

# 3. Reset do OD
echo ""
echo "--- Reset do overdrive ---"
if [ -w "$OD" ]; then
    echo 'r' > "$OD"; echo 'c' > "$OD" 2>/dev/null
    echo "  [OD resetado]"
fi
echo "  done"

echo ""
echo "=== Concluído. Power limit: defina 190W se desejar (via dashboard + / -) ==="
