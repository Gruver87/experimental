# Observability Stack

Мониторинг узла: Prometheus + Grafana.

## Быстрый старт

**Терминал 1** — нода:

```bash
python main.py
```

**Терминал 2** — мониторинг:

```bash
docker compose -f docker-compose.observability.yml up -d
```

## URL

| Сервис | URL | Логин |
|--------|-----|-------|
| Grafana | http://localhost:3000 | admin / admin |
| Prometheus | http://localhost:9090 | — |
| Node metrics | http://localhost:8080/metrics | — |

## Метрики

- `abs_uptime_seconds` — uptime
- `abs_chain_height` — высота цепи
- `abs_peers_connected` — P2P пиры
- `abs_mempool_size` — мемпул
- `abs_mempool_store_demoted` / `abs_mempool_store_demote_count` / `abs_mempool_store_backend` — demote honesty (Wave E)
- `abs_p2p_under_mesh` / `abs_p2p_sync_status` / `abs_p2p_peer_sync_gap` — mesh honesty (Wave D)
- `abs_http_requests_total` — HTTP запросы
- `abs_errors_total` — ошибки API
- `abs_native_crypto_available` / `abs_native_crypto_self_test` — состояние PyO3/Rust crypto
- `abs_rust_bridge_required` / `abs_rust_bridge_ok` — production readiness Rust bridge CLI

## Алерты

Файл: `deploy/prometheus/alerts.yml`

- `AbsoluteNodeDown` — нода недоступна 2m
- `AbsoluteNoPeers` — 0 пиров 10m
- `AbsoluteMempoolBacklog` — mempool > 500
- `AbsoluteHighErrorRate` — рост ошибок
- `AbsoluteRustBridgeDown` — production Rust bridge не прошёл JSON smoke-test
- `AbsoluteMempoolStoreDemoted` — Rust mempool store demoted 5m (Wave E/F)
- `AbsoluteMempoolStoreDemoteBurst` — demote_count increase in 1h
- `AbsoluteP2PUnderMesh` — under_mesh 15m (Wave D/F; longer `for` to reduce soft flaps)

Prometheus **оценивает** правила; для Telegram/email нужен **Alertmanager** (ещё не в compose) или внешний uptime.

### Локальный health watch (без Alertmanager)

```powershell
# Prod mesh :18180-18182, лог в logs/health_watch.log
.\scripts\health_watch.ps1 -ProdMesh -IntervalSec 300

# С webhook (Slack-compatible JSON), env или параметр:
$env:HEALTH_WEBHOOK_URL = "https://hooks.slack.com/services/..."
.\scripts\health_watch.ps1 -ProdMesh -DurationMin 1440
```

Проверяет: `/health/ready`, `/status`, `/chain/consistency/harness` на каждом порту.

## JSON-логи

```bash
LOG_JSON=true python main.py
# data/node.log — одна JSON-строка на событие
```

Подходит для Loki, ELK, CloudWatch.
