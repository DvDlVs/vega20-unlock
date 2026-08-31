#!/bin/bash
set -euo pipefail

# vega20-unlock — verifica o estado atual do unlock/OD
# Uso: ./scripts/verify.sh

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

echo "=== vega20-unlock — verificação ==="
echo "Device: $PP_DIR"
echo ""

echo "--- ppfeaturemask ---"
if grep -q 'amdgpu.ppfeaturemask' /proc/cmdline 2>/dev/null; then
    echo "[OK] $(grep -oP 'amdgpu\.ppfeaturemask=\K[0-9a-fA-Fx]+' /proc/cmdline)"
else
    echo "[FAIL] não está na linha de boot"
fi

echo ""
echo "--- pp_od_clk_voltage ---"
if [ -f "$PP_DIR/pp_od_clk_voltage" ]; then
    cat "$PP_DIR/pp_od_clk_voltage"
    for sec in OD_SCLK OD_MCLK OD_VDDC_CURVE OD_RANGE; do
        grep -q "$sec" "$PP_DIR/pp_od_clk_voltage" && echo "[OK] $sec presente"
    done
else
    echo "[FAIL] pp_od_clk_voltage não existe (unlock não aplicado ou boot sem ppfeaturemask)"
fi

echo ""
echo "--- hwmon ---"
for f in "$PP_DIR"/hwmon/hwmon*/power1_cap "$PP_DIR"/hwmon/hwmon*/temp1_input "$PP_DIR"/hwmon/hwmon*/temp2_input; do
    [ -f "$f" ] && echo "$(basename $f): $(cat $f)"
done 2>/dev/null || echo "N/A"

echo ""
echo "--- dmesg (últimas linhas amdgpu) ---"
dmesg 2>/dev/null | grep -i 'amdgpu\|powerplay\|overdrive' | tail -5 || echo "N/A"
