# ALERTA DE GRADUAÇÃO — meme lançado com uma "moeda de lançamento" de par (ação tokenizada, outro meme, token)
# Como detecta: lê na blockchain (RPC público, getProgramAccounts) as pools da PumpSwap cujo par (quote) é cada
# moeda vigiada. Pool que aparece entre duas leituras = meme acabou de graduar (saiu da curva da pump.fun).
# Lista de moedas vigiadas se atualiza sozinha 1x/dia: varre TODAS as pools da PumpSwap e pega toda moeda usada
# como par em >= 5 pools (fora SOL/USDC/USDT/USD1, que são o mercado de memes inteiro).
# Avisa nas primeiras 24h (US$250k em 1h / US$1M em 24h) e REGISTRA até 72h p/ medir explosão tardia.
# Toda segunda manda resumo da semana. Só LEITURA: não tem chave de carteira, não mexe em dinheiro.
# Uso: python alerta_graduacao.py [--estado PASTA] [--enviar]   (sem --enviar só imprime as mensagens)
import json, os, sys, time, urllib.request, argparse, base64, re, collections, datetime as dt
import ssl
try:
    import certifi; CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError: CTX = ssl.create_default_context()

here = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--estado", default=os.path.join(here, "estado"))
ap.add_argument("--enviar", action="store_true")
ap.add_argument("--forcar-varredura", action="store_true")
ap.add_argument("--forcar-resumo", action="store_true")
args = ap.parse_args()
os.makedirs(args.estado, exist_ok=True)
EST = os.path.join(args.estado, "estado.json")
RPC = os.environ.get("SOLANA_RPC", "https://api.mainnet-beta.solana.com")
PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
OFF_BASE, OFF_QUOTE, TAM_POOL = 43, 75, 301
H = 3600
AVISA_ATE_H = 24                  # só manda aviso nas primeiras 24h do meme
REGISTRA_ATE_H = 72               # mas registra o volume até 72h (p/ decidir se vale estender)
NIVEIS = [("vol1h", 250_000, "🔥 US$250 mil em 1h"), ("vol24", 1_000_000, "🚀 US$1 milhão em 24h")]
PROMOVE_MEME = 1_000_000          # meme c/ ≥ US$1M/24h vira moeda vigiada na hora (sem esperar a varredura)
MIN_POOLS = 5                     # varredura diária: moeda usada como par em ≥ 5 pools entra na lista
ATIVA_DIAS = 7                    # moeda (não-ação) só é lida a cada 10 min se ganhou meme novo nos últimos 7 dias
EXCLUI = {"So11111111111111111111111111111111111111112": "SOL", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
          "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT", "USD1ttGY1N17NEEHLmELoaybftRBUSErhqYiQzvEmuB": "USD1"}
# ações onde a pool da Meteora PEGOU taxa no estudo de 18/11 (estratégia 3). Resto = só estratégia 2.
CAPTA = {"AMD", "AVGOx", "ANTHROPIC", "TTWO", "ANDURIL", "NEURALINK", "POLYMARKET", "NVDAx", "DJT"}

