# vega20-unlock

Soft-unlock (sem flash de vBIOS) do controle de clock/voltagem (overdrive) para GPUs
**AMD Vega 20** — Radeon Pro VII e Radeon VII — no Linux, injetando uma PowerPlay table
modificada via sysfs, + um **dashboard interativo em tempo real** no terminal.

O vBIOS original permanece intacto (display, 6x DP, TDP etc. preservados).

> ⚠️ **Disclaimer**: overclock/undervolt pode causar instabilidade, crashes de display
> ou dano de hardware se mal configurado. Use por sua conta e risco. Este projeto
> modifica parâmetros do SMU via sysfs; os valores finais dependem do seu silicone.

---

## O problema

Na Radeon **Pro VII** (e em algumas VII), a AMD desabilita o overdrive no próprio
vBIOS: a subestrutura `OverDrive8Table` da `ATOM_Vega20_POWERPLAYTABLE` vem preenchida
com valores zerados. Por isso:

- `pp_od_clk_voltage` não expõe OD_SCLK/OD_VDDC_CURVE mesmo com `ppfeaturemask=0xffffffff`
- o teto de clock fica travado (na Pro VII, ~1700 MHz)

## A solução

Em vez de flashear o vBIOS, este projeto **reinjeta uma PowerPlay table modificada**
via sysfs (`/sys/class/drm/.../pp_table`). Isso re-habilita o overdrive em runtime.

### Por que injetar a tabela não bastava (correção importante)

O driver copia `ODSettingsMax/Min[]` para `od_settings_max/min[]` de forma **1:1, sem
reordenar** (`phm_copy_overdrive_settings_limits_array`), mas indexa esses arrays pelo
`enum OD8_SETTING_ID` enquanto a **tabela física** usa `ATOM_VEGA20_ODSETTING_ID` — duas
ordens diferentes. Consequência: o teto real do SCLK vinha de `ODSettingsMax[1]`
(FMIN físico ↔ `OD8_GFXCLK_FMAX`), não de `[0]`. Editar apenas `[0]` mantinha o teto
em 1700. As tabelas aqui já usam a indexação correta.

### Limite de voltagem

O sensor de borda e o SMU limitam a voltagem: `MaxVoltageGfx=4650`, `VOLTAGE_SCALE=4`
→ **máx real 1162 mV**. Valores acima disso fazem o driver desabilitar a feature de
curva inteira. As tabelas usam teto de 1160 mV.

---

## Requisitos

- Kernel Linux com amdgpu (Vega 20 / gfx906)
- `amdgpu.ppfeaturemask=0xffffffff` na linha de boot (ver abaixo)
- `python3` (para o dashboard; usa apenas stdlib, sem dependências)

---

## Passo 1 — Baixar / clonar o repositório

```bash
git clone https://github.com/DvDlVs/vega20-unlock.git
cd vega20-unlock
```

> Se não tiver o `git`, instale antes:
> ```bash
> sudo pacman -S git      # Arch / Manjaro
> sudo apt install git    # Debian / Ubuntu
> ```

---

## Passo 2 — Habilitar `ppfeaturemask` (necessário 1 vez, depois reboot)

O kernel precisa abrir a interface de overdrive. Adicione
`amdgpu.ppfeaturemask=0xffffffff` à linha de comando do kernel, **depois reinicie**.

### Manjaro / Arch com Limine

```bash
# 1. edita o arquivo de configuração
sudo nano /etc/default/limine
```

Dentro, na linha **padrão do kernel**, acrescente ao final do texto que já existe:

```
amdgpu.ppfeaturemask=0xffffffff
```

Por exemplo (a parte exata varia, mas o parâmetro é o mesmo):

```
KERNEL_CMDLINE[default]+="quiet nowatchdog splash rw rootflags=subvol=/@ root=UUID=xxxx amdgpu.ppfeaturemask=0xffffffff"
```

Salve (no `nano`: `Ctrl+O`, `Enter`, `Ctrl+X`) e **regenere as entradas de boot**:

```bash
sudo limine-update
```

### Arch com GRUB

Edit a linha `GRUB_CMDLINE_LINUX_DEFAULT` em `/etc/default/grub`, acrescente o
parâmetro, salve, e gere o novo `grub.cfg`:

```bash
sudo nano /etc/default/grub                 # adicionar o parâmetro
sudo grub-mkconfig -o /boot/grub/grub.cfg
```

### Debian / Ubuntu com GRUB

```bash
sudo nano /etc/default/grub      # adicionar o parâmetro
sudo update-grub
```

### EndeavourOS / Arch com systemd-boot

```bash
sudo nano /boot/loader/entries/arch.conf   # adicionar o parâmetro à linha "options"
```

Em todos os casos, **reinicie** para o parâmetro entrar em vigor:

```bash
sudo reboot
```

Depois do reboot, confirme que ativou:

```bash
grep -oP 'ppfeaturemask=\K[0-9a-fx]+' /proc/cmdline
# deve imprimir: 0xffffffff
```

---

## Passo 3 — Injetar a tabela unlock

Volte à pasta do repositório e injete a tabela em memória:

