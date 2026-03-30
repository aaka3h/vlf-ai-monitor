# 📡 VLF AI Monitor

RTL-SDR V4 + Local AI (Ollama) — Autonomous VLF band scanner (3-30 kHz). Detects and identifies global military naval VLF stations with local AI analysis and audio recording. No cloud, no API keys required.

## Stations Detected
- 🇮🇳 VTX — INS Kattabomman (Indian Navy nuclear submarine comms)
- 🇷🇺 Alpha — RSDN-20 (Russian Navy navigation)
- 🇨🇳 3SB — Datong (Chinese Navy PLAN)
- 🇧🇾 RDL — Molodechno (Russian Navy)
- 🇩🇪 DHO38 — Rhauderfehn (German Navy/NATO)

## Requirements
- RTL-SDR Blog V4 dongle
- Ollama with any local model

## Install
```bash
pip3 install pyrtlsdr numpy requests
ollama pull llama3.2
```

## Run
```bash
python3 vlf_ai_monitor.py
```

## Author
[@aaka3h](https://github.com/aaka3h)
