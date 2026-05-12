# 🌌 SQM-OPD — Sky Quality Monitoring System

Sistema completo para aquisição, armazenamento, análise e visualização de dados de brilho do céu (SQM-LU), desenvolvido no contexto do Observatório do Pico dos Dias (LNA/MCTI).

## 🎯 Objetivos

- Medições automáticas de brilho do céu (zenital)
- Aquisição contínua (cadência de 1 minuto)
- Filtro astronômico (Sol e Lua)
- Estatísticas noturnas
- Arquivo histórico (SQLite + CSV)
- Visualização com Grafana
- Base para monitoramento científico e políticas públicas

---

## ⚙️ Requisitos

- Linux (openSUSE, Ubuntu, Fedora)
- Python ≥ 3.6
- SQM-LU (USB)
- Porta `/dev/ttyUSB*`

---

## 📦 Instalação

### 1. Clonar repositório

```bash
git clone https://github.com/SEU_USUARIO/sqm-opd.git
cd sqm-opd
