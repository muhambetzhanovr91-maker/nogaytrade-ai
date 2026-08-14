
import os, math
from datetime import date, timedelta
import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)
FINNHUB = os.getenv("FINNHUB_API_KEY", "").strip()
ALPHA = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
BASE = "https://finnhub.io/api/v1"

def fh(endpoint, params):
    if not FINNHUB:
        raise RuntimeError("FINNHUB_API_KEY орнатылмаған")
    p = dict(params)
    p["token"] = FINNHUB
    r = requests.get(BASE + endpoint, params=p, timeout=12)
    r.raise_for_status()
    return r.json()

def sma(values, n):
    if len(values) < n: return None
    return sum(values[-n:]) / n

def ema(values, n):
    if len(values) < n: return None
    k = 2/(n+1)
    e = sum(values[:n])/n
    for x in values[n:]:
        e = x*k + e*(1-k)
    return e

def rsi(values, n=14):
    if len(values) < n+1: return None
    gains=[]; losses=[]
    for a,b in zip(values[-(n+1):-1], values[-n:]):
        d=b-a
        gains.append(max(d,0)); losses.append(max(-d,0))
    ag=sum(gains)/n; al=sum(losses)/n
    if al == 0: return 100.0
    return 100 - 100/(1+ag/al)

def macd(values):
    if len(values) < 35: return None, None
    e12=ema(values,12); e26=ema(values,26)
    return e12-e26, None

def alpha_daily(symbol):
    if not ALPHA: return None
    url="https://www.alphavantage.co/query"
    p={"function":"TIME_SERIES_DAILY","symbol":symbol,"outputsize":"compact","apikey":ALPHA}
    r=requests.get(url,params=p,timeout=15); r.raise_for_status()
    data=r.json().get("Time Series (Daily)")
    if not data: return None
    rows=sorted(data.items())
    closes=[float(v["4. close"]) for _,v in rows]
    highs=[float(v["2. high"]) for _,v in rows]
    lows=[float(v["3. low"]) for _,v in rows]
    vols=[float(v["5. volume"]) for _,v in rows]
    return {"closes":closes,"highs":highs,"lows":lows,"volumes":vols,"dates":[d for d,_ in rows]}

def technical(symbol, quote):
    d=alpha_daily(symbol)
    if not d:
        return {"available":False,"message":"Техникалық тарих үшін ALPHAVANTAGE_API_KEY қосылмаған."}
    c=d["closes"]
    r=rsi(c)
    e20=ema(c,20); e50=ema(c,50); e200=ema(c,200)
    m, _=macd(c)
    avgvol=sma(d["volumes"],20)
    vol_ratio=(d["volumes"][-1]/avgvol) if avgvol else None
    score=50
    if r is not None:
        score += 12 if 45 <= r <= 65 else (5 if 35 <= r < 45 or 65 < r <= 75 else -8)
    if e20 and e50: score += 12 if e20 > e50 else -8
    if e50 and e200: score += 12 if e50 > e200 else -8
    if m is not None: score += 8 if m > 0 else -5
    if vol_ratio is not None: score += 6 if vol_ratio >= 1.2 else 0
    score=max(0,min(100,round(score)))
    return {"available":True,"rsi":round(r,2) if r is not None else None,
            "ema20":round(e20,2) if e20 else None,"ema50":round(e50,2) if e50 else None,
            "ema200":round(e200,2) if e200 else None,"macd":round(m,4) if m is not None else None,
            "volume_ratio":round(vol_ratio,2) if vol_ratio else None,"score":score}

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/analyze")
def analyze():
    symbol=request.args.get("symbol","RKLB").upper().strip()
    if not symbol or len(symbol)>10:
        return jsonify({"error":"Тикер қате."}),400
    try:
        q=fh("/quote",{"symbol":symbol})
        profile=fh("/stock/profile2",{"symbol":symbol})
        end=date.today(); start=end-timedelta(days=7)
        news=fh("/company-news",{"symbol":symbol,"from":start.isoformat(),"to":end.isoformat()})
        tech=technical(symbol,q)
        price=float(q.get("c") or 0)
        day_change=float(q.get("dp") or 0)
        news_items=[{"headline":n.get("headline",""),"source":n.get("source",""),"url":n.get("url",""),
                     "datetime":n.get("datetime")} for n in news[:8]]
        base_score=tech.get("score",60) if tech.get("available") else 60
        if day_change > 2: base_score += 5
        elif day_change < -2: base_score -= 5
        score=max(0,min(100,base_score))
        signal="BUY" if score>=75 else ("WAIT" if score>=55 else "SELL")
        return jsonify({
            "symbol":symbol,"name":profile.get("name",symbol),"exchange":profile.get("exchange",""),
            "currency":profile.get("currency","USD"),"price":price,"change":q.get("d"),"change_pct":day_change,
            "high":q.get("h"),"low":q.get("l"),"previous_close":q.get("pc"),
            "market_cap":profile.get("marketCapitalization"),"website":profile.get("weburl",""),
            "technical":tech,"score":score,"signal":signal,"news":news_items,
            "limitations":["Бұл MVP live quote/news алады.","Толық RSI/MACD/EMA үшін Alpha Vantage key қосылуы керек.","Инвестициялық шешім ретінде қабылдамаңыз."]
        })
    except Exception as e:
        return jsonify({"error":str(e)}),500

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","5000")),debug=True)
