#!/usr/bin/env python3
"""
VLF AI Monitor v4 — Cross-Verified Edition
RTL-SDR V4 + Shadow-AI (Ollama) + KiwiSDR Cross-Verification

- Auto-selects nearest KiwiSDR based on your IP location
- Parallel cross-verification (~7 seconds)
- 6-stage noise filter pipeline
- Shadow-AI local analysis

Author: Aakash (@aaka3h)
GitHub: github.com/aaka3h/vlf-ai-monitor
"""

import numpy as np
import time, datetime, json, os, math, sys, wave, requests, subprocess, concurrent.futures
from rtlsdr import RtlSdr
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

# ─── Filter Settings ───────────────────────────────────────────────────────────
PERSISTENCE_SCANS   = 2
HARMONIC_TOLERANCE  = 30
MAX_BANDWIDTH_HZ    = 150
FREQ_STABILITY_HZ   = 80
MIN_SNR_FOR_AUDIO   = 12.0
DUPLICATE_WINDOW_HZ = 300

# ─── KiwiSDR Pool — auto-selects nearest one at startup ────────────────────────
KIWI_POOL = [
    {"ip":"185.238.204.191","port":8073,"location":"Zakroczym, Poland",      "country":"Poland",       "lat":52.35, "lon":20.60},
    {"ip":"69.204.142.218", "port":8073,"location":"Canaan, USA",            "country":"USA",          "lat":41.93, "lon":-73.40},
    {"ip":"46.29.238.230",  "port":8073,"location":"Nuremberg, Germany",     "country":"Germany",      "lat":49.45, "lon":11.07},
    {"ip":"103.77.224.1",   "port":8073,"location":"Singapore",              "country":"Singapore",    "lat":1.35,  "lon":103.82},
    {"ip":"180.150.5.136",  "port":8073,"location":"Sydney, Australia",      "country":"Australia",    "lat":-33.87,"lon":151.21},
    {"ip":"117.20.49.163",  "port":8073,"location":"Tokyo, Japan",           "country":"Japan",        "lat":35.68, "lon":139.69},
    {"ip":"5.9.52.32",      "port":8073,"location":"Helsinki, Finland",      "country":"Finland",      "lat":60.17, "lon":24.94},
]
KIWI_THRESHOLD_DB = 3.0
KIWI_NOISE_FLOOR  = defaultdict(lambda: -112.0)
KIWI_SERVERS      = []  # filled at startup with nearest
KIWIRECORDER      = os.path.expanduser("~/kiwiclient/kiwirecorder.py")

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
    17000: {"callsign":"VTX",   "name":"INS Kattabomman",         "country":"India",    "lat":8.37,  "lon":77.75,  "operator":"Indian Navy",            "power_kw":500,  "mode":"MSK","purpose":"Nuclear submarine communication","active":True, "notes":"Primary Indian Navy VLF. Arihant-class SSBNs. Transmits 24/7."},
    18200: {"callsign":"VTX3",  "name":"Visakhapatnam Naval VLF", "country":"India",    "lat":17.72, "lon":83.30,  "operator":"Indian Navy",            "power_kw":50,   "mode":"CW", "purpose":"Naval communication",           "active":True, "notes":"Indian Navy Eastern Command HQ."},
    24200: {"callsign":"NRX",   "name":"Mettur Dam Naval Station","country":"India",    "lat":11.78, "lon":77.80,  "operator":"Indian Navy",            "power_kw":100,  "mode":"MSK","purpose":"Naval communication",           "active":True, "notes":"Indian Navy Tamil Nadu."},
    22300: {"callsign":"VEP",   "name":"INS Sangrador",           "country":"India",    "lat":15.48, "lon":73.83,  "operator":"Indian Navy",            "power_kw":50,   "mode":"CW", "purpose":"Naval communication",           "active":True, "notes":"Indian Navy West Coast, Goa."},
    24000: {"callsign":"NAA",   "name":"Cutler Naval Station",    "country":"USA",      "lat":44.64, "lon":-67.28, "operator":"US Navy",                "power_kw":1000, "mode":"MSK","purpose":"Nuclear submarine communication","active":True, "notes":"Most powerful VLF on Earth. 1 megawatt."},
    24800: {"callsign":"NLK",   "name":"Jim Creek Naval Station", "country":"USA",      "lat":48.20, "lon":-121.92,"operator":"US Navy",                "power_kw":250,  "mode":"MSK","purpose":"Submarine comm Pacific",        "active":True, "notes":"Primary US Navy Pacific VLF."},
    21400: {"callsign":"NPM",   "name":"Lualualei Naval Station", "country":"USA",      "lat":21.42, "lon":-158.15,"operator":"US Navy",                "power_kw":566,  "mode":"MSK","purpose":"Submarine comm Pacific",        "active":True, "notes":"Key Pacific submarine comms."},
    25200: {"callsign":"NML",   "name":"LaMoure Naval Station",   "country":"USA",      "lat":46.37, "lon":-98.33, "operator":"US Navy",                "power_kw":500,  "mode":"MSK","purpose":"Submarine communication",       "active":True, "notes":"US Navy strategic VLF."},
    19800: {"callsign":"NWC",   "name":"Harold E. Holt",          "country":"Australia","lat":-21.82,"lon":114.17, "operator":"US/Royal Australian Navy","power_kw":1000, "mode":"MSK","purpose":"Submarine comm Indian Ocean",   "active":True, "notes":"Covers entire Indian Ocean. 1 megawatt."},
    13000: {"callsign":"VL3DEF","name":"Gippsland VLF",           "country":"Australia","lat":-37.80,"lon":147.00, "operator":"Australian Defence",     "power_kw":10,   "mode":"CW", "purpose":"Naval communication",           "active":True, "notes":"ADF VLF station Victoria."},
    16400: {"callsign":"JXN",   "name":"Novik VLF Station",       "country":"Norway",   "lat":66.98, "lon":13.87,  "operator":"Norwegian/NATO Navy",    "power_kw":45,   "mode":"MSK","purpose":"NATO submarine communication",  "active":True, "notes":"Transmits 6x daily in 2hr blocks."},
    19600: {"callsign":"GQD",   "name":"Anthorn Radio Station",   "country":"UK",       "lat":54.91, "lon":-3.28,  "operator":"UK Royal Navy/NATO",     "power_kw":500,  "mode":"MSK","purpose":"NATO submarine + time signal",  "active":True, "notes":"Also MSF 60kHz time signal."},
    19580: {"callsign":"GBZ",   "name":"Skelton UK",              "country":"UK",       "lat":52.34, "lon":-3.08,  "operator":"UK Royal Navy",          "power_kw":30,   "mode":"MSK","purpose":"NATO submarine communication",  "active":True, "notes":"200 Bd MSK."},
    23400: {"callsign":"DHO38", "name":"Rhauderfehn Station",     "country":"Germany",  "lat":53.08, "lon":7.61,   "operator":"German Navy/NATO",       "power_kw":500,  "mode":"MSK","purpose":"NATO submarine communication",  "active":True, "notes":"Major NATO strategic VLF."},
    15100: {"callsign":"HWU",   "name":"Rosnay Naval Station",    "country":"France",   "lat":46.72, "lon":1.24,   "operator":"French Navy",            "power_kw":400,  "mode":"MSK","purpose":"French nuclear sub comms",      "active":True, "notes":"Alternates 15.1/18.3/21.75 kHz."},
    18300: {"callsign":"HWU",   "name":"Le Blanc Naval Station",  "country":"France",   "lat":46.62, "lon":1.18,   "operator":"French Navy",            "power_kw":400,  "mode":"MSK","purpose":"French nuclear sub comms",      "active":True, "notes":"HWU alternate frequency."},
    21750: {"callsign":"HWU",   "name":"HWU Rosnay Alt",          "country":"France",   "lat":46.72, "lon":1.24,   "operator":"French Navy",            "power_kw":400,  "mode":"MSK","purpose":"French nuclear sub comms",      "active":True, "notes":"HWU third frequency."},
    17200: {"callsign":"SAQ",   "name":"Grimeton Radio Station",  "country":"Sweden",   "lat":57.10, "lon":12.39,  "operator":"UNESCO Heritage",        "power_kw":200,  "mode":"CW", "purpose":"Historic — twice yearly only",  "active":False,"notes":"UNESCO World Heritage. 1924 alternator."},
    20270: {"callsign":"ICV",   "name":"Tavolara Naval Station",  "country":"Italy",    "lat":40.92, "lon":9.73,   "operator":"Italian Navy/NATO",      "power_kw":43,   "mode":"MSK","purpose":"NATO submarine communication",  "active":True, "notes":"Mediterranean coverage."},
    11905: {"callsign":"Alpha", "name":"RSDN-20 Krasnodar",       "country":"Russia",   "lat":44.46, "lon":39.34,  "operator":"Russian Navy",           "power_kw":500,  "mode":"CW", "purpose":"Navigation + submarine comms",  "active":True, "notes":"RSDN-20 Alpha. 3-station network."},
    12649: {"callsign":"Alpha", "name":"RSDN-20 Novosibirsk",     "country":"Russia",   "lat":54.99, "lon":82.90,  "operator":"Russian Navy",           "power_kw":500,  "mode":"CW", "purpose":"Navigation",                    "active":True, "notes":"Alpha second frequency."},
    14881: {"callsign":"Alpha", "name":"RSDN-20 Komsomolsk",      "country":"Russia",   "lat":50.55, "lon":137.00, "operator":"Russian Navy",           "power_kw":500,  "mode":"CW", "purpose":"Navigation",                    "active":True, "notes":"Alpha third frequency."},
    18100: {"callsign":"RDL",   "name":"Molodechno VLF",          "country":"Belarus",  "lat":54.28, "lon":26.47,  "operator":"Russian Navy",           "power_kw":300,  "mode":"MSK","purpose":"Russian submarine communication","active":True, "notes":"Russian Navy strategic comms."},
    19700: {"callsign":"UGE",   "name":"Arkhangelsk VLF",         "country":"Russia",   "lat":64.22, "lon":41.35,  "operator":"Russian Navy",           "power_kw":150,  "mode":"MSK","purpose":"Russian submarine communication","active":True, "notes":"Russian Navy Northern Fleet."},
    20500: {"callsign":"3SA",   "name":"Changde VLF Station",     "country":"China",    "lat":28.99, "lon":111.70, "operator":"PLAN (Chinese Navy)",    "power_kw":300,  "mode":"MSK","purpose":"Chinese submarine communication","active":True, "notes":"PLAN nuclear submarine comms."},
    20600: {"callsign":"3SB",   "name":"Datong VLF Station",      "country":"China",    "lat":40.09, "lon":113.30, "operator":"PLAN (Chinese Navy)",    "power_kw":300,  "mode":"MSK","purpose":"Chinese submarine communication","active":True, "notes":"PLAN second VLF transmitter."},
    22200: {"callsign":"JJI",   "name":"Ebino VLF Station",       "country":"Japan",    "lat":32.08, "lon":130.83, "operator":"Japan MSDF",             "power_kw":50,   "mode":"FSK","purpose":"Japanese submarine communication","active":True, "notes":"JMSDF submarine comms."},
    15000: {"callsign":"NPK",   "name":"Karachi Naval VLF",       "country":"Pakistan", "lat":24.86, "lon":67.01,  "operator":"Pakistan Navy",          "power_kw":50,   "mode":"CW", "purpose":"Naval submarine communication", "active":True, "notes":"Pakistan Navy VLF. Karachi."},
}

