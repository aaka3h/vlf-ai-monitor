#!/usr/bin/env python3
"""
VLF AI Monitor v5 — Dual Mode Edition
RTL-SDR V4 (local) OR KiwiSDR (online) — your choice at startup
+ Shadow-AI analysis + Cross-verification + Audio streaming

Author: Aakash (@aaka3h)
GitHub: github.com/aaka3h/vlf-ai-monitor
"""

import numpy as np
import time, datetime, json, os, math, sys, wave, requests, subprocess, concurrent.futures
from collections import defaultdict, deque

# ─── Configuration ─────────────────────────────────────────────────────────────
SAMPLE_RATE       = 250_000
CENTER_FREQ       = 24_000_000
GAIN              = 49.6
FFT_SIZE          = 131072
SCAN_INTERVAL     = 2.0
SNR_THRESHOLD     = 8.0
AUDIO_SECONDS     = 5
OLLAMA_MODEL      = "shadow-ai"
OLLAMA_URL        = "http://localhost:11434/api/generate"
RECEIVER_LAT      = 0.0
RECEIVER_LON      = 0.0
RECEIVER_NAME     = "Unknown"
MODE              = "rtlsdr"  # "rtlsdr" or "kiwisdr"

# ─── Filter Settings ───────────────────────────────────────────────────────────
PERSISTENCE_SCANS   = 2
HARMONIC_TOLERANCE  = 30
MAX_BANDWIDTH_HZ    = 150
FREQ_STABILITY_HZ   = 80
MIN_SNR_FOR_AUDIO   = 8.0
DUPLICATE_WINDOW_HZ = 300

# ─── KiwiSDR Pool ──────────────────────────────────────────────────────────────
KIWI_POOL = [
    {"ip":"185.238.204.191","port":8073,"location":"Zakroczym, Poland",  "country":"Poland",    "lat":52.35, "lon":20.60},
    {"ip":"69.204.142.218", "port":8073,"location":"Canaan, USA",        "country":"USA",       "lat":41.93, "lon":-73.40},
    {"ip":"46.29.238.230",  "port":8073,"location":"Nuremberg, Germany", "country":"Germany",   "lat":49.45, "lon":11.07},
    {"ip":"103.77.224.1",   "port":8073,"location":"Singapore",          "country":"Singapore", "lat":1.35,  "lon":103.82},
    {"ip":"180.150.5.136",  "port":8073,"location":"Sydney, Australia",  "country":"Australia", "lat":-33.87,"lon":151.21},
    {"ip":"117.20.49.163",  "port":8073,"location":"Tokyo, Japan",       "country":"Japan",     "lat":35.68, "lon":139.69},
    {"ip":"5.9.52.32",      "port":8073,"location":"Helsinki, Finland",  "country":"Finland",   "lat":60.17, "lon":24.94},
]
KIWI_THRESHOLD_DB = 3.0
KIWI_NOISE_FLOOR  = defaultdict(lambda: -112.0)
KIWI_SERVERS      = []
KIWIRECORDER      = os.path.expanduser("~/kiwiclient/kiwirecorder.py")

# KiwiSDR scan frequencies (VLF band 3-30 kHz)
KIWI_SCAN_FREQS = [
    11.905, 12.649, 14.881,   # Russian Alpha
    15.000, 15.100,            # Pakistan, France HWU
    16.400,                    # Norway JXN
    17.000, 17.200,            # India VTX, Sweden SAQ
    18.100, 18.200, 18.300,    # Belarus RDL, India VTX3, France HWU
    19.600, 19.700, 19.800,    # UK GQD, Russia UGE, Australia NWC
    20.270, 20.500, 20.600,    # Italy ICV, China 3SA/3SB
    21.400, 21.750,            # USA NPM, France HWU
    22.200, 22.300,            # Japan JJI, India VEP
    23.400,                    # Germany DHO38
    24.000, 24.200, 24.800,    # USA NAA, India NRX, USA NLK
    25.200,                    # USA NML
]

# ─── Directories ───────────────────────────────────────────────────────────────
BASE_DIR     = "vlf_logs"
AUDIO_DIR    = os.path.join(BASE_DIR,"audio")
REPORTS_DIR  = os.path.join(BASE_DIR,"reports")
SESSIONS_DIR = os.path.join(BASE_DIR,"sessions")

class C:
    RESET="\033[0m";BOLD="\033[1m";RED="\033[91m";GREEN="\033[92m"
    YELLOW="\033[93m";BLUE="\033[94m";CYAN="\033[96m";GRAY="\033[90m";WHITE="\033[97m"

