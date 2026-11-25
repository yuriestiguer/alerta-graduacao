# ALERTA DE GRADUAÇÃO — meme lançado com uma "moeda de lançamento" de par (ação tokenizada, outro meme, token)
# Como detecta: lê na blockchain (RPC público, getProgramAccounts) as pools da PumpSwap cujo par (quote) é cada
# moeda vigiada. Pool que aparece entre duas leituras = meme acabou de graduar (saiu da curva da pump.fun).
# Lista de moedas vigiadas se atualiza sozinha a cada ~6h: varre TODAS as pools da PumpSwap e pega toda moeda usada
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
MIN_LIQ, MIN_MERCADO = 20_000, 50_000   # trava 19/11: abaixo disso o meme já morreu (ex.: NEKOMARIO) → não avisa
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
    out = [{"nome": f'{p["baseToken"]["symbol"]}/{p["quoteToken"]["symbol"]}', "addr": p["pairAddress"],
            "liq": (p.get("liquidity") or {}).get("usd") or 0, "v1h": (p.get("volume") or {}).get("h1") or 0} for p in r]
    return sorted(out, key=lambda x: -x["v1h"])

# Veredito automático (25/11, pedido do Yuri) — regras PROVISÓRIAS do teste com dinheiro real, a calibrar c/ o estudo:
VER_QUEDA_1H, VER_QUEDA_5M = -30, -15      # preço da pool principal caindo mais que isso → não entra
VER_DLMM_VOL1H = 2_000                     # pool DLMM precisa ter negócio na última hora (senão não há taxa)
VER_DLMM_SALDO = 1_000                     # e saldo mínimo (simulação: pools de US$30–100 renderam ~0 de taxa; US$50 viraria metade da pool)
def bloco_veredito(meme_mint, var5m, var1h):
    dl = dlmm_do_meme(meme_mint)
    linhas = [f"moeda (colar na busca, NÃO buscar pelo nome): {meme_mint}"]
    for x in dl[:3]:
        linhas.append(f"• DLMM {x['nome']} · saldo {usd(x['liq'])} · volume 1h {usd(x['v1h'])} → https://app.meteora.ag/dlmm/{x['addr']}")
    if not dl: linhas.append("• nenhuma pool DLMM do meme na Meteora")
    nao = []
    if var1h is not None and var1h <= VER_QUEDA_1H: nao.append(f"preço caiu {var1h:.0f}% na última hora")
    if var5m is not None and var5m <= VER_QUEDA_5M: nao.append(f"preço caindo {var5m:.0f}% nos últimos 5 min")
    boas = [x for x in dl if x["liq"] >= VER_DLMM_SALDO and x["v1h"] >= VER_DLMM_VOL1H]
    if not dl: nao.append("sem pool DLMM na Meteora")
    elif not boas: nao.append(f"nenhuma pool DLMM com saldo ≥ {usd(VER_DLMM_SALDO)} e volume ≥ {usd(VER_DLMM_VOL1H)} na última hora")
    if nao: linhas.append("❌ NÃO ENTRA: " + "; ".join(nao))
    else: linhas.append(f"✅ PASSA NO FILTRO → pool {boas[0]['nome']} https://app.meteora.ag/dlmm/{boas[0]['addr']}\nReceita: US$50, faixa −50%/+50% Spot, sair em 1h. Conferir o endereço da moeda e print antes de aprovar.")
    return linhas

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
        linhas.append(f"gráfico: https://dexscreener.com/solana/{p['pairAddress']}")
    pc = (p or {}).get("priceChange") or {}
    linhas += bloco_veredito(pl["base"], pc.get("m5"), pc.get("h1"))
    return "\n".join(linhas)

def telegram(txt):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat): print("[sem TELEGRAM_*: não enviado]"); return
    # 25/11 (pedido do Yuri): só o ✅ PASSA toca; o resto chega em silêncio. Cabeçalho no topo p/ aparecer na prévia do iPhone.
    passa = "✅ PASSA NO FILTRO" in txt
    if passa: txt = "🚨 ✅ PASSA NO FILTRO — vale olhar agora\n" + txt
    http(f"https://api.telegram.org/bot{tok}/sendMessage",
         json.dumps({"chat_id": chat, "text": txt, "disable_web_page_preview": True,
                     "disable_notification": not passa}).encode())

# ---------------- estado
est = json.load(open(EST, encoding="utf-8")) if os.path.exists(EST) else {"quotes": {}, "pools": {}}
est.setdefault("varredura", {"ultima": 0, "contagem": {}})
est.setdefault("resumo", {"ultimo": 0})
primeira_vez = not est["quotes"]
agora = time.time()
msgs = []
for r in json.load(open(os.path.join(here, "acoes.json"), encoding="utf-8")):   # sementes: sempre vigiadas
    est["quotes"].setdefault(r["mint"], {"sym": r["sym"], "tipo": "acao", "base_ok": False, "desde": agora})

