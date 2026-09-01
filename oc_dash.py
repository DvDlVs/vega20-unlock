#!/usr/bin/env python3
"""
vega20-unlock — OCR dashboard para AMD Vega 20 (Radeon Pro VII / Radeon VII)

Dashboard interativo (ncurses) para ajustar SCLK, MCLK, voltagem da curva VDDC,
power limit e DPM em tempo real via sysfs.

Requer root para escrever no sysfs:
    sudo python3 oc_dash.py
"""
import curses
from collections import deque
import glob
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Auto-detecta o primeiro device amdgpu (cardN/device com driver amdgpu)
def find_amdgpu_base():
    for card in sorted(glob.glob("/sys/class/drm/card*")):
        dev = os.path.join(card, "device")
        if not os.path.isdir(os.path.join(dev, "hwmon")):
            continue
        drv = os.path.realpath(os.path.join(dev, "driver"))
        if os.path.basename(drv) == "amdgpu":
            return dev
    return None

BASE = find_amdgpu_base() or "/sys/class/drm/card1/device"
OD = f"{BASE}/pp_od_clk_voltage"
PP = f"{BASE}/pp_table"

# Encontra o hwmon do amdgpu
def find_hwmon():
    for h in sorted(glob.glob(f"{BASE}/hwmon/hwmon*")):
        try:
            if open(os.path.join(h, "name")).read().strip() == "amdgpu":
                return h
        except Exception:
            pass
    return os.path.join(BASE, "hwmon", "hwmon1")

HWMON = find_hwmon()

# Tabela stock (original) para restaurar defaults
STOCK_PPT = os.path.join(SCRIPT_DIR, "pp_tables", "stock.pp")
# Tabela unlock (OD habilitado) — usada para reinjetar se necessário
UNLOCK_PPT = os.path.join(SCRIPT_DIR, "pp_tables", "unlock.pp")
# Perfil persistente aplicado no boot (lido pelo scripts/apply.sh)
# Se o serviço estiver instalado, o boot carrega de /opt — salva lá para
# a tecla S ter efeito real no boot. Senão, usa o perfil local do repo.
_LOCAL_PROFILE = os.path.join(SCRIPT_DIR, "scripts", "profile.conf")
_INSTALLED_PROFILE = "/opt/vega20-unlock/scripts/profile.conf"
PROFILE_CONF = _INSTALLED_PROFILE if os.path.isdir("/opt/vega20-unlock") else _LOCAL_PROFILE
PROFILE_SOURCE = "servico (aplica no boot)" if PROFILE_CONF == _INSTALLED_PROFILE else "repo local"

DPM_MODES = ["auto", "low", "high"]
DPM_LABELS = {
    "auto":  "Automatico (DPM dinamico)",
    "low":   "Clock minimo forcado",
    "high":  "Clock maximo forcado",
    "manual": "Manual",
    "profile_standard": "Perfil padrao",
    "profile_min_sclk": "Perfil min SCLK",
    "profile_min_mclk": "Perfil min MCLK",
    "profile_peak":     "Perfil pico",
}

def dpm_label(raw):
    return DPM_LABELS.get(raw, raw)

def read_file(p):
    try:
        with open(p) as f:
            return f.read().strip()
    except Exception:
        return ""

def read_int(p):
    v = read_file(p)
    try:
        return int(v)
    except Exception:
        return 0

def parse_od():
    txt = read_file(OD)
    data = {"sclk": [], "mclk": [], "curve": [], "range": {}}
    section = None
    for line in txt.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("OD_SCLK:"):
            section = "sclk"
        elif line.startswith("OD_MCLK:"):
            section = "mclk"
        elif line.startswith("OD_VDDC_CURVE:"):
            section = "curve"
        elif line.startswith("OD_RANGE:"):
            section = "range"
        elif section == "sclk" and "Mhz" in line:
            v = line.split(":")[1].split("Mhz")[0].strip()
            data["sclk"].append(int(v))
        elif section == "mclk" and "Mhz" in line:
            v = line.split(":")[1].split("Mhz")[0].strip()
            data["mclk"].append(int(v))
        elif section == "curve" and "Mhz" in line and "mV" in line:
            parts = line.split()
            clk = int(parts[1].replace("Mhz", ""))
            mv = int(parts[2].replace("mV", ""))
            data["curve"].append((clk, mv))
        elif section == "range" and ":" in line and "Mhz" in line:
            key, rest = line.split(":", 1)
            minv, maxv = rest.replace("Mhz", "").split()
            data["range"][key.strip()] = (int(minv), int(maxv))
    return data

