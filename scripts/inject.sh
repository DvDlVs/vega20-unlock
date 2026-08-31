#!/bin/bash
set -euo pipefail

# vega20-unlock — injeta a PowerPlay table com OD habilitado (soft unlock)
#
# Uso: sudo ./scripts/inject.sh [caminho_da_tabela]
#   padrao: ./pp_tables/unlock.pp
#
# A injeção é VOLÁTIL: some no reboot. Para persistir, use install.sh
# (instala o serviço systemd) ou chame apply.sh a cada boot.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TABELA="${1:-$SCRIPT_DIR/pp_tables/unlock.pp}"

# Auto-detecta o device amdgpu
find_amdgpu() {
    for card in /sys/class/drm/card*; do
        [ -d "$card/device/hwmon" ] || continue
        drv="$(basename "$(readlink -f "$card/device/driver" 2>/dev/null)" 2>/dev/null)"
        if [ "$drv" = "amdgpu" ]; then
            echo "$card/device"
            return 0
        fi
    done
    echo ""
}

PP_DIR="$(find_amdgpu)"
if [ -z "$PP_DIR" ]; then
    echo "ERROR: nenhum device amdgpu encontrado" >&2
    exit 1
fi

[ -f "$TABELA" ] || { echo "ERROR: tabela não encontrada: $TABELA" >&2; exit 1; }

echo "=== vega20-unlock — injeção de PowerPlay table ==="
echo "Device : $PP_DIR"
echo "Tabela : $TABELA ($(stat -c%s "$TABELA") bytes)"
echo ""

# Verifica ppfeaturemask
if grep -q 'amdgpu.ppfeaturemask' /proc/cmdline 2>/dev/null; then
    echo "[OK] ppfeaturemask ativo: $(grep -oP 'amdgpu\.ppfeaturemask=\K[0-9a-fA-Fx]+' /proc/cmdline)"
else
    echo "AVISO: amdgpu.ppfeaturemask NÃO está na linha de boot!"
    echo "       A interface pp_od_clk_voltage pode não aparecer."
fi

# Backup da tabela atual
mkdir -p "$SCRIPT_DIR/backups"
echo ""
echo "--- Backup da tabela atual ---"
dd if="$PP_DIR/pp_table" of="$SCRIPT_DIR/backups/pp_table_$(date +%Y%m%d_%H%M%S).bin" bs=1 count=1730 2>/dev/null || true
echo "[OK] backup salvo em backups/"

# Injeção
echo ""
echo "--- Injetando $TABELA ---"
cat "$TABELA" > "$PP_DIR/pp_table" || {
    echo "ERROR: falha ao escrever. Rode como root (sudo)." >&2
    exit 1
}
sleep 3

# Verificação
echo ""
echo "--- Estado pós-injeção (pp_od_clk_voltage) ---"
cat "$PP_DIR/pp_od_clk_voltage" 2>/dev/null && echo "" || echo "pp_od_clk_voltage não presente"
echo ""
echo "Se OD_SCLK/OD_MCLK/OD_VDDC_CURVE aparecem acima, o unlock funcionou."
