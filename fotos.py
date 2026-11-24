# FOTOS DOS DEGRAUS — p/ cada meme avisado, a cada 30 min nas primeiras 24h depois do aviso, fotografa TODAS as pools
# DLMM do meme na Meteora (qualquer par: SOL, USDC, USDT, ação, outro meme): quanto dinheiro tem em cada degrau
# em volta do preço, saldo, volume e taxa acumulados. Serve p/ simular faixas/formatos com dados reais de como os
# outros provedores se posicionam ao longo do dia. Só LEITURA. Se falhar, não afeta o alarme.
# Saída: fotos/<mint>.jsonl (vai como backup 'fotos-<run>' no fim de cada plantão). Controle em estado/fotos.json.
import json, os, sys, time, subprocess, urllib.request, ssl
try:
    import certifi; CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError: CTX = ssl.create_default_context()

here = os.path.dirname(os.path.abspath(__file__))
PASTA = os.environ.get("FOTOS_ESTADO", os.path.join(here, "estado"))
EST = os.path.join(PASTA, "estado.json")
CTRL = os.path.join(PASTA, "fotos.json")
OUT = os.environ.get("FOTOS_SAIDA", os.path.join(here, "fotos")); os.makedirs(OUT, exist_ok=True)
INTERVALO = 30 * 60          # 1 foto a cada 30 min
JANELA = 24 * 3600           # durante as 24h seguintes ao 1º aviso
MIN_TVL = float(os.environ.get("FOTOS_MIN_TVL", 300))               # pool com menos de US$300 não vale a foto


def http(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "alerta-fotos"}), timeout=60, context=CTX) as r:
                return json.load(r)
        except Exception: time.sleep(3 + 3 * i)
    return None


if not os.path.exists(EST): sys.exit(0)
est = json.load(open(EST, encoding="utf-8"))
ctrl = json.load(open(CTRL, encoding="utf-8")) if os.path.exists(CTRL) else {}
agora = time.time()
memes = {}
for pl in est["pools"].values():
    if any(not a.endswith("_tarde") for a in pl["avisos"]):
        t = pl.get("t0") or pl["visto"]
        m = memes.setdefault(pl["base"], [pl.get("sym"), t]); m[1] = min(m[1], t)
n_fotos = 0
for mint, (sym, t_grad) in memes.items():
    c = ctrl.setdefault(mint, {"sym": sym, "inicio": t_grad, "ultima": 0})   # janela de 24h conta da graduação
    if agora - c["inicio"] > JANELA or agora - c["ultima"] < INTERVALO - 60: continue
    r = http(f"https://dlmm.datapi.meteora.ag/pools?query={mint}&page_size=50") or {}
    pools = [p for p in r.get("data", []) if mint in (p["token_x"]["address"], p["token_y"]["address"])]
    grandes = [p for p in pools if (p.get("tvl") or 0) >= MIN_TVL]
    bins = {}
    if grandes:
        try:
            res = subprocess.run(["node", os.path.join(here, "fotos_bins.cjs")] + [p["address"] for p in grandes],
                                 capture_output=True, text=True, timeout=240)
            bins = json.loads(res.stdout or "{}")
        except Exception as e: print("fotos: falha ao ler degraus", sym, e, file=sys.stderr)
    linha = {"t": int(agora), "sym": sym, "pools": []}
    for p in pools:
        cm = p.get("cumulative_metrics") or {}
        reg = {"addr": p["address"], "nome": p["name"], "bin": p["pool_config"]["bin_step"], "taxa": p["pool_config"]["base_fee_pct"],
               "taxa_din": p.get("dynamic_fee_pct"), "criada": int(p["created_at"] / 1000), "tvl": p.get("tvl"),
               "preco": p.get("current_price"), "x": p.get("token_x_amount"), "y": p.get("token_y_amount"),
               "px_x": p["token_x"].get("price"), "px_y": p["token_y"].get("price"),
               "vol_acum": cm.get("volume"), "taxas_acum": cm.get("fees")}
        b = bins.get(p["address"])
        if b and "bins" in b:
            reg["ativo"] = b["activeBin"]
            reg["degraus"] = [[d["id"], round(d["x"], 6), round(d["y"], 9)] for d in b["bins"] if d["x"] or d["y"]]
        linha["pools"].append(reg)
    with open(os.path.join(OUT, f"{mint}.jsonl"), "a", encoding="utf-8") as f: f.write(json.dumps(linha) + "\n")
    c["ultima"] = agora; n_fotos += 1
json.dump(ctrl, open(CTRL, "w", encoding="utf-8"))
print(f"fotos: {n_fotos} memes fotografados", file=sys.stderr)