def parse_range_index_text():
    txt = read_file(OD)
    out = {}
    for line in txt.splitlines():
        l = line.strip()
        if "VDDC_CURVE_SCLK[" in l and "Mhz" in l:
            idx = int(l.split("[")[1].split("]")[0])
            rest = l.split(":")[1].replace("Mhz", "").split()
            out[idx] = (int(rest[0]), int(rest[1]))
        elif "VDDC_CURVE_VOLT[" in l and "mV" in l:
            idx = int(l.split("[")[1].split("]")[0])
            rest = l.split(":")[1].replace("mV", "").split()
            key = ("volt", idx)
            out[key] = (int(rest[0]), int(rest[1]))
    return out

def write_od(lines):
    try:
        for line in lines:
            with open(OD, "w") as f:
                f.write(line + "\n")
        return True
    except Exception:
        return False

def apply(lines):
    return write_od(list(lines) + ["c"])

_POWER_SAMPLES = deque()

def get_state():
    s = {}
    s["sclk_now"] = read_int(f"{HWMON}/freq1_input") // 1000000
    s["mclk_now"] = read_int(f"{HWMON}/freq2_input") // 1000000
    now = time.time()
    WINDOW = 1.0
    _POWER_SAMPLES.append((now, read_int(f"{HWMON}/power1_input") // 1000000))
    while _POWER_SAMPLES and now - _POWER_SAMPLES[0][0] > WINDOW:
        _POWER_SAMPLES.popleft()
    s["power_w"] = sum(p for _, p in _POWER_SAMPLES) // max(len(_POWER_SAMPLES), 1)
    s["power_inst"] = read_int(f"{HWMON}/power1_input") // 1000000
    s["cap_w"] = read_int(f"{HWMON}/power1_cap") // 1000000
    s["cap_max"] = read_int(f"{HWMON}/power1_cap_max") // 1000000
    s["cap_min"] = read_int(f"{HWMON}/power1_cap_min") // 1000000
    s["temp_edge"] = read_int(f"{HWMON}/temp1_input") // 1000
    s["temp_junction"] = read_int(f"{HWMON}/temp2_input") // 1000
    s["temp_mem"] = read_int(f"{HWMON}/temp3_input") // 1000
    s["vddc_now"] = read_int(f"{HWMON}/in0_input")
    s["od"] = parse_od()
    s["odr"] = parse_range_index_text()
    s["force"] = read_file(f"{BASE}/power_dpm_force_performance_level")
    return s

def set_power_cap(w):
    cmax = read_int(f"{HWMON}/power1_cap_max") // 1000000
    w = max(0, min(cmax, w))
    try:
        with open(f"{HWMON}/power1_cap", "w") as f:
            f.write(str(w * 1000000))
        return w
    except Exception:
        return None

def set_dpm_level(level):
    try:
        with open(f"{BASE}/power_dpm_force_performance_level", "w") as f:
            f.write(level)
        return True
    except Exception:
        return False

def load_profile():
    d = {}
    try:
        with open(PROFILE_CONF) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    except Exception:
        pass
    return d

def save_profile(sclk, mclk, power, v0, v1, v2):
    text = (
        "# Perfil de OC gerado pelo dashboard (oc_dash.py, tecla S).\n"
        "# Aplicado no boot pelo scripts/apply.sh via serviço vega20-unlock.\n"
        "# Formato: chave=valor  (sem espaços ao redor do =)\n"
        "# Salvar aqui seta ENABLE_OC=1 lançando a aplicação no boot.\n"
        "ENABLE_OC=1\n"
        f"SCLK_BOOST={sclk}\n"
        f"MCLK_BOOST={mclk}\n"
        f"POWER_LIMIT={power}\n"
        f"VDDC_0={' '.join(str(x) for x in v0)}\n"
        f"VDDC_1={' '.join(str(x) for x in v1)}\n"
        f"VDDC_2={' '.join(str(x) for x in v2)}\n"
    )
    try:
        with open(PROFILE_CONF, "w") as f:
            f.write(text)
        return True
    except Exception:
        return False

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(0)
    stdscr.timeout(80)

    st = get_state()
    od = st["od"]
    sclk_boost = od["sclk"][1] if len(od["sclk"]) >= 2 else 1900
    mclk_boost = od["mclk"][1] if len(od["mclk"]) >= 2 else 1000
    v0 = list(od["curve"][0]) if len(od["curve"]) > 0 else [860, 759]
    v1 = list(od["curve"][1]) if len(od["curve"]) > 1 else [1280, 824]
    v2 = list(od["curve"][2]) if len(od["curve"]) > 2 else [1900, 1031]
    my_volt = v2[1]
    my_power = st["cap_w"]
    edit_mode = "sclk"

    try:
        sclk_min, sclk_max = od["range"].get("SCLK", (500, 2300))
    except Exception:
        sclk_min, sclk_max = 500, 2300
    try:
        mclk_min, mclk_max = od["range"].get("MCLK", (800, 1500))
    except Exception:
        mclk_min, mclk_max = 800, 1500

    last_err = ""
    last_status = "pronto"

    while True:
        st = get_state()
        od = st["od"]

        stdscr.erase()
        h, w = stdscr.getmaxyx()
        title = " vega20-unlock — OC Dashboard "
        if w > 2:
            stdscr.addstr(0, (w - len(title)) // 2, title, curses.A_REVERSE)

        stdscr.addstr(2, 2, f"SCLK boost   : {sclk_boost:5d} MHz   (real: {st['sclk_now']:4d} MHz)")
        stdscr.addstr(3, 2, f"MCLK boost   : {mclk_boost:5d} MHz   (real: {st['mclk_now']:4d} MHz)")
        stdscr.addstr(4, 2, f"Voltagem pt2 : {my_volt:5d} mV    (real: {st['vddc_now']:5d} mV)")
        curve_last = od["curve"][-1] if od["curve"] else (0, 0)
        stdscr.addstr(5, 2, f"Curva (cur)  : pt0 {od['curve'][0] if len(od['curve'])>0 else (0,0)}  pt1 {od['curve'][1] if len(od['curve'])>1 else (0,0)}  pt2 {curve_last}")
        stdscr.addstr(6, 2, f"Power cap    : {st['cap_w']:3d} W    (media 1s: {st['power_w']:3d} W, max: {st['cap_max']} W)")
        stdscr.addstr(7, 2, f"Modo clock   : {dpm_label(st['force'])}")
        stdscr.addstr(8, 2, f"Temperaturas : edge {st['temp_edge']:3d}C   junction/hotspot {st['temp_junction']:3d}C   mem {st['temp_mem']:3d}C")
        stdscr.addstr(9, 2, f"Ranges       : SCLK {od['range'].get('SCLK', ('?','?'))[0]}-{od['range'].get('SCLK',('?','?'))[1]}  MCLK {od['range'].get('MCLK',('?','?'))[0]}-{od['range'].get('MCLK',('?','?'))[1]}")
        stdscr.addstr(10, 2, f"Editando     : {'VRAM (MCLK)' if edit_mode=='mclk' else 'GPU (SCLK)'}", curses.A_BOLD)
        stdscr.addstr(11, 2, f"Perfil (S)   : {PROFILE_SOURCE}", curses.A_BOLD)

        stdscr.addstr(13, 2, "Teclas:", curses.A_BOLD)
        keys = [
            "  M / G . . . . . .  alternar edicao VRAM (MCLK) / GPU (SCLK)",
            "  Seta cima/baixo . . subir/descer clock (modo ativo)",
            "  PgUp / PgDn . . . . subir/descer voltagem (curva pt2)",
            "  [+] / [-] . . . .  subir/descer power cap",
            "  F . . . . . . . .  alternar modo clock (auto/baixo/alto)",
            "  Espaco . . . . . . reset: 1700MHz, 1000Mhz, 940mV, 190W, auto",
            "  S . . . . . . . .  salvar perfil atual p/ aplicar no boot",
            "  Q . . . . . . . .  sair",
        ]
        for i, k in enumerate(keys):
            if 14 + i < h:
                stdscr.addstr(14 + i, 4, k)

        if 23 < h:
            stdscr.addstr(23, 2, f"Status: {last_status}")
        if last_err:
            stdscr.addstr(2, 50, f"ERRO: {last_err[:30]}", curses.A_BOLD)

        stdscr.refresh()

        key = stdscr.getch()
        if key in (ord("q"), ord("Q")):
            break

        if key in (curses.KEY_UP, curses.KEY_DOWN):
            step = 25
            if edit_mode == "mclk":
                if key == curses.KEY_UP:
                    mclk_boost = min(mclk_max, mclk_boost + step)
                else:
                    mclk_boost = max(mclk_min, mclk_boost - step)
                ok = apply([f"m 1 {mclk_boost}"])
                last_status = f"m 1 {mclk_boost} -> " + ("OK" if ok else "FALHOU")
                if not ok:
                    last_err = f"mclk {mclk_boost} rejeitado"
                    mclk_boost = od["mclk"][1] if len(od["mclk"]) >= 2 else mclk_boost
            else:
                if key == curses.KEY_UP:
                    sclk_boost = min(sclk_max, sclk_boost + step)
                else:
                    sclk_boost = max(sclk_min, sclk_boost - step)
                ok = apply([f"s 1 {sclk_boost}"])
                last_status = f"s 1 {sclk_boost} -> " + ("OK" if ok else "FALHOU")
                if not ok:
                    last_err = f"sclk {sclk_boost} rejeitado"
                    sclk_boost = od["sclk"][1] if len(od["sclk"]) >= 2 else sclk_boost
                else:
                    v2[0] = sclk_boost

        elif key in (ord("m"), ord("M"), ord("g"), ord("G")):
            if key in (ord("m"), ord("M")):
                edit_mode = "mclk"
            else:
                edit_mode = "sclk"
            last_status = f"editando: {'VRAM (MCLK)' if edit_mode=='mclk' else 'GPU (SCLK)'}"

        elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE):
            step = 5
            vrng = st["odr"].get(("volt", 0), (750, 1160))
            if key == curses.KEY_PPAGE:
                my_volt = min(vrng[1], my_volt + step)
            else:
                my_volt = max(vrng[0], my_volt - step)
            ok = apply([f"s 1 {sclk_boost}", f"vc 2 1900 {my_volt}"])
            last_status = f"volt pt2 {my_volt}mV -> " + ("OK" if ok else "FALHOU")
            if not ok:
                last_err = f"volt {my_volt} rejeitado"
                my_volt = od["curve"][-1][1] if od["curve"] else my_volt
            else:
                v2[1] = my_volt

        elif key in (ord("+"), ord("="), ord("-"), ord("_")):
            step = 20
            if key in (ord("+"), ord("=")):
                nw = set_power_cap(st["cap_w"] + step)
            else:
                nw = set_power_cap(st["cap_w"] - step)
            if nw is not None:
                my_power = nw
                last_status = f"power cap {nw}W"
            else:
                last_err = "falha ao ajustar power"

        elif key in (ord("f"), ord("F")):
            cur = st["force"]
            try:
                idx = DPM_MODES.index(cur)
            except ValueError:
                idx = -1
            nxt = DPM_MODES[(idx + 1) % len(DPM_MODES)]
            ok = set_dpm_level(nxt)
            last_status = f"modo clock: {dpm_label(nxt)}" if ok else "falha ao mudar DPM"

        elif key == ord(" "):
            apply(["s 1 1700", "m 1 1000", "vc 0 860 759", "vc 1 1280 824", "vc 2 1700 940"])
            time.sleep(1)
            set_power_cap(190)
            set_dpm_level("auto")
            my_power = 190
            sclk_boost = 1700
            mclk_boost = 1000
            my_volt = 940
            v2 = [1900, 940]
            last_status = "reset: 1700MHz, 1000Mhz, 940mV, 190W"

        elif key in (ord("s"), ord("S")):
            # Corrige coerência da curva: pt0 (idle) não pode ter voltagem
            # >= pt1, senão a GPU segura voltagem alta parada. Se desajustado,
            # baixa o pt0 para o patamar idle e avisa.
            corr = ""
            if v0[1] >= v1[1]:
                v0[1] = 759 if v1[1] > 759 else max(750, v1[1] - 1)
                corr = " [curva corrigida: VDDC_0 idle baixado]"
            ok_save = save_profile(sclk_boost, mclk_boost, my_power, v0, v1, v2)
            if ok_save:
                last_status = f"perfil salvo p/ {PROFILE_SOURCE} (aplicado no boot){corr}"
            else:
                last_err = f"falha ao salvar perfil em {PROFILE_CONF}"

        time.sleep(0.02)
    curses.endwin()

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
