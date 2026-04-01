import datetime, subprocess, sys, os

KIWIRECORDER = os.path.expanduser("~/kiwiclient/kiwirecorder.py")
QUIET_FREQS = [10.2, 13.3, 16.8]

def get_time_quality():
    utc = datetime.datetime.utcnow().hour + datetime.datetime.utcnow().minute/60
    ist = (utc + 5.5) % 24
    if ist >= 22 or ist <= 5:   return "EXCELLENT 🌙", 1.5, ist
    elif ist <= 8:               return "GOOD 🌅", 1.2, ist
    elif ist <= 10:              return "FAIR 🌤️", 0.9, ist
    elif ist <= 17:              return "POOR ☀️", 0.6, ist
    elif ist <= 20:              return "FAIR 🌆", 0.8, ist
    else:                        return "GOOD 🌇", 1.1, ist

def measure_kiwi_noise(ip, port):
    readings = []
    for freq in QUIET_FREQS:
        try:
            r = subprocess.run(
                [sys.executable, KIWIRECORDER,
                 "-s", ip, "-p", str(port),
                 "-f", str(freq), "-m", "usb",
                 "--S-meter=1", "--tlimit=4", "--quiet"],
                capture_output=True, text=True, timeout=10)
            for line in r.stdout.splitlines():
                if "RSSI:" in line:
                    readings.append(float(line.split("RSSI:")[1].strip()))
        except: pass
    return min(readings) if readings else -112.0

def auto_tune_threshold(kiwi_ip, kiwi_port, lat=0.0, verbose=True):
    quality, factor, ist = get_time_quality()
    if verbose:
        print(f"  ⏰ Local time (IST) : {ist:.1f}h — {quality}")
    if verbose:
        print(f"  📊 Measuring noise floor...", end="", flush=True)
    noise = measure_kiwi_noise(kiwi_ip, kiwi_port)
    if verbose:
        print(f" {noise:.1f} dBm")
    if factor >= 1.3:   threshold = 5.5
    elif factor >= 1.0: threshold = 4.5
    elif factor >= 0.8: threshold = 3.5
    else:               threshold = 3.0
    if verbose:
        print(f"  📡 Auto SNR threshold : {threshold} dB")
        print(f"  💡 Best time to scan  : 10pm-5am IST (night)")
    return threshold, noise, quality

def get_best_scan_window():
    windows = []
    for h in range(24):
        ist = h
        if ist >= 22 or ist <= 5:   q,f = "EXCELLENT 🌙", 1.5
        elif ist <= 8:               q,f = "GOOD 🌅", 1.2
        elif ist <= 17:              q,f = "POOR ☀️", 0.6
        else:                        q,f = "GOOD 🌇", 1.1
        windows.append((h, f, q))
    return sorted(windows, key=lambda x: x[1], reverse=True)[:3]
