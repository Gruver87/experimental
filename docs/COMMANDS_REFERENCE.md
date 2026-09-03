# Absolute Blockchain — Справочник команд

> **Полный список (без секретов):** [`ALL_COMMANDS.txt`](ALL_COMMANDS.txt)  
> **Личная копия (Desktop):** `Absolute_Blockchain_All_Commands_FIXED.txt`  
> **Бэкап Desktop:** `Absolute_Blockchain_All_Commands_FIXED.bak_20260828.txt`  
> **Секреты:** только `.env` — [`secrets/README.md`](../secrets/README.md)

| | |
|---|---|
| **Обновлено** | 2026-08-28 |
| **Репозитории** | [Experimental](https://github.com/Gruver87/experimental) (R&D) · [Hybrid](https://github.com/Gruver87/Absolute_Blockchain_Ultimate_Hybrid) (audit pin) |
| **Entry** | `python main.py` / `.\scripts\start_node.ps1` |
| **Статус** | R&D / prod-profile mesh — **не** public audited mainnet |

---

## Честно

- Gate green ≠ public mainnet
- Prod mesh `778888` = industrial profile, не публичный mainnet
- Bridge на live mesh: **OFF**
- libp2p 48h — **PASS** evidence: [`evidence/runs/3c801b87/`](evidence/runs/3c801b87/) · [`EVIDENCE_MATRIX.md`](EVIDENCE_MATRIX.md)
- Council 87 NFT — staging `778889`, **не** L1 security guarantee

Доказательства: [`EVIDENCE_MATRIX.md`](EVIDENCE_MATRIX.md) · [`EXECUTION_ORDER.md`](EXECUTION_ORDER.md) · [`MAINNET_GAP_ANALYSIS.md`](MAINNET_GAP_ANALYSIS.md)

---

## L1 Integration Gate [обязательно после core/P2P/sync]

```powershell
cd C:\Users\vovun\Desktop\Absolute_Blockchain_Experimental
.\scripts\build_native.ps1
.\scripts\docker_prod_3node.ps1 -SkipBuild -KeepVolumes
.\scripts\probe_prod_mesh.ps1 -Quick
python scripts/industrial_gate.py
```

---

## Быстрый старт

### Experimental (R&D mesh, libp2p)

```powershell
cd C:\Users\vovun\Desktop\Absolute_Blockchain_Experimental
pip install -r requirements.txt
.\scripts\build_native.ps1
.\scripts\docker_prod_3node.ps1 -SkipBuild -KeepVolumes
.\scripts\probe_prod_mesh.ps1 -Quick
```

### Hybrid (audit pin, TCP+TLS)

```powershell
cd C:\Users\vovun\Desktop\Absolute_Blockchain_Ultimate_Hybrid
.\scripts\build_native.ps1
.\scripts\start_all.ps1 -SkipBuild -KeepVolumes
```

---

## Порты

| Что | Порт / URL |
|-----|------------|
| Solo REST | `http://localhost:8080` |
| Prod mesh | `:18180`–`:18182` |
| Staging APP (NFT council) | `http://127.0.0.1:19080` (Experimental) |
| Chain ID prod mesh | `778888` |
| Chain ID council staging | `778889` |

---

## Оглавление `ALL_COMMANDS.txt`

| Часть | Тема |
|------:|------|
| 0–23 | Старт, devnet, API, bridge, prod mesh, gate, soak, DR, ceremony |
| 24 | Секреты — **только имена** (значения в `.env`) |
| 25–27 | Git, сценарии дня, устаревшее |
| 28 | ADR 0016 profiles |
| 29 | Hybrid vs Experimental |
| 30 | **L1 Integration Gate** |
| 31 | Experimental R&D labs |
| 32 | **Gruver87 Council NFT** (ADR 0022) |

---

## Council NFT (Experimental, staging)

```powershell
python scripts/guarantor_council_manifest_gen.py
python scripts/guarantor_council_lab.py
docker compose -p abs-staging-app -f docker-compose.staging.app.yml up -d --build
python scripts/guarantor_council_staging_ceremony.py --dry-run
```

Документы: [`GRUVER87_COUNCIL_CHARTER.md`](GRUVER87_COUNCIL_CHARTER.md) · [`adr/0022-gruver87-genesis-council-governance.md`](adr/0022-gruver87-genesis-council-governance.md)

---

## R&D batch (без soak)

```powershell
python scripts/verify_parallel_rd_batch.py
```

---

## Перед git push

```powershell
python scripts/check_secrets.py
```

PowerShell: всегда `.\scripts\...` — не без пути.