```bash
cd vega20-unlock
sudo ./scripts/inject.sh
```

Confira se o overdrive apareceu:

```bash
./scripts/verify.sh
# Você deve ver "OD_SCLK", "OD_MCLK" e "OD_VDDC_CURVE" presentes
```

---

## Passo 4 — Ajustar via dashboard (opcional, em tempo real)

```bash
cd vega20-unlock
sudo python3 oc_dash.py
```

O dashboard auto-detecta o device amdgpu e o hwmon, e exibe em tempo real: clocks
(real × boost), curva VDDC, consumo, power limit, temperaturas e modo DPM.

| Tecla | Ação |
|-------|------|
| `M` / `G` | alternar edição **VRAM (MCLK)** / **GPU (SCLK)** |
| `↑` / `↓` | subir/descer clock no modo ativo (25 MHz) |
| `PgUp` / `PgDn` | subir/descer voltagem da curva (5 mV) |
| `+` / `-` | subir/descer power limit (20 W) |
| `F` | alternar modo DPM: Auto / Clock mín / Clock máx |
| `Space` | reset: 1700 MHz, 1000 MHz, 940 mV, 190 W |
| `S` | **salvar** o perfil atual em `scripts/profile.conf` e habilitar (seta `ENABLE_OC=1`) |
| `Q` | sair |

---

## Passo 5 — Persistir no boot (aplicar sozinho toda vez que ligar)

A injeção é **volátil** (some no reboot). Para aplicar automaticamente no boot:

```bash
cd vega20-unlock
sudo ./install.sh
```

O serviço espelha o repo em `/opt/vega20-unlock`, reinjeta a tabela a cada boot e
**habilita o overdrive**. Por padrão ele **NÃO força overclock** — o chip roda no
boost padrão do driver, porque nem toda Vega 20 aguenta os mesmos valores.

### Ajustar o perfil do boot (opcional, para o SEU chip)

**Do jeito mais fácil — pelo dashboard:**

```bash
cd vega20-unlock
sudo python3 oc_dash.py
```

1. Ajuste clock/voltagem/power até ficar do seu agrado (teclas `G`/`M`, `↑/↓`, `PgUp/PgDn`, `+/-`)
2. Aperte **`S`** para salvar. Isso seta `ENABLE_OC=1` e grava seus valores
   (incluindo o power limit atual) — o serviço passa a aplicar esse perfil no próximo boot.

Os valores ficam em (no sistema instalado):

```bash
sudo nano /opt/vega20-unlock/scripts/profile.conf
```

> A tecla `S` grava sempre no mesmo lugar que o boot carrega: em
> `/opt/vega20-unlock/scripts/profile.conf` quando o serviço está instalado, senão em
> `scripts/profile.conf` do diretório onde o dashboard está rodando (veja a linha
> `Perfil (S)` no painel). Assim o perfil salvo sempre tem efeito no boot.

Para reaplicar o perfil na hora, sem reiniciar:

```bash
sudo systemctl restart vega20-unlock
```

> Quer voltar ao padrão de fábrica? Rode `restore.sh` (volta ao stock e remove o
> serviço) ou edite `profile.conf` colocando `ENABLE_OC=0`.

> **Instalação limpa = stock.** O `profile.conf` de exemplo que vem com o projeto
> (e que `install.sh` copia) traz `ENABLE_OC=0`, `SCLK_BOOST=1700` (940 mV) e
> `POWER_LIMIT=190 W` — ou seja, ao instalar nada de overclock é forçado; você ajusta
> o seu perfil no dashboard e aperta `S`.

---

## Desinstalar / voltar ao stock

```bash
cd vega20-unlock
sudo ./scripts/restore.sh
```

Isso restaura a tabela stock em memória, remove o serviço systemd e reseta o overdrive.
Um reboot deixa tudo como era originalmente.

---

## Scripts

| Arquivo | Função |
|---------|--------|
| `scripts/inject.sh` | reinjeta a tabela unlock em memória |
| `scripts/apply.sh` | injeta a tabela; aplica o **power limit** (`POWER_LIMIT`, padrão 190 W) sempre e o perfil de `profile.conf` só se `ENABLE_OC=1` |
| `scripts/profile.conf` | **perfil de OC** (padrão `ENABLE_OC=0` = sem OC, 1700 MHz/940 mV/190 W; tecla `S` do dash seta `1`) |
| `scripts/verify.sh` | confere OD/ppfeaturemask/hwmon |
| `scripts/restore.sh` | restaura stock + desinstala serviço |
| `oc_dash.py` | dashboard interativo |
| `install.sh` | instala o serviço systemd de boot |

## Tabelas (pp_tables/)

| Arquivo | Conteúdo |
|---------|----------|
| `stock.pp` | PowerPlay table original da Pro VII (OD desabilitado) |
| `unlock.pp` | PowerPlay table com OD habilitado (perfil opcional em `scripts/profile.conf`) |

Estas são tabelas **Vega 20** (1730 bytes, `ATOM_Vega20_POWERPLAYTABLE`). Em outras
GPUs/boards podem variar; use com cuidado.

---

## Licença

MIT — veja [LICENSE](LICENSE).