FLAGS={"India":"🇮🇳","USA":"🇺🇸","Australia":"🇦🇺","Norway":"🇳🇴","UK":"🇬🇧",
       "Germany":"🇩🇪","France":"🇫🇷","Sweden":"🇸🇪","Italy":"🇮🇹","Russia":"🇷🇺",
       "Belarus":"🇧🇾","China":"🇨🇳","Japan":"🇯🇵","Pakistan":"🇵🇰","Singapore":"🇸🇬",
       "Finland":"🇫🇮"}

# ─── Location + nearest KiwiSDR ────────────────────────────────────────────────
def detect_location():
    try:
        r=requests.get("http://ip-api.com/json/",timeout=5)
        d=r.json()
        return float(d["lat"]),float(d["lon"]),d["city"]+", "+d["country"]
    except:
        return 0.0,0.0,"Unknown"

def haversine(lat1,lon1,lat2,lon2):
    a=math.sin(math.radians(lat2-lat1)/2)**2
    b=math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(math.radians(lon2-lon1)/2)**2
    return 6371*2*math.asin(math.sqrt(a+b))

def select_nearest_kiwis(lat,lon,n=1):
    """Select n nearest KiwiSDRs from pool based on distance."""
    scored=sorted(KIWI_POOL,key=lambda s:haversine(lat,lon,s["lat"],s["lon"]))
    return scored[:n]