# ---------------- varredura a cada ~6h: atualiza a lista de moedas usadas como par
if args.forcar_varredura or agora - est["varredura"]["ultima"] >= 5.5 * H:
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
            if ant and cont.get(m, 0) > ant.get(m, 0): q["ultima_nova"] = agora     # ganhou meme novo desde a última varredura
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
    vivo = ((p.get("liquidity") or {}).get("usd") or 0) >= MIN_LIQ and (p.get("fdv") or 0) >= MIN_MERCADO
    for chave, lim, tit in NIVEIS:
        val = v.get("h1") if chave == "vol1h" else v.get("h24")
        if (val or 0) >= lim and chave not in pl["avisos"] and chave + "_tarde" not in pl["avisos"]:
            if not vivo: pl["barrado"] = 1; continue            # bateu a meta mas já morreu: não avisa (pode avisar se reviver)
            if idade_h < AVISA_ATE_H: msgs.append(mensagem(tit, pl, q, p)); pl["avisos"].append(chave)
            else: pl["avisos"].append(chave + "_tarde")        # só registra (entra no resumo semanal)
    if vivo and (v.get("h24") or 0) >= PROMOVE_MEME and pl["base"] not in est["quotes"] and pl["base"] not in EXCLUI:
        est["quotes"][pl["base"]] = {"sym": p["baseToken"]["symbol"], "tipo": "meme", "base_ok": False, "desde": agora}
        msgs.append(f"➕ {p['baseToken']['symbol']} passou a ser vigiado como moeda de lançamento (memes lançados com ele de par)")

# ---------------- Fontes extras via GeckoTerminal (25/11, pedidos do Yuri). 1–3 consultas por rodada; falha não derruba o alarme.
# (a) StonkFun: memes de lá vão p/ a Raydium, não p/ a PumpSwap → a varredura acima não vê. Mesmas metas e travas.
# (b) MEME/SOL da PumpSwap (excluídos acima por serem ~100/dia, quase todos puxada de tapete — estudo 25/11):
#     só avisa c/ FILTRO COMPLETO: valor de mercado ≥ US$1M + pool DLMM na Meteora c/ saldo ≥ VER_DLMM_SALDO.
MEMESOL_MERCADO = 1_000_000
def fonte_gecko(nome, url, paginas, chave_est, rotulo, so_quote=None, piso_mercado=0, exige_dlmm=False):
    reg_all = est.setdefault(chave_est, {})
    for pg in range(1, paginas + 1):
        gk = http(f"{url}&page={pg}") or {}
        inc = {x["id"]: x["attributes"] for x in gk.get("included", [])}
        for d in gk.get("data", []):
            a, r = d["attributes"], d["relationships"]
            bid = r["base_token"]["data"]["id"]; b = inc.get(bid, {}); qq = inc.get(r["quote_token"]["data"]["id"], {})
            if so_quote and qq.get("address") != so_quote: continue
            criada = dt.datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00")).timestamp()
            idade_h = (agora - criada) / H
            if idade_h >= AVISA_ATE_H: continue
            v1, v24 = float(a["volume_usd"]["h1"] or 0), float(a["volume_usd"]["h24"] or 0)
            liq, fdv = float(a.get("reserve_in_usd") or 0), float(a.get("fdv_usd") or 0)
            reg = reg_all.setdefault(a["address"], {"avisos": [], "sym": b.get("symbol", "?"), "t0": criada})
            reg["max1h"] = max(reg.get("max1h", 0), v1); reg["max24"] = max(reg.get("max24", 0), v24)
            if liq < MIN_LIQ or fdv < max(MIN_MERCADO, piso_mercado): continue
            for chave, lim, tit in NIVEIS:
                val = v1 if chave == "vol1h" else v24
                if val < lim or chave in reg["avisos"]: continue
                meme_mint = bid.split("_", 1)[-1]
                if exige_dlmm and not any(x["liq"] >= VER_DLMM_SALDO for x in dlmm_do_meme(meme_mint)):
                    reg["sem_dlmm"] = 1; continue                  # sem pool DLMM c/ dinheiro: não avisa (pode avisar se surgir)
                reg["avisos"].append(chave)
                pc = a.get("price_change_percentage") or {}
                msgs.append("\n".join([
                    f"{tit}: {b.get('symbol', '?')} / {qq.get('symbol', '?')}  [{rotulo}]",
                    f"volume 1h {usd(v1)} · 24h {usd(v24)} · liquidez {usd(liq)} · valor de mercado {usd(fdv)} · {idade_h:.1f}h de vida",
                    f"gráfico: https://dexscreener.com/solana/{a['address']}",
                    ] + bloco_veredito(meme_mint, *(float(pc.get(k) or 0) for k in ("m5", "h1")))))
                reg["avisos"] = sorted(set(reg["avisos"]) | {c for c, l, _ in NIVEIS if (v1 if c == "vol1h" else v24) >= l})
                break                                              # 1 mensagem por meme por rodada (não duplica 1h + 24h)
    for k in [k for k, x in reg_all.items() if agora - x.get("t0", agora) > 7 * 86400]: del reg_all[k]   # registro curto (7 dias)

GK = "https://api.geckoterminal.com/api/v2/networks/solana/dexes"
for args_f in (("StonkFun", f"{GK}/stonkfun/pools?sort=h24_volume_usd_desc&include=base_token,quote_token", 1, "stonkfun",
                "StonkFun → vai p/ Raydium, não PumpSwap", None, 0, False),
               ("MEME/SOL", f"{GK}/pumpswap/pools?sort=h24_volume_usd_desc&include=base_token,quote_token", 3, "memesol",
                "MEME/SOL c/ filtro completo: mercado ≥ US$1 mi + DLMM na Meteora", "So11111111111111111111111111111111111111112", MEMESOL_MERCADO, True)):
    try: fonte_gecko(*args_f)
    except Exception as e: print(f"{args_f[0]}: leitura falhou ({e}) — segue sem", file=sys.stderr)

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