def http(url, data=None, tries=4, timeout=60, raw=False):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data, {"User-Agent": "alerta-graduacao", "Accept": "application/json",
                                                     "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r: return r.read() if raw else json.load(r)
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

def varredura_completa():
    """Conta, p/ cada moeda, em quantas pools da PumpSwap ela é o par. ~800 mil pools, ~200 MB, ~1 min."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getProgramAccounts", "params": [PUMPSWAP, {
        "encoding": "base64", "dataSlice": {"offset": OFF_QUOTE, "length": 32}, "filters": [{"dataSize": TAM_POOL}]}]}).encode()
    raw = http(RPC, body, tries=2, timeout=300, raw=True)
    if not raw: return None
    c = collections.Counter(re.findall(rb'"data":\["([A-Za-z0-9+/=]{44})","base64"\]', raw))
    if sum(c.values()) < 100_000: return None
    return {b58(base64.b64decode(k)): n for k, n in c.items()}

def dex_pairs(addrs):
    out = {}
    for i in range(0, len(addrs), 30):
        d = http("https://api.dexscreener.com/latest/dex/pairs/solana/" + ",".join(addrs[i:i + 30]))
        for p in (d or {}).get("pairs") or []: out[p["pairAddress"]] = p
        time.sleep(0.3)
    return out

def nomes_tokens(mints):
    out = {}
    for i in range(0, len(mints), 30):
        for p in http("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(mints[i:i + 30])) or []:
            for t in (p.get("baseToken") or {}, p.get("quoteToken") or {}):
                if t.get("address") in mints and t["address"] not in out: out[t["address"]] = (t.get("symbol") or "?", t.get("name") or "")
        time.sleep(0.3)
    return out

def tipo_por_nome(sym, nome):
    n = (nome or "").lower()
    if any(k in n for k in ("xstock", "tokenized", "ondo", "prestock", "backpack")): return "acao"
    return "moeda"

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
    elif q["tipo"] == "acao": estr = f"pool {par} na Meteora não costuma captar → só estratégia 2"
    else: estr = f"par é {par} (moeda/token, não é ação) → estratégia 2; conferir o que é {par}"
    linhas = [f"{titulo}: {meme} / {par}", estr]
    if p:
        v = p.get("volume") or {}
        idade = (time.time() - (p.get("pairCreatedAt") or time.time() * 1000) / 1000) / 3600
        linhas.append(f"volume 1h {usd(v.get('h1'))} · 24h {usd(v.get('h24'))} · liquidez {usd((p.get('liquidity') or {}).get('usd'))} · valor de mercado {usd(p.get('fdv'))} · {idade:.1f}h de PumpSwap")
        linhas.append(p.get("url", ""))
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
est.setdefault("varredura", {"ultima": 0, "contagem": {}})
est.setdefault("resumo", {"ultimo": 0})
primeira_vez = not est["quotes"]
agora = time.time()
msgs = []
for r in json.load(open(os.path.join(here, "acoes.json"), encoding="utf-8")):   # sementes: sempre vigiadas
    est["quotes"].setdefault(r["mint"], {"sym": r["sym"], "tipo": "acao", "base_ok": False, "desde": agora})

# ---------------- varredura diária: atualiza a lista de moedas usadas como par
if args.forcar_varredura or agora - est["varredura"]["ultima"] >= 23.5 * H:
    cont = varredura_completa()
    if cont is None: print("varredura falhou (tenta na próxima rodada)", file=sys.stderr)
    else:
        ant = est["varredura"]["contagem"]
        novas = [m for m, n in cont.items() if n >= MIN_POOLS and m not in EXCLUI and m not in est["quotes"]]
        nomes = nomes_tokens(novas) if novas else {}
        for m in novas:
            sym, nome = nomes.get(m, (m[:6], ""))
            est["quotes"][m] = {"sym": sym, "nome": nome, "tipo": tipo_por_nome(sym, nome), "base_ok": False, "desde": agora}
        for m, q in est["quotes"].items():
            if ant and cont.get(m, 0) > ant.get(m, 0): q["ultima_nova"] = agora     # ganhou meme novo desde ontem
            q["npools"] = cont.get(m, 0)
        est["varredura"] = {"ultima": agora, "contagem": {m: n for m, n in cont.items() if n >= 2},
                            "total_pools": sum(cont.values())}
        print(f"varredura: {sum(cont.values())} pools, {len(novas)} moedas novas na lista", file=sys.stderr)

def ativa(q):
    return q["tipo"] in ("acao", "meme") or agora - q.get("ultima_nova", 0) < ATIVA_DIAS * 86400

# ---------------- leitura das moedas ativas
novos = falhas = lidas = 0
for mint, q in list(est["quotes"].items()):
    if not ativa(q): continue
    ps = pools_da_quote(mint); lidas += 1
    time.sleep(0.25)
    if ps is None: print("falha RPC", q["sym"], file=sys.stderr); falhas += 1; continue
    for pool, base in ps.items():
        if pool in est["pools"]: continue
        est["pools"][pool] = {"base": base, "quote": mint, "visto": agora, "avisos": [], "acompanha": q["base_ok"], "novo": q["base_ok"]}
        if q["base_ok"]: novos += 1; q["ultima_nova"] = agora
    q["base_ok"] = True       # 1ª leitura de cada moeda = só registra o que já existe, sem avisar

# ---------------- acompanhar memes recentes: avisa até 24h, registra até 72h
seg = [a for a, pl in est["pools"].items() if pl["acompanha"]]
info = dex_pairs(seg) if seg else {}
for a in seg:
    pl, p = est["pools"][a], info.get(a)
    q = est["quotes"][pl["quote"]]
    if p and p.get("pairCreatedAt"): pl["t0"] = p["pairCreatedAt"] / 1000
    idade_h = (agora - pl.get("t0", pl["visto"])) / H
    if idade_h >= REGISTRA_ATE_H: pl["acompanha"] = False; continue
    if not p: continue
    v = p.get("volume") or {}
    dia = min(int(idade_h // 24), 2)
    mx = pl.setdefault("max24", [0, 0, 0]); mx[dia] = max(mx[dia], v.get("h24") or 0)
    pl["max1h"] = max(pl.get("max1h", 0), v.get("h1") or 0)
    pl["sym"] = p["baseToken"]["symbol"]
    for chave, lim, tit in NIVEIS:
        val = v.get("h1") if chave == "vol1h" else v.get("h24")
        if (val or 0) >= lim and chave not in pl["avisos"] and chave + "_tarde" not in pl["avisos"]:
            if idade_h < AVISA_ATE_H: msgs.append(mensagem(tit, pl, q, p)); pl["avisos"].append(chave)
            else: pl["avisos"].append(chave + "_tarde")        # só registra (entra no resumo semanal)
    if (v.get("h24") or 0) >= PROMOVE_MEME and pl["base"] not in est["quotes"] and pl["base"] not in EXCLUI:
        est["quotes"][pl["base"]] = {"sym": p["baseToken"]["symbol"], "tipo": "meme", "base_ok": False, "desde": agora}
        msgs.append(f"➕ {p['baseToken']['symbol']} passou a ser vigiado como moeda de lançamento (memes lançados com ele de par)")

# ---------------- resumo semanal (segunda, ~9h de Brasília)
agora_utc = dt.datetime.fromtimestamp(agora, dt.timezone.utc)
if args.forcar_resumo or (agora_utc.weekday() == 0 and agora_utc.hour == 12 and agora - est["resumo"]["ultimo"] > 2 * 86400):
    ini, fim = agora - 10 * 86400, agora - 3 * 86400       # memes que já completaram 72h de registro
    grad = [pl for pl in est["pools"].values() if pl.get("novo") and ini <= pl.get("t0", pl["visto"]) < fim]
    sem = [pl for pl in grad if "max24" in pl]
    d1 = [pl for pl in sem if pl["max24"][0] >= 1e6]
    tarde = [pl for pl in sem if pl["max24"][0] < 1e6 and max(pl["max24"][1:]) >= 1e6]
    av = collections.Counter(k for pl in sem for k in pl["avisos"])
    ql = [q for q in est["quotes"].values()]
    novas = [q["sym"] for q in ql if agora - q.get("desde", 0) < 7 * 86400 and q.get("tipo") != "acao"]
    f = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%d/%m")
    linhas = [f"📊 Resumo semanal — memes que graduaram de {f(ini)} a {f(fim)} (já com 72h acompanhadas)",
              f"• graduaram: {len(grad)} · com dados de volume: {len(sem)}",
              f"• passaram de US$1 mi em 24h já no 1º dia: {len(d1)}",
              f"• só passaram de US$1 mi no 2º ou 3º dia (perdidos pela janela de 24h): {len(tarde)}"
              + (" → " + ", ".join(pl.get("sym", "?") for pl in tarde[:8]) if tarde else ""),
              f"• avisos enviados: 🔥 {av['vol1h']} · 🚀 {av['vol24']}  (registrados depois de 24h, sem aviso: 🔥 {av['vol1h_tarde']} · 🚀 {av['vol24_tarde']})",
              f"• moedas vigiadas: {len(ql)} (lidas a cada 10 min: {sum(ativa(q) for q in ql)})"]
    if novas: linhas.append("• moedas novas na lista esta semana: " + ", ".join(novas[:15]) + (" …" if len(novas) > 15 else ""))
    msgs.append("\n".join(linhas))
    est["resumo"]["ultimo"] = agora

if primeira_vez: est["inicio"] = agora
json.dump(est, open(EST, "w", encoding="utf-8"))
print(f"moedas {len(est['quotes'])} (lidas {lidas}) · pools conhecidas {len(est['pools'])} · novas nesta leitura {novos} · em acompanhamento {sum(1 for pl in est['pools'].values() if pl['acompanha'])} · mensagens {len(msgs)}", file=sys.stderr)
if primeira_vez: msgs.insert(0, f"✅ Alerta de memes ligado: vigiando {len(est['quotes'])} moedas de lançamento ({len(est['pools'])} memes já graduados registrados). Aviso quando um meme novo passar de US$250 mil em 1h ou US$1 milhão em 24h.")
for m in msgs:
    print("-----\n" + m)
    if args.enviar: telegram(m); time.sleep(1)
if lidas and falhas > lidas / 2:
    sys.exit(f"ERRO: {falhas} de {lidas} leituras falharam (RPC fora/limitado)")