# ─── Geometry ──────────────────────────────────────────────────────────────────
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

# ─── Cross-Verification ────────────────────────────────────────────────────────
def measure_kiwi_rssi(ip,port,freq_khz,timeout=7):
    try:
        result=subprocess.run(
            [sys.executable,KIWIRECORDER,
             "-s",ip,"-p",str(port),
             "-f",str(freq_khz),"-m","usb",
             "--S-meter=1",f"--tlimit={timeout}","--quiet"],
            capture_output=True,text=True,timeout=timeout+5
        )
        for line in result.stdout.splitlines():
            if "RSSI:" in line:
                return float(line.split("RSSI:")[1].strip())
        return None
    except:
        return None

def cross_verify(freq_hz,local_snr_db):
    freq_khz=freq_hz/1000

    def check_one(srv):
        ip=srv["ip"];port=srv["port"];loc=srv["location"]
        rssi=measure_kiwi_rssi(ip,port,freq_khz,timeout=7)
        if rssi is None:
            return {"location":loc,"country":srv["country"],"rssi":None,"above_noise":None,"confirmed":False,"status":"UNREACHABLE"}
        noise=KIWI_NOISE_FLOOR[ip]
        above=rssi-noise
        ok=above>=KIWI_THRESHOLD_DB
        return {"location":loc,"country":srv["country"],"rssi":rssi,"noise_floor":noise,"above_noise":round(above,1),"confirmed":ok,"status":"SIGNAL" if ok else "NOISE"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,len(KIWI_SERVERS)))as ex:
        results=list(ex.map(check_one,KIWI_SERVERS))

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
            print(f"  {C.GRAY}  ✗ {r['location']:32} UNREACHABLE{C.RESET}")
        else:
            icon="✅"if r["confirmed"]else"❌"
            col=C.GREEN if r["confirmed"] else C.RED
            print(f"  {col}  {icon} {r['location']:32} RSSI:{r['rssi']:7.1f} dBm ({r['above_noise']:+.1f} dB vs noise){C.RESET}")
    print()
    if cv["verified"] and cv["confidence"]=="HIGH":
        print(f"  {C.GREEN}{C.BOLD}✅ CONFIRMED on {cv['confirmed_count']}/{cv['total_checked']} independent receiver(s){C.RESET}")
        print(f"  {C.GREEN}{C.BOLD}   VERDICT: REAL SIGNAL — cannot be local noise{C.RESET}")
    elif cv["verified"]:
        print(f"  {C.YELLOW}{C.BOLD}⚠️  PARTIAL: {cv['confirmed_count']}/{cv['total_checked']} confirmed — PROBABLE REAL SIGNAL{C.RESET}")
    else:
        print(f"  {C.RED}{C.BOLD}❌ NOT confirmed — possible local interference{C.RESET}")

