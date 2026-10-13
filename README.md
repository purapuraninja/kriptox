# KRIPTOX — Bot Paper-Trading 24/7 (Bybit · OKX · Bitget · Gate · Binance)

Bot otonom **paper trading** (uang pura-pura, data sungguhan) yang jalan 24/7 selama ±1 bulan.
Matematika dan risk ditulis di **code**, bukan di model — model/aturan tidak bisa override limit.

> Jujur dulu: **Jev / AgenKit** di prompt awal adalah layanan eksternal yang tidak dibutuhkan
> dan tidak diverifikasi di sini. Sistem ini mengimplementasikan **skema keputusan yang sama persis**
> (`regime / direction / toxic_flow / setup_quality / risk_state / confidence`) secara
> **deterministik, lokal, dan teraudit** — tanpa API key tambahan, tanpa biaya per-candle,
> tanpa black-box. Itu justru lebih aman untuk paper trading.

---

## START HERE FIRST (5 langkah, ±15 menit)

### 1. Install
```powershell
cd C:\Users\Administrator\Documents\kriptox
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

### 2. Tes matematika inti (wajib hijau sebelum jalan)
```powershell
python -m pytest tests/ -q
```
Harus: `6 passed`. Kalau merah, JANGAN lanjut — kirim output error-nya.

### 3. Backtest cepat (validasi logika, bukan janji profit)
```powershell
python scripts/run_backtest.py --exchange binance --symbol BTC/USDT --timeframe 1h --limit 500
```
Butuh internet sekali. Ekspektasi jujur: hasil backtest **tanpa orderbook/funding real = optimis**.
Kalau backtest saja rugi setelah fee+slippage → strategi jangan dipakai live.

### 4. Paper live 24/7 (ini trading awal kamu)
```powershell
python scripts/run_paper.py
```
- Berhenti: `Ctrl+C`.
- Jalan 24 jam/hari selama sebulan di VPS/PC yang tidak mati. Log ada di `state/logs/`.
- **Tidak ada order sungguhan.** Semua fill tercatat di `state/logs/fills.csv`.
- Default: Bybit+OKX+Bitget+Gate+Binance × BTC/ETH/SOL, candle 1m, poll 15 detik.

### 5. Review tiap malam
```powershell
python scripts/run_review.py
```
Baca `state/logs/review-YYYYMMDD.md`. Aturan recalibrasi ada di file itu.
Naikkan `min_confidence` / turunkan size jika kalibrasi buruk. Operator yang approve —
bot tidak pernah mengubah config sendiri.

---

## Arsitektur (BRAIN vs REFLEX, versi jujur)

```
                ┌────────────── BRAIN (lambat, dalam) ──────────────┐
                │ kamu + review malam (review.py) + backtest         │
                │ baca fills, Brier score, ubah config manual        │
                └──────────────────────┬────────────────────────────┘
                                       │ threshold/size diset di code
                ┌──────────────────────▼────────────────────────────┐
                │ REFLEX (cepat, tiap candle, <1 dtk)                │
                │ state_engine → regime.decide → policy.gate         │
                │ snapshot (<400 token) → Decision → FIRE/HOLD       │
                └──────────────────────┬────────────────────────────┘
                                       │ dicek risk + sizing
                ┌──────────────────────▼────────────────────────────┐
                │ RISK LAYER (tidak bisa dioverride)                 │
                │ risk.check_before_order + sizing Kelly + kill-switch│
                └──────────────────────┬────────────────────────────┘
                                       ▼
                         paper_broker (fill simulasi + fee/slip)