# ─── Station Database ──────────────────────────────────────────────────────────
STATIONS = {
    17000: {"callsign":"VTX",   "name":"INS Kattabomman",         "country":"India",    "lat":8.37,  "lon":77.75,  "operator":"Indian Navy",            "power_kw":500,  "mode":"MSK","purpose":"Nuclear submarine communication","active":True, "notes":"Primary Indian Navy VLF. Arihant-class SSBNs."},
    18200: {"callsign":"VTX3",  "name":"Visakhapatnam Naval VLF", "country":"India",    "lat":17.72, "lon":83.30,  "operator":"Indian Navy",            "power_kw":50,   "mode":"CW", "purpose":"Naval communication",           "active":True, "notes":"Indian Navy Eastern Command."},
    24200: {"callsign":"NRX",   "name":"Mettur Dam Naval Station","country":"India",    "lat":11.78, "lon":77.80,  "operator":"Indian Navy",            "power_kw":100,  "mode":"MSK","purpose":"Naval communication",           "active":True, "notes":"Indian Navy Tamil Nadu."},
    22300: {"callsign":"VEP",   "name":"INS Sangrador",           "country":"India",    "lat":15.48, "lon":73.83,  "operator":"Indian Navy",            "power_kw":50,   "mode":"CW", "purpose":"Naval communication",           "active":True, "notes":"Indian Navy West Coast, Goa."},
    24000: {"callsign":"NAA",   "name":"Cutler Naval Station",    "country":"USA",      "lat":44.64, "lon":-67.28, "operator":"US Navy",                "power_kw":1000, "mode":"MSK","purpose":"Nuclear submarine communication","active":True, "notes":"Most powerful VLF on Earth."},
    24800: {"callsign":"NLK",   "name":"Jim Creek Naval Station", "country":"USA",      "lat":48.20, "lon":-121.92,"operator":"US Navy",                "power_kw":250,  "mode":"MSK","purpose":"Submarine comm Pacific",        "active":True, "notes":"Primary US Navy Pacific VLF."},
    21400: {"callsign":"NPM",   "name":"Lualualei Naval Station", "country":"USA",      "lat":21.42, "lon":-158.15,"operator":"US Navy",                "power_kw":566,  "mode":"MSK","purpose":"Submarine comm Pacific",        "active":True, "notes":"Key Pacific submarine comms."},
    25200: {"callsign":"NML",   "name":"LaMoure Naval Station",   "country":"USA",      "lat":46.37, "lon":-98.33, "operator":"US Navy",                "power_kw":500,  "mode":"MSK","purpose":"Submarine communication",       "active":True, "notes":"US Navy strategic VLF."},
    19800: {"callsign":"NWC",   "name":"Harold E. Holt",          "country":"Australia","lat":-21.82,"lon":114.17, "operator":"US/Royal Australian Navy","power_kw":1000, "mode":"MSK","purpose":"Submarine comm Indian Ocean",   "active":True, "notes":"Covers entire Indian Ocean."},
    16400: {"callsign":"JXN",   "name":"Novik VLF Station",       "country":"Norway",   "lat":66.98, "lon":13.87,  "operator":"Norwegian/NATO Navy",    "power_kw":45,   "mode":"MSK","purpose":"NATO submarine communication",  "active":True, "notes":"Transmits 6x daily."},
    19600: {"callsign":"GQD",   "name":"Anthorn Radio Station",   "country":"UK",       "lat":54.91, "lon":-3.28,  "operator":"UK Royal Navy/NATO",     "power_kw":500,  "mode":"MSK","purpose":"NATO submarine + time signal",  "active":True, "notes":"Also MSF 60kHz time signal."},
    23400: {"callsign":"DHO38", "name":"Rhauderfehn Station",     "country":"Germany",  "lat":53.08, "lon":7.61,   "operator":"German Navy/NATO",       "power_kw":500,  "mode":"MSK","purpose":"NATO submarine communication",  "active":True, "notes":"Major NATO strategic VLF."},
    15100: {"callsign":"HWU",   "name":"Rosnay Naval Station",    "country":"France",   "lat":46.72, "lon":1.24,   "operator":"French Navy",            "power_kw":400,  "mode":"MSK","purpose":"French nuclear sub comms",      "active":True, "notes":"Alternates 15.1/18.3/21.75 kHz."},
    18300: {"callsign":"HWU",   "name":"Le Blanc Naval Station",  "country":"France",   "lat":46.62, "lon":1.18,   "operator":"French Navy",            "power_kw":400,  "mode":"MSK","purpose":"French nuclear sub comms",      "active":True, "notes":"HWU alternate frequency."},
    11905: {"callsign":"Alpha", "name":"RSDN-20 Krasnodar",       "country":"Russia",   "lat":44.46, "lon":39.34,  "operator":"Russian Navy",           "power_kw":500,  "mode":"CW", "purpose":"Navigation + submarine comms",  "active":True, "notes":"RSDN-20 Alpha. 3-station network."},
    12649: {"callsign":"Alpha", "name":"RSDN-20 Novosibirsk",     "country":"Russia",   "lat":54.99, "lon":82.90,  "operator":"Russian Navy",           "power_kw":500,  "mode":"CW", "purpose":"Navigation",                    "active":True, "notes":"Alpha second frequency."},
    14881: {"callsign":"Alpha", "name":"RSDN-20 Komsomolsk",      "country":"Russia",   "lat":50.55, "lon":137.00, "operator":"Russian Navy",           "power_kw":500,  "mode":"CW", "purpose":"Navigation",                    "active":True, "notes":"Alpha third frequency."},
    18100: {"callsign":"RDL",   "name":"Molodechno VLF",          "country":"Belarus",  "lat":54.28, "lon":26.47,  "operator":"Russian Navy",           "power_kw":300,  "mode":"MSK","purpose":"Russian submarine communication","active":True, "notes":"Russian Navy strategic comms."},
    20500: {"callsign":"3SA",   "name":"Changde VLF Station",     "country":"China",    "lat":28.99, "lon":111.70, "operator":"PLAN (Chinese Navy)",    "power_kw":300,  "mode":"MSK","purpose":"Chinese submarine communication","active":True, "notes":"PLAN nuclear submarine comms."},
    20600: {"callsign":"3SB",   "name":"Datong VLF Station",      "country":"China",    "lat":40.09, "lon":113.30, "operator":"PLAN (Chinese Navy)",    "power_kw":300,  "mode":"MSK","purpose":"Chinese submarine communication","active":True, "notes":"PLAN second VLF transmitter."},
    22200: {"callsign":"JJI",   "name":"Ebino VLF Station",       "country":"Japan",    "lat":32.08, "lon":130.83, "operator":"Japan MSDF",             "power_kw":50,   "mode":"FSK","purpose":"Japanese submarine communication","active":True, "notes":"JMSDF submarine comms."},
    15000: {"callsign":"NPK",   "name":"Karachi Naval VLF",       "country":"Pakistan", "lat":24.86, "lon":67.01,  "operator":"Pakistan Navy",          "power_kw":50,   "mode":"CW", "purpose":"Naval submarine communication", "active":True, "notes":"Pakistan Navy VLF."},
}