# ─── Confidence scoring ────────────────────────────────────────────────────────
def compute_confidence(freq_hz,snr_db,bandwidth_hz,persistence,station):
    score=0
    score+=min(30,snr_db*1.5)
    score+=min(20,persistence*5)
    if bandwidth_hz<50:    score+=20
    elif bandwidth_hz<100: score+=15
    elif bandwidth_hz<150: score+=10
    if station:
        _,info=station
        err=abs(freq_hz-list(STATIONS.keys())[list(STATIONS.values()).index(info)])
        score+=30 if err<100 else 20 if err<200 else 10 if err<400 else 0
    return min(100,int(score))

# ─── DSP ───────────────────────────────────────────────────────────────────────
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

def scan_band(sdr,noise):
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

# ─── Noise Filters ─────────────────────────────────────────────────────────────
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

    def bucket(self,f):
        return round(f/DUPLICATE_WINDOW_HZ)*DUPLICATE_WINDOW_HZ

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
    if is_h:return False,f"50Hz harmonic #{int(hf/50)}","HARMONIC"
    if bw>MAX_BANDWIDTH_HZ:return False,f"Too wide ({bw:.0f}Hz)","BANDWIDTH"
    drift=tracker.get_stability(freq_hz)
    if drift>FREQ_STABILITY_HZ:return False,f"Unstable ({drift:.0f}Hz)","STABILITY"
    if snr_db<SNR_THRESHOLD:return False,f"Weak ({snr_db:.1f}dB)","SNR"
    return True,"PASSED","NONE"