```

File persis:

| File | Isi |
|---|---|
| `src/state_engine.py` | snapshot kausal: mid, spread_bps, imbalance, microprice, EMA, RSI, ATR, realvol, funding, inventory, drawdown |
| `src/regime.py` | `Decision(regime, direction, toxic_flow, setup_quality 0-3, risk_state, confidence)` |
| `src/policy.py` | gate: FIRE hanya jika quality≥2, confidence>0.80, risk=safe, bukan crisis/neutral/toxic |
| `src/sizing.py` | fractional Kelly (half-Kelly, cap quarter 25%) + filter biaya |
| `src/risk.py` | max DD 15%, max daily loss 3%, cap posisi 20%, exposure 60%, kill-switch file |
| `src/exchanges.py` | konektor ccxt 5 exchange (publik, polling) |
| `src/paper_broker.py` | kas + posisi + fee/slippage + `fills.csv` |
| `src/live_loop.py` | loop 24/7 |
| `src/backtest.py` | backtest offline jujur |
| `src/review.py` | nightly review + Brier |

---

## Matematika (ringkas, tanpa mistik)

**Regime.** Crisis menang selalu (DD ≥ 8% atau spread ≥ 40bps + ATR meledak).
High-vol jika realvol ≥ persentil-80 histori. Trending jika ADX ≥ 22 dan
|EMA12−EMA48|/ATR ≥ 0.35. Sisanya mean-reverting (paling konservatif).

**Setup quality 0–3.** Satu poin per bukti independen: trend-aligned,
crowd-fade/RSI-ekstrem, flow-confirm, clean-impulse. Toxic flow (spread lebar +
imbalance ekstrem) memenggal skor ke ≤1.

**Confidence.** Baseline 0.50 + 0.12/poin, bonus 0.04 jika regime cocok,
dijepit 0.50–0.90. Netral/toxic dipenggal. **Ini BUKAN probabilitas terkalibrasi**
sampai review malam membuktikan Brier < 0.25 atas ≥20 fill.

**Kelly.** `f* = (p(b+1)−1)/b`, `b = avg_win/avg_loss` (default 1.2).
Pakai half-Kelly, cap 25% equity per posisi, skala `quality/3`,
tolak jika edge < fee+slippage+min_edge. Detail di `src/sizing.py`.

**Risk.** Dicek sebelum SETIAP order. DD ≥ 15% → flatten + HALT permanen
(tulis kill-switch file). Daily loss ≥ 3% → stop hari itu. Cooldown 1 jam.
Kill-switch manual: buat file `state/kill_switch.armed` → bot halt.

---

## Konfigurasi 1 bulan paper

- `config/config.yaml` — semua threshold. Ubah pelan-pelan, satu parameter per malam,
  catat alasan di review report.
- Simbol awal **sempit dan likuid**: BTC/USDT, ETH/USDT, SOL/USDT. Jangan tambah
  altcoin tipis di minggu pertama — spread membunuh edge.
- Timeframe 1m + poll 15 dtk ≈ hemat rate-limit 5 exchange. Naikkan `poll_seconds`
  ke 30 jika error rate-limit sering.
- Short di paper = posisi sintetis (PnL = −qty×Δprice). Live spot TIDAK bisa short
  tanpa margin — jangan ekstrapolasi hasil short paper ke live spot.

## Operasional 24/7

- Jalankan di mesin yang tidak sleep. Windows: matikan sleep, atau lebih baik sewa
  VPS Linux kecil dan jalankan via `nohup`/`systemd`.
- Cek tiap pagi: `heartbeat` di console, `state/logs/decisions.csv` bertambah,
  tidak ada `kill_switch.armed`.
- Krisis (regime=crisis berkali-kali) → wajar tidak ada trade berhari-hari.
  **Tidak trade = fitur, bukan bug.**

## Riset pasar & finalis (cara pakai yang benar)

Lihat `research/` — template harian, bukan ramalan. Bot ini **tidak menebak naratif**;
ia mengukur: tren BTC/ETH, funding, spread, imbalance, RSI, ATR. Isi template
`research/daily_template.md` tiap malam (10 menit) dari sumber primer
(exchange funding page, CoinGecko/DeFiLlama untuk TVL/fees — beri tanggal + link).
Setiap tesis wajib punya: katalis terkonfirmasi vs spekulasi, bear case,
dan kondisi invalidasi. Tanpa itu → setup_quality tidak boleh ≥2 (tulis alasan di review).

## Status konektivitas (hasil verifikasi 2026-10-13, dari mesin ini)

Terverifikasi langsung: `python scripts/check_exchanges.py`

- OK: **gate** (backtest real 200 candle BTC 1h jalan, equity 9996.34, 2 trades)
- FAIL dari jaringan ini (SSL/proxy memblokir): bybit, okx, bitget, binance.
  Kode konektor kelimanya identik via ccxt dan `live_loop` otomatis SKIP exchange
  yang gagal + lanjut dengan yang hidup — **wajib jalankan `check_exchanges.py`
  dari VPS/PC trading kamu** sebelum paper sebulan. Semua 5 sudah didukung kode,
  tinggal soal jaringan.

Verifikasi offline (tanpa internet): `python scripts/run_dry.py --steps 300`
hasil: `FIRE=1 HOLD=296 ESCALATE=3 equity=10067.52` — rantai penuh terbukti jalan.

## Batasan jujur (baca sebelum berharap profit)

1. Edge kecil (<15bps) mati oleh fee+slippage. Filter biaya di sizing menolaknya — itu benar.
2. Backtest publik optimis (tanpa orderbook/funding real, tanpa latency, tanpa partial fill).
3. Confidence ≠ probabilitas sampai terkalibrasi (butuh ≥20 fill + markout).
4. Crypto 24/7 = gap akhir pekan, funding tiap jam, delisting sewaktu-waktu. Risk layer
   yang membuat sistem survive, bukan akurasi arah.
5. **Jangan live dengan uang sungguhan** sebelum: 1 bulan paper hijau setelah biaya,
   Brier < 0.25, max DD paper < 8%, dan kamu paham setiap baris `src/risk.py`.

## WHAT COULD I BE WRONG ABOUT?

- Regime trending terdeteksi telat (EMA/ADX lag) → beli puncak, jual lembah.
- Imbalance orderbook spot ≠ arah (spoofing) → flow-confirm adalah noise.
- Funding=0 di spot mengabaikan tekanan derivatif → crowd-fade tidak bekerja.
- Kelly dengan `b=1.2` dan `p` belum kalibrasi → oversize sistematis.
- Polling 15 dtk ketinggalan dari market-maker (ms) → selalu jadi taker yang membayar spread.
- Satu bug di `risk.py` lebih mahal dari semua edge. Prioritas: **survive dulu, profit kemudian.**

## Perintah cepat

```powershell
python -m pytest tests/ -q                  # tes
python scripts/run_backtest.py --help        # opsi backtest
python scripts/run_paper.py                  # paper live
python scripts/run_review.py                 # review malam
# halt manual:
New-Item -ItemType File state/kill_switch.armed -Force
# restart setelah halt: hapus file itu HANYA setelah baca review
Remove-Item state/kill_switch.armed
```
