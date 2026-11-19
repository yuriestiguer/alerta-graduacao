# 19/11/2026: ALERTA DE GRADUAÇÃO — meme pareado com ação tokenizada (ou com outro meme "moeda de lançamento")
# Como detecta: lê na blockchain (RPC público, getProgramAccounts) todas as pools da PumpSwap cujo par (quote) é cada
# ação/meme vigiado. Pool que aparece entre duas leituras = meme acabou de graduar.
# Depois acompanha cada meme por 24h no DexScreener e avisa em 3 níveis: graduou / US$100k em 1h / US$1M em 24h.
# Só LEITURA: não tem chave de carteira, não mexe em dinheiro.
# Uso: python alerta_graduacao.py [--estado PASTA] [--enviar]   (sem --enviar só imprime as mensagens)
import json, os, sys, time, urllib.request, argparse, base64
import ssl
try:
    import certifi; CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError: CTX = ssl.create_default_context()

here = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--estado", default=os.path.join(here, "estado"))
ap.add_argument("--enviar", action="store_true")
args = ap.parse_args()
os.makedirs(args.estado, exist_ok=True)
EST = os.path.join(args.estado, "estado.json")
RPC = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
OFF_BASE, OFF_QUOTE = 43, 75
ACOMPANHA_H = 24
NIVEIS = [("vol1h", 100_000, "🔥 US$100 mil em 1h"), ("vol24", 1_000_000, "🚀 US$1 milhão em 24h")]
PROMOVE_MEME = 1_000_000          # meme c/ ≥ US$1M/24h vira "moeda de lançamento" vigiada
# ações onde a pool da Meteora PEGOU taxa no estudo de 18/11 (estratégia 3). Resto = só estratégia 2.
CAPTA = {"AMD", "AVGOx", "ANTHROPIC", "TTWO", "ANDURIL", "NEURALINK", "POLYMARKET", "NVDAx", "DJT"}