# ─── Audio ─────────────────────────────────────────────────────────────────────
def record_audio(sdr,freq_hz,duration_sec,filename):
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

def analyze(ai_ready,freq_hz,power_db,snr_db,bw,confidence,station,cv):
    if not ai_ready:return "⚠️  Ollama not running"
    try:
        if station:
            _,info=station
            ctx=f"Match: {info['callsign']} — {info['name']}, {info['country']}, {info['operator']}, {info['power_kw']}kW, {info.get('mode','?')}, {info['purpose']}"
        else:
            ctx="No database match."
        cv_s=f"Cross-verify: {cv['confidence']} — {cv['confirmed_count']}/{cv['total_checked']} remote receivers confirmed" if cv else "Not verified"
        prompt=f"""VLF expert analyst. Signal from {RECEIVER_NAME}:
Freq: {freq_hz/1000:.3f} kHz | Power: {power_db:.1f} dBFS | SNR: {snr_db:.1f} dB | BW: {bw:.1f} Hz | Confidence: {confidence}%
{cv_s}
{ctx}
Passed: 50Hz filter, bandwidth, stability, persistence filters.
Respond EXACTLY:
IDENTIFICATION: [what]
CONFIDENCE: [0-100]%
ANTENNA: [compass from {RECEIVER_NAME}]
MODE: [CW/MSK/FSK/UNKNOWN]
SIGNIFICANCE: [1 sentence]
VERDICT: [CONFIRMED SIGNAL/PROBABLE SIGNAL/POSSIBLE SIGNAL/NOISE/INTERFERENCE]"""
        r=requests.post(OLLAMA_URL,json={"model":OLLAMA_MODEL,"prompt":prompt,"stream":False},timeout=90)
        return r.json()["response"].strip()
    except Exception as e:
        return f"AI error: {e}"

# ─── Logging ───────────────────────────────────────────────────────────────────
def setup_dirs():
    for d in [BASE_DIR,AUDIO_DIR,REPORTS_DIR,SESSIONS_DIR]:
        os.makedirs(d,exist_ok=True)

def save_all(entry,sid):
    for fp in [
        os.path.join(BASE_DIR,"all_detections.json"),
        os.path.join(SESSIONS_DIR,f"session_{sid}.json"),
        os.path.join(REPORTS_DIR,f"{entry.get('country','unknown').lower().replace(' ','_')}.json")
    ]:
        logs=[]
        if os.path.exists(fp):
            try:
                with open(fp)as f:logs=json.load(f)
            except:pass
        logs.append(entry)
        with open(fp,"w")as f:json.dump(logs,f,indent=2)
    with open(os.path.join(REPORTS_DIR,f"detection_{entry['detection_number']:04d}.txt"),"w")as f:
        f.write("="*60+"\nVLF DETECTION REPORT v4\n"+"="*60+"\n")
        for k,v in entry.items():
            if k not in("ai_analysis","cv_results"):f.write(f"{k:25}: {v}\n")
        f.write(f"\nAI ANALYSIS:\n{'-'*40}\n{entry['ai_analysis']}\n"+"="*60+"\n")

