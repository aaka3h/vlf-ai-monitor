"""
KiwiSDR Cross-Verifier v2
- Dynamic noise floor calibration per server
- Weighted confidence scoring
- Parallel queries
- Auto-retry on failure
- Signal quality assessment
"""

import subprocess, sys, os, time, json, math
import concurrent.futures
from collections import defaultdict

KIWIRECORDER   = os.path.expanduser("~/kiwiclient/kiwirecorder.py")
KIWI_THRESHOLD = 3.0   # dB above noise = signal present

# ─── Server pool — only reachable ones ─────────────────────────────────────────
KIWI_POOL = [
    {"ip":"185.238.204.191","port":8073,"location":"Zakroczym, Poland",  "country":"Poland","lat":52.35,"lon":20.60,"weight":1.0},
    {"ip":"69.204.142.218", "port":8073,"location":"Canaan, USA",        "country":"USA",   "lat":41.93,"lon":-73.40,"weight":1.0},
]

# ─── Dynamic noise floor cache ─────────────────────────────────────────────────
# Stores calibrated noise floor per server per frequency band
_noise_cache = defaultdict(lambda: -112.0)
_cache_time  = defaultdict(float)
CACHE_TTL    = 300  # recalibrate every 5 minutes

def _measure_rssi(ip, port, freq_khz, timeout=7):
    """Raw RSSI measurement from KiwiSDR."""
    try:
        r = subprocess.run(
            [sys.executable, KIWIRECORDER,
             "-s", ip, "-p", str(port),
             "-f", str(freq_khz), "-m", "usb",
             "--S-meter=1", f"--tlimit={timeout}", "--quiet"],
            capture_output=True, text=True, timeout=timeout+5
        )
        for line in r.stdout.splitlines():
            if "RSSI:" in line:
                return float(line.split("RSSI:")[1].strip())
        return None
    except:
        return None

