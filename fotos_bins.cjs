// Lê a liquidez por degrau (bin) em volta do preço atual de pools DLMM. Só leitura, sem carteira.
const { Connection, PublicKey } = require("@solana/web3.js");
const DLMM = require("@meteora-ag/dlmm");
(async () => {
  const conn = new Connection(process.env.RPC || "https://api.mainnet-beta.solana.com", "confirmed");
  const out = {};
  for (const addr of process.argv.slice(2)) {
    try {
      const pool = await DLMM.create(conn, new PublicKey(addr));
      const active = await pool.getActiveBin();
      const { bins } = await pool.getBinsAroundActiveBin(150, 150);
      const dx = pool.tokenX.mint.decimals, dy = pool.tokenY.mint.decimals;
      const px = Number(pool.fromPricePerLamport(Number(active.price)));
      out[addr] = { activeBin: active.binId, price: px, binStep: pool.lbPair.binStep,
        bins: bins.map((b) => ({ id: b.binId, price: Number(pool.fromPricePerLamport(Number(b.price))),
          x: Number(b.xAmount.toString()) / 10 ** dx, y: Number(b.yAmount.toString()) / 10 ** dy })) };
    } catch (e) { out[addr] = { error: String(e).slice(0, 300) }; }
  }
  console.log(JSON.stringify(out));
})();