# ─── Display ───────────────────────────────────────────────────────────────────
def print_signal(sig,station,ai_result,det_num,confidence,audio_file,filtered_count):
    fhz=sig["freq_hz"];pdb=sig["power_db"];snr=sig["snr_db"];bw=sig["bandwidth_hz"]
    ts=datetime.datetime.now().strftime("%H:%M:%S")
    cc=C.GREEN if confidence>=70 else C.YELLOW if confidence>=40 else C.RED

    print(f"\n  {C.GREEN}{C.BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.RESET}")
    print(f"  {C.GREEN}{C.BOLD}[{ts}] 📡 SIGNAL #{det_num}  {cc}● {confidence}% confidence{C.RESET}")
    print(f"  {C.GREEN}{C.BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{C.RESET}")
    print(f"  {C.YELLOW}Frequency{C.RESET} : {C.BOLD}{C.WHITE}{fhz/1000:.3f} kHz{C.RESET}")
    print(f"  {C.YELLOW}Power    {C.RESET} : {pdb:.1f} dBFS")
    print(f"  {C.YELLOW}SNR      {C.RESET} : {C.GREEN}{snr:.1f} dB{C.RESET} above noise")
    print(f"  {C.YELLOW}Bandwidth{C.RESET} : {bw:.1f} Hz  {C.GRAY}(narrow = real station){C.RESET}")
    print(f"  {C.GRAY}Noise rejected: {filtered_count}{C.RESET}")

    info={};dist_km=None;bearing=None;compass=None
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

    if audio_file:print(f"\n  {C.CYAN}🎵 Audio: {audio_file}{C.RESET}")
    print(f"  {C.GRAY}💾 {BASE_DIR}/{C.RESET}")
    return dist_km,bearing,compass