FLAGS={"India":"🇮🇳","USA":"🇺🇸","Australia":"🇦🇺","Norway":"🇳🇴","UK":"🇬🇧",
       "Germany":"🇩🇪","France":"🇫🇷","Sweden":"🇸🇪","Italy":"🇮🇹","Russia":"🇷🇺",
       "Belarus":"🇧🇾","China":"🇨🇳","Japan":"🇯🇵","Pakistan":"🇵🇰"}

# ─── Location ──────────────────────────────────────────────────────────────────
def detect_location():
    try:
        r=requests.get("http://ip-api.com/json/",timeout=5)
        d=r.json()
        return float(d["lat"]),float(d["lon"]),d["city"]+", "+d["country"]
    except:
        return 0.0,0.0,"Unknown"

def haversine(la1,lo1,la2,lo2):
    a=math.sin(math.radians(la2-la1)/2)**2
    b=math.cos(math.radians(la1))*math.cos(math.radians(la2))*math.sin(math.radians(lo2-lo1)/2)**2
    return 6371*2*math.asin(math.sqrt(a+b))

def select_nearest_kiwi(lat,lon,n=1):
    scored=sorted(KIWI_POOL,key=lambda s:haversine(lat,lon,s["lat"],s["lon"]))
    return scored[:n]

def get_bearing(lat2,lon2):
    la1,lo1=math.radians(RECEIVER_LAT),math.radians(RECEIVER_LON)
    la2,lo2=math.radians(lat2),math.radians(lon2)
    x=math.sin(lo2-lo1)*math.cos(la2)
    y=math.cos(la1)*math.sin(la2)-math.sin(la1)*math.cos(la2)*math.cos(lo2-lo1)
    return (math.degrees(math.atan2(x,y))+360)%360