def http(url, data=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data, {"User-Agent": "alerta-graduacao", "Accept": "application/json",
                                                     "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60, context=CTX) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (400, 404): return None
            time.sleep(3 + 5 * i)
        except Exception: time.sleep(3 + 3 * i)
    return None

def rpc(method, params):
    r = http(RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode())
    return (r or {}).get("result")

def b58(b):
    A = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    n = int.from_bytes(b, "big"); s = ""
    while n: n, r = divmod(n, 58); s = A[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s

def pools_da_quote(mint):
    r = rpc("getProgramAccounts", [PUMPSWAP, {"encoding": "base64", "dataSlice": {"offset": OFF_BASE, "length": 32},
                                              "filters": [{"memcmp": {"offset": OFF_QUOTE, "bytes": mint}}]}])
    if r is None: return None
    return {a["pubkey"]: b58(base64.b64decode(a["account"]["data"][0])) for a in r}

def dex_pairs(addrs):
    out = {}
    for i in range(0, len(addrs), 30):
        d = http("https://api.dexscreener.com/latest/dex/pairs/solana/" + ",".join(addrs[i:i + 30]))
        for p in (d or {}).get("pairs") or []: out[p["pairAddress"]] = p
        time.sleep(0.3)
    return out

def dlmm_do_meme(meme_mint):
    d = http(f"https://api.dexscreener.com/token-pairs/v1/solana/{meme_mint}") or []
    r = [p for p in d if p.get("dexId") == "meteora" and "DLMM" in (p.get("labels") or [])]
    return [(f'{p["baseToken"]["symbol"]}/{p["quoteToken"]["symbol"]}', (p.get("liquidity") or {}).get("usd") or 0) for p in r]

def usd(v):
    v = v or 0
    return f"US$ {v/1e6:.1f} mi" if v >= 1e6 else f"US$ {v/1e3:.0f} mil" if v >= 1e3 else f"US$ {v:.0f}"

def mensagem(titulo, pl, q, p):
    meme = p["baseToken"]["symbol"] if p else pl["base"][:6]
    par = q["sym"]
    if q["tipo"] == "meme": estr = "par é MEME (2º nível) → estratégia 2; risco dobrado"
    elif par in CAPTA: estr = f"pool {par} na Meteora costuma captar → estratégia 3 (e 2)"
    else: estr = f"pool {par} na Meteora não costuma captar → só estratégia 2"
    linhas = [f"{titulo}: {meme} / {par}", estr]
    if p:
        v = p.get("volume") or {}
        idade = (time.time() - (p.get("pairCreatedAt") or time.time() * 1000) / 1000) / 3600
        linhas.append(f"volume 1h {usd(v.get('h1'))} · 24h {usd(v.get('h24'))} · liquidez {usd((p.get('liquidity') or {}).get('usd'))} · valor de mercado {usd(p.get('fdv'))} · {idade:.1f}h de PumpSwap")
        linhas.append(p.get("url", ""))
    if titulo != "🎓 Graduou":
        dl = dlmm_do_meme(pl["base"])
        linhas.append("DLMM do meme na Meteora: " + ("; ".join(f"{n} {usd(l)}" for n, l in dl) if dl else "NENHUMA ainda (vaga p/ ser a 1ª ponte)"))
    return "\n".join(linhas)

def telegram(txt):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat): print("[sem TELEGRAM_*: não enviado]"); return
    http(f"https://api.telegram.org/bot{tok}/sendMessage",
         json.dumps({"chat_id": chat, "text": txt, "disable_web_page_preview": True}).encode())

# ---------------- estado
est = json.load(open(EST, encoding="utf-8")) if os.path.exists(EST) else {"quotes": {}, "pools": {}}
if not est["quotes"]:
    res = json.load(open(os.path.join(here, "acoes.json"), encoding="utf-8"))
    est["quotes"] = {r["mint"]: {"sym": r["sym"], "tipo": "acao", "base_ok": False} for r in res}
    primeira_vez = True
else: primeira_vez = False
agora = time.time()
msgs = []
novos = 0
falhas = 0
for mint, q in list(est["quotes"].items()):
    ps = pools_da_quote(mint)
    time.sleep(0.25)
    if ps is None: print("falha RPC", q["sym"], file=sys.stderr); falhas += 1; continue
    for pool, base in ps.items():
        if pool in est["pools"]: continue
        est["pools"][pool] = {"base": base, "quote": mint, "visto": agora, "avisos": [], "acompanha": q["base_ok"]}
        if q["base_ok"]: novos += 1
    q["base_ok"] = True       # 1ª leitura de cada quote = só registra o que já existe, sem avisar

# ---------------- acompanhar memes recentes (últimas 24h)
ativos = [a for a, pl in est["pools"].items() if pl["acompanha"] and agora - pl["visto"] < ACOMPANHA_H * 3600]
info = dex_pairs(ativos) if ativos else {}
for a in ativos:
    pl, p = est["pools"][a], info.get(a)
    q = est["quotes"][pl["quote"]]
    # "graduou" sozinho NÃO avisa: em nov/26 foram ~120 graduações/dia (spam). Só avisa quando o volume pega.
    if not p: continue
    v = p.get("volume") or {}
    for chave, lim, tit in NIVEIS:
        val = v.get("h1") if chave == "vol1h" else v.get("h24")
        if (val or 0) >= lim and chave not in pl["avisos"]:
            msgs.append(mensagem(tit, pl, q, p)); pl["avisos"].append(chave)
    if (v.get("h24") or 0) >= PROMOVE_MEME and pl["base"] not in est["quotes"]:
        est["quotes"][pl["base"]] = {"sym": p["baseToken"]["symbol"], "tipo": "meme", "base_ok": False, "desde": agora}
        msgs.append(f"➕ {p['baseToken']['symbol']} passou a ser vigiado como moeda de lançamento (memes lançados com ele de par)")

# limpa pools antigas do acompanhamento (mantém registro p/ não re-alertar)
for pl in est["pools"].values():
    if pl["acompanha"] and agora - pl["visto"] >= ACOMPANHA_H * 3600: pl["acompanha"] = False
json.dump(est, open(EST, "w", encoding="utf-8"))
print(f"quotes vigiadas {len(est['quotes'])} · pools conhecidas {len(est['pools'])} · novas nesta leitura {novos} · mensagens {len(msgs)}", file=sys.stderr)
if primeira_vez: msgs.insert(0, f"✅ Alerta de memes ligado: vigiando {len(est['quotes'])} ações tokenizadas ({len(est['pools'])} memes já graduados registrados). Aviso quando um meme novo passar de US$100 mil em 1h ou US$1 milhão em 24h.")
for m in msgs:
    print("-----\n" + m)
    if args.enviar: telegram(m); time.sleep(1)
if falhas > len(est["quotes"]) / 2:
    sys.exit(f"ERRO: {falhas} leituras falharam (RPC fora/limitado)")