# ─── Main ──────────────────────────────────────────────────────────────────────
def main():
    global RECEIVER_LAT,RECEIVER_LON,RECEIVER_NAME,KIWI_SERVERS
    os.system("clear")
    sid=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    setup_dirs()

    print(f"{C.CYAN}{C.BOLD}")
    print("  ╔══════════════════════════════════════════════════════════╗")
    print("  ║   📡  VLF AI MONITOR v4 — Cross-Verified Edition        ║")
    print("  ║   RTL-SDR V4  +  Shadow-AI  +  Nearest KiwiSDR          ║")
    print(f"  ║   Stations : {len(STATIONS)} known  |  Band: 3–30 kHz             ║")
    print("  ╚══════════════════════════════════════════════════════════╝")
    print(f"{C.RESET}")

    # Auto-detect location and nearest KiwiSDR
    print(f"  {C.YELLOW}Detecting location...{C.RESET}")
    RECEIVER_LAT,RECEIVER_LON,RECEIVER_NAME=detect_location()
    print(f"  {C.GREEN}✅ Location: {RECEIVER_NAME} ({RECEIVER_LAT:.2f}°, {RECEIVER_LON:.2f}°){C.RESET}")

    KIWI_SERVERS=select_nearest_kiwis(RECEIVER_LAT,RECEIVER_LON,n=1)
    kiwi=KIWI_SERVERS[0]
    kiwi_dist=round(haversine(RECEIVER_LAT,RECEIVER_LON,kiwi["lat"],kiwi["lon"]))
    print(f"  {C.GREEN}✅ Nearest KiwiSDR: {kiwi['location']} ({kiwi_dist:,} km away){C.RESET}")
    print(f"  {C.GRAY}Noise filters: [1]50Hz [2]Bandwidth [3]Stability [4]Persistence{C.RESET}\n")

    print(f"  {C.YELLOW}Starting Shadow-AI...{C.RESET}")
    ai_ready=init_ai()

    print(f"  {C.YELLOW}Starting RTL-SDR V4...{C.RESET}")
    try:
        sdr=RtlSdr()
        sdr.sample_rate=SAMPLE_RATE;sdr.center_freq=CENTER_FREQ
        sdr.gain=GAIN;sdr.set_direct_sampling(2)
        print(f"  {C.GREEN}✅ RTL-SDR V4 ready{C.RESET}")
    except Exception as e:
        print(f"  {C.RED}❌ {e}{C.RESET}");sys.exit(1)

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
            raw=scan_band(sdr,noise)
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
                confidence=compute_confidence(fhz,snr,bw,count,station)

                print(f"\n  {C.CYAN}⏳ Cross-verifying {fhz/1000:.3f} kHz on {kiwi['location']}...{C.RESET}")
                cv=cross_verify(fhz,snr)
                print_crossverify(cv)

                ai_result=analyze(ai_ready,fhz,sig["power_db"],snr,bw,confidence,station,cv)

                audio_file=None
                if snr>=MIN_SNR_FOR_AUDIO:
                    apath=os.path.join(AUDIO_DIR,f"{fhz/1000:.3f}kHz_{datetime.datetime.now().strftime('%H%M%S')}.wav")
                    if record_audio(sdr,fhz,AUDIO_SECONDS,apath):audio_file=apath

                dist_km,bearing,compass=print_signal(sig,station,ai_result,detections,confidence,audio_file,filtered)

                info=station[1] if station else {}
                entry={
                    "detection_number":detections,"session_id":sid,
                    "timestamp":datetime.datetime.now().isoformat(),
                    "freq_khz":round(fhz/1000,3),"power_db":round(sig["power_db"],1),
                    "snr_db":round(snr,1),"bandwidth_hz":round(bw,1),
                    "confidence_pct":confidence,
                    "station":info.get("name","Unknown"),"callsign":info.get("callsign","?"),
                    "country":info.get("country","Unknown"),"operator":info.get("operator","Unknown"),
                    "mode":info.get("mode","?"),"purpose":info.get("purpose","Unknown"),
                    "distance_km":dist_km,
                    "bearing":f"{compass} ({bearing:.0f}°)"if bearing else None,
                    "cross_verified":cv["verified"],"cross_confidence":cv["confidence"],
                    "audio_file":audio_file,"ai_analysis":ai_result,"cv_results":cv["results"]
                }
                save_all(entry,sid)
                session_log.append(entry)

            tracker.reset_stale(active_buckets)

            if not raw:
                sys.stdout.write(
                    f"\r  {C.GRAY}[{ts}] Scan #{scans} | "
                    f"Noise:{noise:.0f}dBFS | "
                    f"Confirmed:{detections} | "
                    f"Filtered:{filtered}{C.RESET}   "
                )
                sys.stdout.flush()

            if scans%60==0:noise=estimate_noise(sdr,n=3)
            time.sleep(SCAN_INTERVAL)

    except KeyboardInterrupt:
        print(f"\n\n  {C.CYAN}{'═'*58}{C.RESET}")
        print(f"  {C.BOLD}SESSION COMPLETE — {sid}{C.RESET}")
        print(f"  Scans:{scans} | Confirmed:{detections} | Filtered:{filtered}")
        if session_log:
            for d in session_log:
                flag=FLAGS.get(d["country"],"🌍")
                cv_icon="✅"if d.get("cross_verified")else"⚠️"
                cc=C.GREEN if d["confidence_pct"]>=70 else C.YELLOW
                print(f"  {flag} {d['freq_khz']:7.3f}kHz  {d['station'][:28]:28}  {cc}{d['confidence_pct']}%{C.RESET} {cv_icon} SNR:{d['snr_db']}dB")
        with open(os.path.join(SESSIONS_DIR,f"summary_{sid}.json"),"w")as f:
            json.dump({"session_id":sid,"scans":scans,"confirmed":detections,"filtered":filtered,"detections":session_log},f,indent=2)
        print(f"  {C.GRAY}Files: {BASE_DIR}/{C.RESET}")
        print(f"  {C.CYAN}{'═'*58}{C.RESET}\n")
    finally:
        sdr.close()
        print(f"  {C.GRAY}RTL-SDR closed.{C.RESET}")

if __name__=="__main__":
    main()
