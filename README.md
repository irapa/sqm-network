# LNA SQM Network — Distributed Night-Sky Brightness Monitoring

Sistema distribuído para monitoramento contínuo do brilho do céu usando sensores **Unihedron SQM-LU**, com nós de aquisição em Raspberry Pi e servidor central para ingestão, banco de dados, Grafana e análise científica.

O projeto foi desenvolvido para apoiar o monitoramento do ambiente observacional do Observatório do Pico dos Dias (OPD/LNA), mas a arquitetura é genérica e pode ser usada em qualquer rede de sensores SQM.

## Visão geral da arquitetura

```text
SQM-LU
   ↓ USB
Raspberry Pi 4 / nó coletor
   ↓ coleta a cada 1 minuto
CSV local
   ↓ rsync/SSH a cada 5 minutos
Servidor central
   ↓ ingestão automática a cada 2 minutos
SQLite central
   ↓
Grafana / análise científica / QGIS
```

A Raspberry Pi funciona apenas como **nó de aquisição e buffer local**. O processamento, consolidação de dados, dashboards e análises devem rodar no servidor central.

## Funcionalidades

- Leitura automática do SQM-LU via USB serial;
- Cadência configurável, padrão de 60 s;
- Registro de tempo UTC/local, sensor, local, mag/arcsec², temperatura, Sol, Lua, fase lunar, `usable_dark_sky` e resposta bruta;
- CSV diário local no nó coletor;
- Sincronização via `rsync`/SSH;
- Banco SQLite central multiestação;
- Ingestão incremental com proteção contra duplicatas;
- Pronto para Grafana;
- Preparado para expansão para múltiplos sensores.

## Estrutura do repositório

```text
sqm-network/
├── collector/
│   ├── sqm_collector.py
│   ├── config.example.yaml
│   └── sync_to_server.example.sh
├── server/scripts/
│   └── ingest_csv.py
├── systemd/
│   ├── raspberry/
│   │   ├── sqm-collector.service
│   │   ├── sqm-sync.service
│   │   └── sqm-sync.timer
│   └── server/
│       ├── sqm-ingest.service
│       └── sqm-ingest.timer
├── grafana/sql/
├── docs/
├── requirements-node.txt
├── requirements-server.txt
├── LICENSE
└── README.md
```

## Instalação rápida

Leia em ordem:

1. [`docs/INSTALL.md`](docs/INSTALL.md)
2. [`docs/RASPBERRY_DEPLOY.md`](docs/RASPBERRY_DEPLOY.md)
3. [`docs/SERVER_SETUP.md`](docs/SERVER_SETUP.md)
4. [`docs/GRAFANA.md`](docs/GRAFANA.md)
5. [`docs/OPERATIONS.md`](docs/OPERATIONS.md)

## Estado inicial recomendado

```yaml
sensor_id: SQM_OPD_001
site_name: OPD
latitude: -22.5344
longitude: -45.5825
elevation_m: 1864
```

Para novas estações, altere `sensor_id`, `site_name`, coordenadas e diretório remoto.

## Licença

MIT License.

## Production deployment

The validated production layout, operational paths, health checks and
rollback procedure are documented in
[`docs/PRODUCTION_DEPLOYMENT.md`](docs/PRODUCTION_DEPLOYMENT.md).