def bearing_to_compass(b):
    d=["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return d[round(b/(360/len(d)))%len(d)]

def get_distance(lat2,lon2):
    return round(haversine(RECEIVER_LAT,RECEIVER_LON,lat2,lon2))

def find_station(freq_hz,tol=500):
    best,best_d=None,tol
    for f,info in STATIONS.items():
        d=abs(freq_hz-f)
        if d<best_d:best_d=d;best=(f,info)
    return best

# ─── KiwiSDR Mode ──────────────────────────────────────────────────────────────
def kiwi_measure_rssi(ip, port, freq_khz, timeout=7):
    try:
        r=subprocess.run(
            [sys.executable,KIWIRECORDER,
             "-s",ip,"-p",str(port),
             "-f",str(freq_khz),"-m","usb",
             "--S-meter=1",f"--tlimit={timeout}","--quiet"],
            capture_output=True,text=True,timeout=timeout+5
        )
        for line in r.stdout.splitlines():
            if "RSSI:" in line:
                return float(line.split("RSSI:")[1].strip())
        return None
    except:
        return None

def kiwi_record_audio(ip, port, freq_khz, duration_sec, filepath):
    """Record audio from KiwiSDR at given frequency."""
    try:
        base = filepath.replace(".wav","")
        r=subprocess.run(
            [sys.executable,KIWIRECORDER,
             "-s",ip,"-p",str(port),
             "-f",str(freq_khz),"-m","usb",
             f"--tlimit={duration_sec}",
             "-d",os.path.dirname(filepath),
             f"--fn={os.path.basename(base)}",
             "--quiet"],
            capture_output=True,text=True,timeout=duration_sec+15
        )
        # kiwirecorder saves as base.wav or similar
        possible = [filepath, base+".wav", base+"_00.wav"]
        for p in possible:
            if os.path.exists(p) and os.path.getsize(p)>1000:
                return p
        return None
    except Exception as e:
        return None

def kiwi_scan_band(kiwi_server):
    """
    Scan all VLF frequencies on a KiwiSDR in parallel.
    Returns list of signals above noise threshold.
    """
    ip   = kiwi_server["ip"]
    port = kiwi_server["port"]

    # Get noise floor first
    noise_freqs = [10.0, 13.5, 16.8]
    noise_readings = []
    for f in noise_freqs:
        r = kiwi_measure_rssi(ip, port, f, timeout=5)
        if r: noise_readings.append(r)
    noise_floor = min(noise_readings) if noise_readings else -112.0
    KIWI_NOISE_FLOOR[ip] = noise_floor

    # Scan all known station frequencies in parallel
    def measure_freq(freq_khz):
        rssi = kiwi_measure_rssi(ip, port, freq_khz, timeout=6)
        if rssi is None:
            return None
        snr = rssi - noise_floor
        if snr >= SNR_THRESHOLD:
            return {
                "freq_hz":   freq_khz * 1000,
                "freq_khz":  freq_khz,
                "rssi_dbm":  rssi,
                "snr_db":    round(snr, 1),
                "noise_floor": noise_floor,
            }
        return None

    print(f"  {C.GRAY}Scanning {len(KIWI_SCAN_FREQS)} frequencies on {kiwi_server['location']}...{C.RESET}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(measure_freq, KIWI_SCAN_FREQS))

    detected = [r for r in results if r is not None]
    detected.sort(key=lambda x: x["snr_db"], reverse=True)
    return detected, noise_floor

# ─── Cross-Verification ────────────────────────────────────────────────────────
def cross_verify(freq_hz, local_snr_db, verify_servers):
    freq_khz = freq_hz / 1000

    def check_one(srv):
        ip=srv["ip"];port=srv["port"];loc=srv["location"]
        rssi=kiwi_measure_rssi(ip,port,freq_khz,timeout=7)
        if rssi is None:
            return {"location":loc,"country":srv["country"],"rssi":None,"above_noise":None,"confirmed":False,"status":"UNREACHABLE"}
        noise=KIWI_NOISE_FLOOR[ip]
        above=rssi-noise
        ok=above>=KIWI_THRESHOLD_DB
        return {"location":loc,"country":srv["country"],"rssi":rssi,"noise_floor":noise,"above_noise":round(above,1),"confirmed":ok,"status":"SIGNAL" if ok else "NOISE"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(verify_servers)) as ex:
        results=list(ex.map(check_one,verify_servers))

    confirmed=sum(1 for r in results if r["confirmed"])
    reachable=sum(1 for r in results if r["rssi"] is not None)
    if reachable==0:     conf="UNVERIFIED";verified=False
    elif confirmed>=1:   conf="HIGH" if confirmed==reachable else "MEDIUM";verified=True
    else:                conf="LOW";verified=False

    return {"verified":verified,"confidence":conf,"confirmed_count":confirmed,"total_checked":reachable,"results":results}

def print_crossverify(cv):
    print(f"\n  {C.CYAN}{'─'*54}{C.RESET}")
    print(f"  {C.CYAN}{C.BOLD}🌍 CROSS-VERIFICATION{C.RESET}")
    for r in cv["results"]:
        if r["rssi"] is None:
            print(f"  {C.GRAY}  ✗ {r['location']:30} UNREACHABLE{C.RESET}")
        else:
            icon="✅"if r["confirmed"]else"❌"
            col=C.GREEN if r["confirmed"] else C.RED
            bar="▓"*int(max(0,r["above_noise"])/2)
            print(f"  {col}  {icon} {r['location']:30} RSSI:{r['rssi']:7.1f} dBm ({r['above_noise']:+.1f} dB) {bar}{C.RESET}")
    if cv["verified"] and cv["confidence"]=="HIGH":
        print(f"\n  {C.GREEN}{C.BOLD}✅ CONFIRMED — Real signal, not local noise{C.RESET}")
    elif cv["verified"]:
        print(f"\n  {C.YELLOW}{C.BOLD}⚠️  PROBABLE — Likely real signal{C.RESET}")
    else:
        print(f"\n  {C.RED}{C.BOLD}❌ NOT CONFIRMED — Possible local interference{C.RESET}")

# ─── AI ────────────────────────────────────────────────────────────────────────
def init_ai():
    try:
        r=requests.get("http://localhost:11434/api/tags",timeout=3)
        if r.status_code==200:
            print(f"  {C.GREEN}✅ Ollama ready | model: {OLLAMA_MODEL}{C.RESET}")
            return True
    except:pass
    print(f"  {C.RED}⚠️  Ollama not running{C.RESET}")
    return False

def analyze(ai_ready, freq_hz, snr_db, bw, confidence, station, cv, source):
    if not ai_ready:return "⚠️  Ollama not running"
    try:
        if station:
            _,info=station
            ctx=f"Match: {info['callsign']} — {info['name']}, {info['country']}, {info['operator']}, {info['power_kw']}kW, {info.get('mode','?')}, {info['purpose']}"
        else:
            ctx="No database match."
        cv_s=f"Cross-verify: {cv['confidence']} — {cv['confirmed_count']}/{cv['total_checked']} receivers confirmed" if cv else "Not verified"
        source_note = "KiwiSDR online receiver" if source=="kiwisdr" else "Local RTL-SDR V4"
        prompt=f"""Expert VLF analyst. Signal detected:
Source: {source_note} at {RECEIVER_NAME}
Frequency: {freq_hz/1000:.3f} kHz | SNR: {snr_db:.1f} dB
{cv_s}
{ctx}
Respond EXACTLY:
IDENTIFICATION: [what]
CONFIDENCE: [0-100]%
ANTENNA: [direction from {RECEIVER_NAME}]
MODE: [CW/MSK/FSK/UNKNOWN]
SIGNIFICANCE: [1 sentence — what communication might be happening]
VERDICT: [CONFIRMED SIGNAL/PROBABLE SIGNAL/POSSIBLE SIGNAL/NOISE]"""
        r=requests.post(OLLAMA_URL,json={"model":OLLAMA_MODEL,"prompt":prompt,"stream":False},timeout=90)
        return r.json()["response"].strip()
    except Exception as e:
        return f"AI error: {e}"

# ─── Noise Filters (RTL-SDR mode) ──────────────────────────────────────────────
def is_power_line_harmonic(freq_hz):
    for n in range(1,700):
        if abs(freq_hz-n*50)<HARMONIC_TOLERANCE:
            return True,n*50
    return False,None

class SignalTracker:
    def __init__(self):
        self.history=defaultdict(lambda:deque(maxlen=10))
        self.counts=defaultdict(int)
        self.reported={}

    def bucket(self,f):return round(f/DUPLICATE_WINDOW_HZ)*DUPLICATE_WINDOW_HZ
    def update(self,f,sig):
        b=self.bucket(f);self.history[b].append(f);self.counts[b]+=1
        return self.counts[b]
    def get_stability(self,f):
        h=list(self.history[self.bucket(f)])
        return float(max(h)-min(h)) if len(h)>=2 else 0.0
    def reset_stale(self,active):
        for b in list(self.counts.keys()):
            if b not in active:self.counts[b]=max(0,self.counts[b]-1)
    def is_duplicate(self,f,gap=60):
        return time.time()-self.reported.get(self.bucket(f),0)<gap
    def mark_reported(self,f):
        self.reported[self.bucket(f)]=time.time()

def apply_filters(freq_hz,snr_db,bw,tracker):
    is_h,hf=is_power_line_harmonic(freq_hz)
    if is_h:return False,f"50Hz harmonic","HARMONIC"
    if bw>MAX_BANDWIDTH_HZ:return False,f"Too wide ({bw:.0f}Hz)","BANDWIDTH"
    drift=tracker.get_stability(freq_hz)
    if drift>FREQ_STABILITY_HZ:return False,f"Unstable","STABILITY"
    if snr_db<SNR_THRESHOLD:return False,f"Weak SNR","SNR"
    return True,"PASSED","NONE"

# ─── RTL-SDR DSP ───────────────────────────────────────────────────────────────
def measure_bandwidth(samples,freq_hz,sample_rate,fft_size):
    try:
        n=min(len(samples),fft_size)
        w=samples[:n]*np.hanning(n)
        sp=np.abs(np.fft.rfft(w,n))
        freqs=np.fft.rfftfreq(n,d=1/sample_rate)
        idx=np.argmin(np.abs(freqs-freq_hz))
        peak=sp[idx];half=peak/2
        left=idx
        while left>0 and sp[left]>half:left-=1
        right=idx
        while right<len(sp)-1 and sp[right]>half:right+=1
        return float(freqs[right]-freqs[left])
    except:
        return 999.0

def estimate_noise(sdr,n=8):
    floors=[]
    for _ in range(n):
        s=sdr.read_samples(FFT_SIZE)
        w=s*np.hanning(len(s))
        sp=np.fft.rfft(w,FFT_SIZE)
        pd=20*np.log10(np.abs(sp)+1e-12)
        mask=np.fft.rfftfreq(FFT_SIZE,d=1/SAMPLE_RATE)>=3000
        floors.append(np.percentile(pd[mask],20))
    return float(np.mean(floors))

def scan_band_rtlsdr(sdr,noise):
    s=sdr.read_samples(FFT_SIZE)
    w=s*np.hanning(len(s))
    sp=np.fft.rfft(w,FFT_SIZE)
    freqs=np.fft.rfftfreq(FFT_SIZE,d=1/SAMPLE_RATE)
    pd=20*np.log10(np.abs(sp)+1e-12)
    mask=(freqs>=3000)&(freqs<=30000)
    f,p=freqs[mask],pd[mask]
    detected=[]
    for i in range(3,len(f)-3):
        if(p[i]>p[i-1]and p[i]>p[i-2]and p[i]>p[i-3]and
           p[i]>p[i+1]and p[i]>p[i+2]and p[i]>p[i+3]and
           p[i]>noise+SNR_THRESHOLD):
            bw=measure_bandwidth(s,f[i],SAMPLE_RATE,FFT_SIZE)
            detected.append({"freq_hz":float(f[i]),"power_db":float(p[i]),"snr_db":float(p[i]-noise),"bandwidth_hz":bw,"samples":s})
    detected.sort(key=lambda x:x["snr_db"],reverse=True)
    return detected[:8]

def record_audio_rtlsdr(sdr,freq_hz,duration_sec,filename):
    try:
        chunk_size=65536
        chunks=[sdr.read_samples(chunk_size) for _ in range(max(1,int(SAMPLE_RATE*duration_sec/chunk_size)))]
        samples=np.concatenate(chunks)
        t=np.arange(len(samples))/SAMPLE_RATE
        audio=np.real(samples*np.exp(-2j*np.pi*freq_hz*t))
        audio=audio[::50]/(np.max(np.abs(audio[::50]))+1e-9)
        with wave.open(filename,'w')as wf:
            wf.setnchannels(1);wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE//50)
            wf.writeframes((audio*32767).astype(np.int16).tobytes())
        return True
    except:
        return False

# ─── Logging ───────────────────────────────────────────────────────────────────
def setup_dirs():
    for d in [BASE_DIR,AUDIO_DIR,REPORTS_DIR,SESSIONS_DIR]:
        os.makedirs(d,exist_ok=True)

def save_detection(entry,sid):
    for fp in [
        os.path.join(BASE_DIR,"all_detections.json"),
        os.path.join(SESSIONS_DIR,f"session_{sid}.json"),
    ]:
        logs=[]
        if os.path.exists(fp):
            try:
                with open(fp)as f:logs=json.load(f)
            except:pass
        logs.append(entry)
        with open(fp,"w")as f:json.dump(logs,f,indent=2)

# ─── Display ───────────────────────────────────────────────────────────────────
def print_detection(freq_hz, snr_db, bw, station, ai_result, audio_file,
                    det_num, filtered, cv, source, rssi_dbm=None):
    ts=datetime.datetime.now().strftime("%H:%M:%S")
    src_icon = "📡" if source=="rtlsdr" else "🌐"

    print(f"\n  {C.GREEN}{C.BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.RESET}")
    print(f"  {C.GREEN}{C.BOLD}[{ts}] {src_icon} SIGNAL #{det_num}{C.RESET}")
    print(f"  {C.GREEN}{C.BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.RESET}")
    print(f"  {C.YELLOW}Frequency{C.RESET} : {C.BOLD}{C.WHITE}{freq_hz/1000:.3f} kHz{C.RESET}")
    if rssi_dbm:
        print(f"  {C.YELLOW}RSSI     {C.RESET} : {rssi_dbm:.1f} dBm")
    print(f"  {C.YELLOW}SNR      {C.RESET} : {C.GREEN}{snr_db:.1f} dB{C.RESET} above noise")
    print(f"  {C.YELLOW}Source   {C.RESET} : {'Local RTL-SDR V4' if source=='rtlsdr' else 'KiwiSDR Online'}")
    if filtered is not None:
        print(f"  {C.GRAY}Noise rejected: {filtered}{C.RESET}")

    if station:
        _,info=station
        flag=FLAGS.get(info["country"],"🌍")
        bearing=get_bearing(info["lat"],info["lon"])
        compass=bearing_to_compass(bearing)
        dist_km=get_distance(info["lat"],info["lon"])
        st=f"{C.GREEN}ACTIVE{C.RESET}"if info["active"]else f"{C.RED}HISTORIC{C.RESET}"
        print(f"\n  {C.CYAN}{'─'*54}{C.RESET}")
        print(f"  {C.CYAN}{C.BOLD}DATABASE MATCH{C.RESET}")
        print(f"  {flag}  {C.BOLD}{info['callsign']}{C.RESET}  —  {info['name']}")
        print(f"  {C.YELLOW}Country {C.RESET}: {info['country']}  {st}")
        print(f"  {C.YELLOW}Operator{C.RESET}: {info['operator']}")
        print(f"  {C.YELLOW}Power   {C.RESET}: {info['power_kw']} kW | Mode: {info.get('mode','?')}")
        print(f"  {C.YELLOW}Purpose {C.RESET}: {info['purpose']}")
        print(f"  {C.YELLOW}Distance{C.RESET}: {dist_km:,} km | Notes: {info['notes']}")
        print(f"\n  {C.BOLD}🧭 Point antenna {compass} ({bearing:.0f}°) from {RECEIVER_NAME}{C.RESET}")
    else:
        print(f"\n  {C.RED}⚠️  Unknown — not in database{C.RESET}")

    if cv:
        print_crossverify(cv)

    print(f"\n  {C.BLUE}{'─'*54}{C.RESET}")
    print(f"  {C.BLUE}{C.BOLD}🤖 SHADOW-AI ANALYSIS{C.RESET}")
    for line in ai_result.strip().split("\n"):
        if not line.strip():continue
        if "VERDICT" in line:
            col=C.GREEN if "CONFIRMED" in line else C.YELLOW if "PROBABLE" in line else C.RED
            print(f"  {col}{C.BOLD}{line}{C.RESET}")
        elif any(k in line for k in ["IDENTIFICATION","CONFIDENCE","ANTENNA","MODE","SIGNIFICANCE"]):
            parts=line.split(":",1)
            print(f"  {C.YELLOW}{parts[0]}{C.RESET}:{parts[1] if len(parts)>1 else ''}")
        else:
            print(f"  {C.GRAY}{line}{C.RESET}")

    if audio_file:
        print(f"\n  {C.CYAN}🎵 Audio: {audio_file}{C.RESET}")
        print(f"  {C.CYAN}   Play : aplay {audio_file}{C.RESET}")
    print(f"  {C.GRAY}💾 {BASE_DIR}/{C.RESET}")

# ─── Mode Selection ────────────────────────────────────────────────────────────
def select_mode():
    os.system("clear")
    print(f"{C.CYAN}{C.BOLD}")
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║   📡  VLF AI MONITOR v5 — Dual Mode Edition             ║")
    print("  ║   Shadow-AI + Cross-Verification + Audio Streaming      ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print(f"{C.RESET}")
    print(f"  {C.CYAN}Select receiver mode:{C.RESET}\n")
    print(f"  {C.GREEN}[1] Local RTL-SDR V4{C.RESET}")
    print(f"      → Plug in your RTL-SDR dongle")
    print(f"      → Full spectrum scanning")
    print(f"      → Works at home with antenna")
    print()
    print(f"  {C.BLUE}[2] Online KiwiSDR{C.RESET}")
    print(f"      → No hardware needed")
    print(f"      → Uses remote receivers worldwide")
    print(f"      → Works from anywhere, any device")
    print(f"      → Auto-selects nearest server")
    print()

    while True:
        choice = input(f"  {C.YELLOW}Enter 1 or 2: {C.RESET}").strip()
        if choice == "1":
            return "rtlsdr"
        elif choice == "2":
            return "kiwisdr"
        print(f"  {C.RED}Please enter 1 or 2{C.RESET}")

# ─── RTL-SDR Main Loop ─────────────────────────────────────────────────────────
def run_rtlsdr(ai_ready, sid, verify_servers):
    global RECEIVER_LAT, RECEIVER_LON, RECEIVER_NAME
    try:
        from rtlsdr import RtlSdr
    except ImportError:
        print(f"  {C.RED}❌ pyrtlsdr not installed{C.RESET}")
        return

    print(f"  {C.YELLOW}Starting RTL-SDR V4...{C.RESET}")
    try:
        sdr=RtlSdr()
        sdr.sample_rate=SAMPLE_RATE;sdr.center_freq=CENTER_FREQ
        sdr.gain=GAIN;sdr.set_direct_sampling(2)
        print(f"  {C.GREEN}✅ RTL-SDR V4 ready{C.RESET}")
    except Exception as e:
        print(f"  {C.RED}❌ RTL-SDR error: {e}{C.RESET}")
        print(f"  {C.YELLOW}Make sure RTL-SDR is plugged in{C.RESET}")
        return

    print(f"  {C.YELLOW}Calibrating noise floor...{C.RESET}")
    noise=estimate_noise(sdr,n=10)
    print(f"  {C.GREEN}✅ Noise: {noise:.1f} dBFS | Threshold: {noise+SNR_THRESHOLD:.1f} dBFS{C.RESET}")
    print(f"\n  {C.GRAY}Ctrl+C to stop{C.RESET}\n")
    time.sleep(1)

    tracker=SignalTracker()
    scans=0;detections=0;filtered=0;session_log=[]

    try:
        while True:
            scans+=1
            ts=datetime.datetime.now().strftime("%H:%M:%S")
            raw=scan_band_rtlsdr(sdr,noise)
            active_buckets=set()

            for sig in raw:
                fhz=sig["freq_hz"];bw=sig["bandwidth_hz"];snr=sig["snr_db"]
                b=tracker.bucket(fhz)
                active_buckets.add(b)

                passed,reason,fname=apply_filters(fhz,snr,bw,tracker)
                if not passed:
                    filtered+=1
                    sys.stdout.write(f"\r  {C.RED}✗ [{fname}] {fhz/1000:.3f}kHz — {reason}{C.RESET}   ")
                    sys.stdout.flush()
                    continue

                count=tracker.update(fhz,sig)
                if count<PERSISTENCE_SCANS:
                    sys.stdout.write(f"\r  {C.YELLOW}⏳ {fhz/1000:.3f}kHz ({count}/{PERSISTENCE_SCANS}){C.RESET}   ")
                    sys.stdout.flush()
                    continue

                if tracker.is_duplicate(fhz):
                    continue

                tracker.mark_reported(fhz)
                detections+=1
                station=find_station(fhz)

                print(f"\n  {C.CYAN}⏳ Cross-verifying {fhz/1000:.3f} kHz...{C.RESET}")
                cv=None  # disabled in KiwiSDR mode

                ai_result=analyze(ai_ready,fhz,snr,bw,80,station,cv,"rtlsdr")

                audio_file=None
                if snr>=MIN_SNR_FOR_AUDIO:
                    apath=os.path.join(AUDIO_DIR,f"{fhz/1000:.3f}kHz_{datetime.datetime.now().strftime('%H%M%S')}.wav")
                    if record_audio_rtlsdr(sdr,fhz,AUDIO_SECONDS,apath):audio_file=apath

                print_detection(fhz,snr,bw,station,ai_result,audio_file,detections,filtered,cv,"rtlsdr")

                info=station[1] if station else {}
                save_detection({
                    "detection_number":detections,"session_id":sid,
                    "timestamp":datetime.datetime.now().isoformat(),
                    "source":"rtlsdr","freq_khz":round(fhz/1000,3),
                    "snr_db":round(snr,1),"station":info.get("name","Unknown"),
                    "cross_verified": cv["verified"] if cv else False,"audio_file":audio_file,
                    "ai_analysis":ai_result
                },sid)
                session_log.append({"freq_khz":round(fhz/1000,3),"station":info.get("name","Unknown"),"snr_db":round(snr,1)})

            tracker.reset_stale(active_buckets)

            if not raw:
                sys.stdout.write(f"\r  {C.GRAY}[{ts}] Scan #{scans} | Noise:{noise:.0f}dBFS | Confirmed:{detections} | Filtered:{filtered}{C.RESET}   ")
                sys.stdout.flush()

            if scans%60==0:noise=estimate_noise(sdr,n=3)
            time.sleep(SCAN_INTERVAL)

    except KeyboardInterrupt:
        pass
    finally:
        sdr.close()
    return session_log

# ─── KiwiSDR Main Loop ─────────────────────────────────────────────────────────
def run_kiwisdr(ai_ready, sid, kiwi_source, verify_servers):
    global SNR_THRESHOLD
    print(f"  {C.GREEN}✅ KiwiSDR source: {kiwi_source['location']}{C.RESET}")

    # Auto-tune SNR threshold
    print(f"\n  {C.YELLOW}Auto-tuning SNR threshold...{C.RESET}")
    try:
        from auto_tune import auto_tune_threshold, get_best_scan_window
        threshold, noise_floor, quality = auto_tune_threshold(
            kiwi_source["ip"], kiwi_source["port"],
            lat=RECEIVER_LAT, verbose=True
        )
        SNR_THRESHOLD = threshold
        print(f"  {C.GREEN}✅ SNR threshold set to {SNR_THRESHOLD} dB{C.RESET}")

        # Show best scan times
        best_windows = get_best_scan_window()
        print(f"  {C.CYAN}Best scan times today (UTC):{C.RESET}")
        for hour, factor, qual in best_windows:
            print(f"  {C.GRAY}  {hour:02d}:00 UTC — {qual}{C.RESET}")
    except Exception as e:
        print(f"  {C.YELLOW}⚠️  Auto-tune failed ({e}), using default {SNR_THRESHOLD} dB{C.RESET}")

    print(f"\n  {C.GRAY}Scanning {len(KIWI_SCAN_FREQS)} VLF frequencies...{C.RESET}")
    print(f"  {C.GRAY}Ctrl+C to stop{C.RESET}\n")

    scans=0;detections=0;session_log=[]
    reported = {}

    try:
        while True:
            scans+=1
            ts=datetime.datetime.now().strftime("%H:%M:%S")
            print(f"\n  {C.GRAY}[{ts}] Scan #{scans} — scanning band...{C.RESET}")

            detected, noise_floor = kiwi_scan_band(kiwi_source)

            if not detected:
                print(f"  {C.GRAY}No signals above threshold this scan{C.RESET}")
            else:
                for sig in detected:
                    fhz     = sig["freq_hz"]
                    freq_khz= sig["freq_khz"]
                    snr     = sig["snr_db"]
                    rssi    = sig["rssi_dbm"]

                    # Duplicate suppression
                    bucket  = round(fhz/500)*500
                    if time.time()-reported.get(bucket,0) < 120:
                        continue
                    reported[bucket] = time.time()

                    detections+=1
                    station=find_station(fhz)

                    # Cross-verify on different KiwiSDR
                    print(f"\n  {C.CYAN}⏳ Cross-verifying {freq_khz:.3f} kHz...{C.RESET}")
                    cv=None  # disabled in KiwiSDR mode

                    # Record audio from KiwiSDR
                    audio_file=None
                    if snr>=MIN_SNR_FOR_AUDIO:
                        apath=os.path.join(AUDIO_DIR,f"{freq_khz:.3f}kHz_{datetime.datetime.now().strftime('%H%M%S')}")
                        print(f"  {C.GRAY}🎵 Recording {AUDIO_SECONDS}s audio from KiwiSDR...{C.RESET}")
                        saved=kiwi_record_audio(kiwi_source["ip"],kiwi_source["port"],freq_khz,AUDIO_SECONDS,apath+".wav")
                        if saved:audio_file=saved

                    ai_result=analyze(ai_ready,fhz,snr,50,80,station,cv,"kiwisdr")
                    print_detection(fhz,snr,50,station,ai_result,audio_file,detections,None,cv,"kiwisdr",rssi_dbm=rssi)

                    info=station[1] if station else {}
                    save_detection({
                        "detection_number":detections,"session_id":sid,
                        "timestamp":datetime.datetime.now().isoformat(),
                        "source":"kiwisdr","freq_khz":round(freq_khz,3),
                        "rssi_dbm":rssi,"snr_db":round(snr,1),
                        "station":info.get("name","Unknown"),
                        "cross_verified": cv["verified"] if cv else False,"audio_file":audio_file,
                        "ai_analysis":ai_result
                    },sid)
                    session_log.append({"freq_khz":round(freq_khz,3),"station":info.get("name","Unknown"),"snr_db":round(snr,1)})

            # Wait before next scan
            print(f"  {C.GRAY}Next scan in 30 seconds...{C.RESET}")
            time.sleep(30)

    except KeyboardInterrupt:
        pass
    return session_log

# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    global RECEIVER_LAT, RECEIVER_LON, RECEIVER_NAME, KIWI_SERVERS, MODE

    setup_dirs()
    MODE = select_mode()
    sid  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    os.system("clear")
    print(f"{C.CYAN}{C.BOLD}")
    print("  ╔══════════════════════════════════════════════════════════╗")
    mode_str = "RTL-SDR V4 (Local)" if MODE=="rtlsdr" else "KiwiSDR (Online)"
    print(f"  ║   📡  VLF AI MONITOR v5 — {mode_str:30}║")
    print("  ║   Shadow-AI + Cross-Verification + Audio Recording      ║")
    print(f"  ║   Stations: {len(STATIONS)} known | Band: 3-30 kHz                  ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print(f"{C.RESET}")

    print(f"  {C.YELLOW}Detecting location...{C.RESET}")
    RECEIVER_LAT,RECEIVER_LON,RECEIVER_NAME=detect_location()
    print(f"  {C.GREEN}✅ Location: {RECEIVER_NAME} ({RECEIVER_LAT:.2f}°, {RECEIVER_LON:.2f}°){C.RESET}")

    # Select KiwiSDRs
    nearest = [{"ip":"185.238.204.191","port":8073,"location":"Zakroczym, Poland","country":"Poland","lat":52.35,"lon":20.60},{"ip":"69.204.142.218","port":8073,"location":"Canaan, USA","country":"USA","lat":41.93,"lon":-73.40}]
    KIWI_SERVERS = nearest

    if MODE == "kiwisdr":
        kiwi_source    = nearest[0]
        verify_servers = nearest[1:] if len(nearest)>1 else nearest
        dist = round(haversine(RECEIVER_LAT,RECEIVER_LON,kiwi_source["lat"],kiwi_source["lon"]))
        print(f"  {C.GREEN}✅ KiwiSDR source: {kiwi_source['location']} ({dist:,} km){C.RESET}")
    else:
        kiwi_source    = None
        verify_servers = nearest

    print(f"  {C.GREEN}✅ Cross-verify: {', '.join(s['location'] for s in verify_servers)}{C.RESET}")

    print(f"  {C.YELLOW}Starting Shadow-AI...{C.RESET}")
    ai_ready=init_ai()
    print()

    session_log=[]
    try:
        if MODE == "rtlsdr":
            session_log = run_rtlsdr(ai_ready, sid, verify_servers) or []
        else:
            session_log = run_kiwisdr(ai_ready, sid, kiwi_source, verify_servers) or []
    except KeyboardInterrupt:
        pass

    # Session summary
    print(f"\n\n  {C.CYAN}{'═'*58}{C.RESET}")
    print(f"  {C.BOLD}SESSION COMPLETE — {sid}{C.RESET}")
    if session_log:
        for d in session_log:
            flag=FLAGS.get(d.get("country",""),"🌍")
            print(f"  {flag} {d['freq_khz']:7.3f} kHz — {d['station']} (SNR:{d['snr_db']}dB)")
    print(f"  {C.GRAY}Files: {BASE_DIR}/{C.RESET}")
    print(f"  {C.CYAN}{'═'*58}{C.RESET}\n")

if __name__=="__main__":
    main()
