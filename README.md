# 📡 VLF AI Monitor

> Autonomous VLF band scanner powered by RTL-SDR V4 and a local AI model. Detects global military naval VLF stations and cross-verifies every signal against a remote KiwiSDR receiver in real time.

No cloud. No API keys. Runs entirely on your machine.

---

## How It Works

```
RTL-SDR V4 scans 3–30 kHz continuously
        ↓
Signal passes 6-stage noise filter pipeline
        ↓
Nearest KiwiSDR receiver (auto-selected) checks same frequency
        ↓
Both receivers confirm → INDEPENDENTLY VERIFIED REAL SIGNAL
```

Single-receiver SDR setups can't distinguish real signals from local interference. This tool solves that by automatically querying a remote KiwiSDR in another country and comparing results in parallel.

---

## Signals Detected

| Station | Frequency | Country | Operator | Purpose |
|---------|-----------|---------|----------|---------|
| VTX — INS Kattabomman | 17.0 kHz | 🇮🇳 India | Indian Navy | Nuclear submarine comms |
| Alpha — RSDN-20 | 11.9 kHz | 🇷🇺 Russia | Russian Navy | Navigation + submarine |
| 3SB — Datong | 20.6 kHz | 🇨🇳 China | PLAN Navy | Submarine comms |
| RDL — Molodechno | 18.1 kHz | 🇧🇾 Belarus | Russian Navy | Submarine comms |
| DHO38 — Rhauderfehn | 23.4 kHz | 🇩🇪 Germany | German Navy/NATO | NATO submarine comms |
| NAA — Cutler | 24.0 kHz | 🇺🇸 USA | US Navy | Nuclear submarine comms |
| NWC — Harold E. Holt | 19.8 kHz | 🇦🇺 Australia | US/RAN Navy | Indian Ocean submarine comms |

---

## Features

- **6-stage noise filter** — rejects 50Hz harmonics, broadband interference, frequency-unstable signals, and single-scan spikes
- **Auto location + nearest KiwiSDR** — detects your location from IP and picks the closest available remote receiver
- **Parallel cross-verification** — queries remote KiwiSDR in ~7 seconds while continuing to scan
- **Local AI analysis** — Ollama LLM analyzes every confirmed signal with no internet required
- **Audio recording** — saves a WAV file for each detected signal
- **35-station database** — covers naval VLF stations across 14 countries
- **Session logging** — JSON logs organized by session, country, and detection number

---

## Noise Filter Pipeline

```
[1] 50Hz harmonic rejection   → eliminates power supply noise, LED drivers, switching regulators
[2] Bandwidth check           → real VLF stations are narrow (<150 Hz); interference is wide
[3] Frequency stability       → real stations hold frequency; local oscillators drift
[4] Persistence check         → signal must appear across multiple consecutive scans
[5] Confidence scoring        → composite score from SNR, bandwidth, and database match
[6] Duplicate suppression     → prevents re-reporting the same signal within 60 seconds
```

---

## KiwiSDR Pool

The tool automatically selects the nearest available KiwiSDR from this pool based on your IP geolocation:

| Location | Country |
|----------|---------|
| Singapore | 🇸🇬 |
| Tokyo, Japan | 🇯🇵 |
| Sydney, Australia | 🇦🇺 |
| Zakroczym, Poland | 🇵🇱 |
| Nuremberg, Germany | 🇩🇪 |
| Helsinki, Finland | 🇫🇮 |
| Canaan, USA | 🇺🇸 |

---

## Requirements

**Hardware:**
- RTL-SDR Blog V4 dongle
- Wire antenna (longer is better for VLF — try 5–10 meters)

**Dependencies:**
```bash
pip3 install pyrtlsdr numpy requests
git clone https://github.com/jks-prv/kiwiclient.git ~/kiwiclient
```

**Local AI (no internet required):**
```bash
# Install Ollama from https://ollama.com
ollama pull llama3.2
```

---

## Installation

```bash
git clone https://github.com/aaka3h/vlf-ai-monitor.git
cd vlf-ai-monitor
ollama serve &
python3 vlf_ai_monitor.py
```

On startup the tool will auto-detect your location, select the nearest KiwiSDR, calibrate the local noise floor, and begin scanning.

---

## Best Reception Times

VLF signals travel further at night due to ionospheric reflection. Daytime absorption significantly reduces signal strength.

```
Best    → 10 PM – 6 AM local time
Good    → 5 AM – 9 AM local time
Worst   → 10 AM – 6 PM local time
```

---

## Sample Output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[02:14:38] 📡 SIGNAL #3  ● 91% confidence
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Frequency  : 17.000 kHz
SNR        : 34.3 dB above noise floor
Bandwidth  : 12.4 Hz

DATABASE MATCH
🇮🇳  VTX  —  INS Kattabomman
Operator : Indian Navy  |  Power: 500 kW  |  Mode: MSK
Purpose  : Nuclear submarine communication
Distance : 1,247 km

🌍 CROSS-VERIFICATION
  ✅ Singapore KiwiSDR    RSSI: -104.2 dBm  (+7.8 dB vs noise)
  VERDICT: REAL SIGNAL — independently confirmed

🤖 AI ANALYSIS
IDENTIFICATION: INS Kattabomman VTX 17.0 kHz — Indian Navy VLF
CONFIDENCE: 95%
MODE: MSK
VERDICT: CONFIRMED SIGNAL
```

---

## Disclaimer

This tool receives publicly broadcast radio signals in the VLF spectrum. Monitoring VLF transmissions is legal in most jurisdictions. No signal content is decrypted or intercepted — only carrier frequency and signal strength are measured.

---

## Contributing

Pull requests welcome. If you have a KiwiSDR to add to the pool or a VLF station missing from the database, open an issue.

## License

MIT
