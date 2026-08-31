#!/bin/bash
set -euo pipefail

# vega20-unlock — injeta a tabela unlock (habilita overdrive)
# Uso: sudo ./scripts/apply.sh
# Por padrão NÃO força overclock (roda no boost padrão do driver).
# Para aplicar um OC, salve seu perfil no dashboard (tecla S) — isso
# seta ENABLE_OC=1 e seus valores em scripts/profile.conf.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TABELA="$SCRIPT_DIR/pp_tables/unlock.pp"
PROFILE="$SCRIPT_DIR/scripts/profile.conf"

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

# Espera o device amdgpu aparecer (no boot o driver pode demorar)
PP_DIR=""
for _ in $(seq 1 60); do
    PP_DIR="$(find_amdgpu)"
    [ -n "$PP_DIR" ] && break
    sleep 1
done
[ -n "$PP_DIR" ] || { echo "ERROR: device amdgpu não encontrado após 60s" >&2; exit 1; }
PP="$PP_DIR/pp_table"
OD="$PP_DIR/pp_od_clk_voltage"

[ -f "$TABELA" ] || { echo "ERROR: $TABELA não encontrada" >&2; exit 1; }

# 1. Reinjeta a tabela unlock (volátil, precisa a cada boot) — habilita o OD
cat "$TABELA" > "$PP"
sleep 4
echo "[OK] Tabela unlock injetada (overdrive habilitado)."

[ -f "$PROFILE" ] || { echo "AVISO: $PROFILE não encontrado — sem OC aplicado"; exit 0; }

# Encontra o hwmon amdgpu para o power limit
HWMON=""
for h in "$PP_DIR"/hwmon/hwmon*; do
    if [ "$(cat "$h/name" 2>/dev/null)" = "amdgpu" ]; then
        HWMON="$h"
        break
    fi
done

# 2. Aplica o power limit (sempre — do POWER_LIMIT no profile; template stock = 190W)
PL=$(grep -E '^POWER_LIMIT=' "$PROFILE" | cut -d= -f2 | tr -d '[:space:]')
PL=${PL:-190}
if [ -n "$HWMON" ] && [ -w "$HWMON/power1_cap" ]; then
    PL_MAX=$(( $(cat "$HWMON/power1_cap_max" 2>/dev/null) / 1000000 ))
    if [ "$PL" -gt "${PL_MAX:-0}" ]; then
        echo "  [aviso] power limit $PL W acima do max ${PL_MAX} W — usando $PL_MAX W"
        PL=$PL_MAX
    fi
    echo "$(( PL * 1000000 ))" > "$HWMON/power1_cap"
    echo "[OK] Power limit: $PL W"
else
    echo "[aviso] não foi possível ajustar power limit (hwmon não gravável)"
fi

# 3. Aplica OC apenas se o usuário salvou um perfil (ENABLE_OC=1)
ENABLE=$(grep -E '^ENABLE_OC=' "$PROFILE" | cut -d= -f2 | tr -d '[:space:]')
if [ "${ENABLE:-0}" != "1" ]; then
    echo "[OK] Nenhum perfil de OC salvo (ENABLE_OC!=1) — rodando no padrão do driver."
    echo "     Ajuste seu OC no dashboard (sudo python3 oc_dash.py) e aperte S para"
    echo "     aplicar no próximo boot."
    exit 0
fi

S=$(grep -E '^SCLK_BOOST=' "$PROFILE" | cut -d= -f2)
M=$(grep -E '^MCLK_BOOST=' "$PROFILE" | cut -d= -f2)
V0=$(grep -E '^VDDC_0=' "$PROFILE" | cut -d= -f2)
V1=$(grep -E '^VDDC_1=' "$PROFILE" | cut -d= -f2)
V2=$(grep -E '^VDDC_2=' "$PROFILE" | cut -d= -f2)

# Aplica o perfil de OC (cada write separado para sysfs)
echo "s 1 $S" > "$OD"
sleep 1
echo "vc 0 $V0" > "$OD"
sleep 1
echo "vc 1 $V1" > "$OD"
sleep 1
echo "vc 2 $V2" > "$OD"
sleep 1
echo 'c' > "$OD"

echo "[OK] OC aplicado (SCLK $S MHz). Verifique com verify.sh"