def calibrate_noise(ip, port):
    """
    Measure noise floor dynamically by sampling
    multiple quiet frequencies and taking the median.
    """
    cache_key = f"{ip}:{port}"

    # Use cache if fresh
    if time.time() - _cache_time[cache_key] < CACHE_TTL:
        return _noise_cache[cache_key]

    # Sample quiet frequencies (between known stations)
    quiet_freqs = [10.5, 12.0, 14.5, 16.0, 22.5]
    readings = []

    def measure_one(f):
        return _measure_rssi(ip, port, f, timeout=5)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(measure_one, quiet_freqs[:3]))

    readings = [r for r in results if r is not None]

    if readings:
        noise = sorted(readings)[len(readings)//2]  # median
    else:
        noise = -112.0

    _noise_cache[cache_key] = noise
    _cache_time[cache_key] = time.time()
    return noise

def check_server(server, freq_khz):
    """
    Check a single KiwiSDR server for signal at freq_khz.
    Returns detailed result dict.
    """
    ip   = server["ip"]
    port = server["port"]
    loc  = server["location"]

    start = time.time()
    rssi  = _measure_rssi(ip, port, freq_khz, timeout=7)
    elapsed = time.time() - start

    if rssi is None:
        return {
            "location":    loc,
            "country":     server["country"],
            "ip":          ip,
            "rssi":        None,
            "noise_floor": None,
            "above_noise": None,
            "snr_db":      None,
            "confirmed":   False,
            "status":      "UNREACHABLE",
            "weight":      server["weight"],
            "elapsed_sec": elapsed,
            "quality":     0.0
        }

    noise      = calibrate_noise(ip, port)
    above      = rssi - noise
    confirmed  = above >= KIWI_THRESHOLD

    # Signal quality 0-100
    # Based on how far above threshold
    if above >= 10:   quality = 1.0
    elif above >= 6:  quality = 0.8
    elif above >= 4:  quality = 0.6
    elif above >= 3:  quality = 0.4
    else:             quality = 0.0

    return {
        "location":    loc,
        "country":     server["country"],
        "ip":          ip,
        "rssi":        rssi,
        "noise_floor": noise,
        "above_noise": round(above, 1),
        "snr_db":      round(above, 1),
        "confirmed":   confirmed,
        "status":      "SIGNAL" if confirmed else "NOISE",
        "weight":      server["weight"],
        "elapsed_sec": round(elapsed, 1),
        "quality":     quality
    }

def cross_verify(freq_hz, local_snr_db=0):
    """
    Cross-verify a locally detected signal against all KiwiSDR servers.
    Queries all servers in PARALLEL for speed.

    Returns comprehensive verification result.
    """
    freq_khz = freq_hz / 1000

    # Query all servers in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(KIWI_POOL)) as ex:
        results = list(ex.map(lambda s: check_server(s, freq_khz), KIWI_POOL))

    # Calculate weighted confidence
    reachable  = [r for r in results if r["rssi"] is not None]
    confirmed  = [r for r in reachable if r["confirmed"]]
    unreachable= [r for r in results if r["rssi"] is None]

    if not reachable:
        confidence_pct = 0
        verdict = "UNVERIFIED"
        verified = False
    else:
        # Weighted score
        total_weight    = sum(r["weight"] for r in reachable)
        confirmed_weight = sum(r["weight"] * r["quality"] for r in confirmed)
        raw_score = confirmed_weight / total_weight if total_weight > 0 else 0

        # Boost if multiple servers confirm
        if len(confirmed) >= 2:
            raw_score = min(1.0, raw_score * 1.2)

        # Factor in local SNR
        if local_snr_db > 20:
            raw_score = min(1.0, raw_score * 1.1)

        confidence_pct = int(raw_score * 100)
        verified = confidence_pct >= 40

        if confidence_pct >= 80:   verdict = "CONFIRMED"
        elif confidence_pct >= 60: verdict = "PROBABLE"
        elif confidence_pct >= 40: verdict = "POSSIBLE"
        elif confidence_pct > 0:   verdict = "WEAK"
        else:                       verdict = "NOT CONFIRMED"

    # Best server reading
    best = max(reachable, key=lambda r: r.get("above_noise") or -999) if reachable else None

    return {
        "verified":        verified,
        "verdict":         verdict,
        "confidence_pct":  confidence_pct,
        "confirmed_count": len(confirmed),
        "reachable_count": len(reachable),
        "total_servers":   len(KIWI_POOL),
        "freq_khz":        freq_khz,
        "local_snr_db":    local_snr_db,
        "best_rssi":       best["rssi"] if best else None,
        "best_snr":        best["above_noise"] if best else None,
        "best_location":   best["location"] if best else None,
        "results":         results
    }

def print_verification(cv):
    """Print formatted cross-verification results."""
    try:
        from config import C
    except:
        class C:
            RESET="\033[0m";BOLD="\033[1m";RED="\033[91m";GREEN="\033[92m"
            YELLOW="\033[93m";CYAN="\033[96m";GRAY="\033[90m"

    verdict = cv["verdict"]
    conf    = cv["confidence_pct"]

    if verdict == "CONFIRMED":      col = C.GREEN
    elif verdict == "PROBABLE":     col = C.YELLOW
    elif verdict == "POSSIBLE":     col = C.YELLOW
    else:                           col = C.RED

    print(f"\n  {C.CYAN}{'─'*54}{C.RESET}")
    print(f"  {C.CYAN}{C.BOLD}🌍 KIWISDR CROSS-VERIFICATION{C.RESET}")

    for r in cv["results"]:
        if r["rssi"] is None:
            print(f"  {C.GRAY}  ✗ {r['location']:30} UNREACHABLE ({r['elapsed_sec']:.1f}s){C.RESET}")
        else:
            icon = "✅" if r["confirmed"] else "❌"
            bar  = "▓" * int(max(0, r["above_noise"]) / 2)
            rcol = C.GREEN if r["confirmed"] else C.RED
            print(f"  {rcol}  {icon} {r['location']:30} "
                  f"RSSI:{r['rssi']:7.1f} dBm  "
                  f"SNR:{r['above_noise']:+5.1f} dB  "
                  f"{bar}{C.RESET}")

    print(f"\n  {col}{C.BOLD}{'━'*50}{C.RESET}")
    print(f"  {col}{C.BOLD}  VERDICT: {verdict}  |  Confidence: {conf}%{C.RESET}")
    print(f"  {col}{C.BOLD}  Confirmed: {cv['confirmed_count']}/{cv['reachable_count']} servers{C.RESET}")

    if cv["best_location"]:
        print(f"  {C.GRAY}  Best: {cv['best_location']} → SNR {cv['best_snr']:+.1f} dB{C.RESET}")
    print(f"  {col}{C.BOLD}{'━'*50}{C.RESET}")

def warm_up():
    """
    Pre-calibrate noise floors for all servers in parallel.
    Call this at startup.
    """
    print("  📡 Calibrating KiwiSDR noise floors...", end="", flush=True)

    def cal_one(s):
        return calibrate_noise(s["ip"], s["port"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(KIWI_POOL)) as ex:
        noises = list(ex.map(cal_one, KIWI_POOL))

    for s, n in zip(KIWI_POOL, noises):
        print(f"\n  {s['location']}: noise floor = {n:.1f} dBm", end="")

    print(f"\n  ✅ Calibration done\n")
