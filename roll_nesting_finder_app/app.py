import streamlit as st
import pandas as pd
import matplotlib
matplotlib.use("Agg")  # headless backend — Streamlit reruns scripts in worker
                       # threads; the default GUI (Tk) backend crashes the app
                       # after a few runs ("main thread is not in main loop").
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import random

# ===============================
# PAGE CONFIG
# ===============================
st.set_page_config(page_title="Roll Optimizer", layout="wide")

# ===============================
# AVAILABLE ROLL WIDTHS
# ===============================
ROLL_WIDTHS = [
    50, 51, 91, 94, 100, 105, 106, 110, 112, 120,
    127, 137, 152, 160, 162, 200, 240, 250,
    257, 260, 310, 320
]

# ===============================
# MAIN NAVIGATION
# ===============================
page = st.sidebar.radio(
    "📂 Navigation",
    ["Roll Optimizer", "RigidBoard Optimizer", "Roll Finder"]
)
st.sidebar.divider()

# ============================================================
# PAGE 1 : MATERIAL WIDTH FINDER
# ============================================================
if page == "Roll Finder":
    st.header("📏 Material Width Optimizer")
    st.caption("Finds the best roll width — using only the widths your material actually comes in.")

    c1, c2 = st.columns(2)
    w = c1.number_input("Artwork Width (cm)", min_value=1.0)
    h = c2.number_input("Artwork Height (cm)", min_value=1.0)

    st.sidebar.header("⚙️ Available Widths")
    st.sidebar.caption("Not every material comes in every width — keep only the ones you actually have.")
    selected = st.sidebar.multiselect(
        "Standard widths (cm)",
        options=ROLL_WIDTHS,
        default=ROLL_WIDTHS,
    )
    custom_txt = st.sidebar.text_input(
        "Add custom widths (cm)",
        placeholder="e.g. 130, 145",
        help="Comma-separated. Use this for widths not in the standard list.",
    )
    custom = []
    for part in custom_txt.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
            if v > 0:
                custom.append(v)
        except ValueError:
            st.sidebar.warning(f"⚠️ Ignored invalid width: “{part}”")

    available = sorted(set(selected) | set(custom))

    if st.button("Find Best Roll Width"):
        if w <= 0 or h <= 0:
            st.error("❌ Enter the artwork width and height.")
            st.stop()
        if not available:
            st.error("❌ Select or enter at least one available roll width.")
            st.stop()

        results = []
        for roll in available:
            real = w * h
            if w <= roll:  # Normal orientation
                results.append((roll, "Normal", h, roll * h - real))
            if h <= roll:  # Rotated 90°
                results.append((roll, "Rotated 90°", w, roll * w - real))
        results.sort(key=lambda x: (x[3], x[0]))

        if not results:
            widths_txt = ", ".join(f"{r:.0f}" for r in available)
            st.error(
                f"❌ This artwork ({w:.0f}×{h:.0f} cm) doesn't fit any of your widths "
                f"({widths_txt} cm). Add a wider roll or tile the artwork."
            )
            st.stop()

        best = results[0]
        st.success(
            f"✅ Best roll width: **{best[0]:.0f} cm**  ·  {best[1]}  ·  "
            f"{best[2]:.1f} cm used length  ·  {best[3]:,.0f} cm² waste"
        )

        if len(results) > 1:
            with st.expander("Compare all your available widths"):
                df = pd.DataFrame(results, columns=[
                    "Roll Width (cm)", "Orientation", "Used Length (cm)", "Waste Area (cm²)"
                ])
                st.dataframe(df, use_container_width=True, hide_index=True)

# ============================================================
# PAGE 2 : RIP NESTING OPTIMIZER
# ============================================================
elif page == "Roll Optimizer":

    st.header("🖨 RIP-Grade Guillotine Optimizer")

    st.sidebar.header("⚙️ Settings")
    ROLL_WIDTH = st.sidebar.number_input("Roll Width (cm)", value=137.0)

    # ===============================
    # TILING (แบ่งภาพต่อแผ่น)
    # A panel wider than the roll used to be cut into strips automatically, and the
    # length came back looking perfectly ordinary. That is only right for สติกเกอร์
    # ต่อแผ่น, whose panels are butted back together on the wall — a 53×204 flag
    # halved onto a 120 roll is a reject. So it is OFF, and an oversize panel is
    # reported as not fitting instead of being quietly divided.
    # ===============================
    TILE = st.sidebar.toggle("✂️ แบ่งภาพต่อแผ่น (Tile oversize panels)", value=False)
    if TILE:
        st.sidebar.caption("ON → panels wider than the roll are split into strips and joined.")
    else:
        st.sidebar.caption("OFF → panels are never divided. Oversize = doesn't fit.")

    OVERLAP = st.sidebar.number_input("Tile Overlap (cm)", value=1.0, disabled=not TILE)

    # ===============================
    # AUTO ROTATE TOGGLE
    # ===============================
    AUTO_ROTATE = st.sidebar.toggle("🔄 Auto Rotate", value=False)
    if AUTO_ROTATE:
        st.sidebar.caption("ON → tries rotating panels 90° to use the least material.")
    else:
        st.sidebar.caption("OFF → panels keep their given orientation.")

    # ===============================
    # LEFTOVER CONSOLIDATION
    # The shortest nest is not always the best one: it fills the last row across the
    # width and leaves the free space in unrelated strips. Gathering the pieces into
    # columns can cost a centimetre and hand back the whole side of the roll as one
    # rectangle — เศษ the shop cuts off and prints on again.
    # ===============================
    CONSOLIDATE = st.sidebar.toggle("🧩 เศษเป็นชิ้นเดียว (Consolidate offcut)", value=True)
    if CONSOLIDATE:
        st.sidebar.caption(
            "ON → may run slightly longer to leave the waste as ONE usable block."
        )
    else:
        st.sidebar.caption("OFF → shortest possible nest, however the waste falls.")

    #: What an offcut is worth against fresh roll, 0–1. Not 1.0: a block has to be
    #: stored, found again and matched to a job small enough to use it — and the run
    #: is charged for every metre it took. Half is what makes the shop's two cases
    #: come out right (see optimize_columns).
    LEFTOVER_VALUE = 0.5
    #: Hard leash. Metres are what the customer pays, whatever the block is worth.
    LENGTH_TOLERANCE = 0.10
    #: Past this many rectangles the extra passes are not worth the wait, and a job
    #: that dense has no big block to find anyway.
    MAX_CONSOLIDATE_PIECES = 80

    st.sidebar.header("Panels")
    panel_count = st.sidebar.number_input("Number of different panels", 1, 50, 5)

    jobs = []
    for i in range(1, panel_count + 1):
        st.sidebar.markdown(f"### Panel {i}")
        w = st.sidebar.number_input(f"W{i} (cm)", 0.0, key=f"w{i}")
        h = st.sidebar.number_input(f"H{i} (cm)", 0.0, key=f"h{i}")
        q = st.sidebar.number_input(f"Qty{i}", min_value=0.0, max_value=None, value=0.0, step=1.0, key=f"q{i}")
        if w > 0 and h > 0 and q > 0:
            jobs.append((i, w, h, int(round(q))))

    # =========================================
    # TILING
    # =========================================
    def tile_width_only(w, roll):
        """Strips a panel is cut into across the roll — one, unless แบ่งภาพ is on.

        With TILE off the panel stays whole: it either fits the roll across (or
        along, once AUTO_ROTATE takes the turn at placement) or it does not fit at
        all, and "does not fit" is the honest answer for a flag, a banner or a
        backdrop. With TILE on this is the original 1..5 strip search.
        """
        if not TILE:
            if w <= roll + 1e-9 or (AUTO_ROTATE and w > roll):
                # Oversize-but-rotatable is decided per piece in _pack; here the
                # panel is simply passed through undivided.
                return w, 1
            return None, None
        for n in [1, 2, 3, 4, 5]:
            if w <= n * roll - (n - 1) * OVERLAP:
                return (w + (n - 1) * OVERLAP) / n, n
        return None, None

    # =========================================
    # COLUMN-FIRST PACKER  (Onyx-style)
    # Fill each length-column across the FULL roll width, biggest pieces first;
    # small pieces drop into the leftover. Deterministic → uniform, stable layout.
    # =========================================
    def _mr_split(free, px, py, pw, ph):
        """MaxRects: split every free rect overlapping the placed slot into sub-rects."""
        res = []
        for fx, fy, fw, fh in free:
            if px >= fx + fw or px + pw <= fx or py >= fy + fh or py + ph <= fy:
                res.append((fx, fy, fw, fh)); continue
            if fx < px:
                res.append((fx, fy, px - fx, fh))
            if fx + fw > px + pw:
                res.append((px + pw, fy, fx + fw - (px + pw), fh))
            if fy < py:
                res.append((fx, fy, fw, py - fy))
            if fy + fh > py + ph:
                res.append((fx, py + ph, fw, fy + fh - (py + ph)))
        pruned = []
        for i, (ax, ay, aw, ah) in enumerate(res):
            if aw <= 1e-9 or ah <= 1e-9:
                continue
            if any(bx <= ax + 1e-9 and by <= ay + 1e-9
                   and bx + bw >= ax + aw - 1e-9 and by + bh >= ay + ah - 1e-9
                   for j, (bx, by, bw, bh) in enumerate(res) if j != i):
                continue
            pruned.append((ax, ay, aw, ah))
        if len(pruned) > 200:
            pruned.sort(key=lambda r: r[2] * r[3], reverse=True)
            pruned = pruned[:200]
        return pruned

    def _roll_best(free, opts, prefer="across"):
        """Where to put the next piece.

        "across" — leftmost length, then topmost across-width, then snug. Fills each
        length-column across the full roll before advancing, so the nest is short.
        "stack"  — width band first, then length: a piece drops UNDER its neighbour
        rather than beside it, gathering the pieces into one corner and the waste
        into one rectangle. Only used with a length cap (uncapped it would pile the
        whole job into a single column).
        """
        best = None
        for fx, fy, fw, fh in free:
            for pl, pw in opts:          # pl = along-length, pw = across-width
                if pl <= fw + 1e-9 and pw <= fh + 1e-9:
                    score = ((round(fx, 3), round(fy, 3), round(fw - pl, 3))
                             if prefer == "across"
                             else (round(fy, 3), round(fx, 3), round(fw - pl, 3)))
                    if best is None or score < best[0]:
                        best = (score, fx, fy, pl, pw)
        return best

    def _tiled_rects(jobs):
        """Flat list of (pid, across, along) — one rect per copy, or per strip when
        แบ่งภาพ is on. Returns None if any panel cannot reach the roll at all."""
        rects = []
        for pid, w, h, q in jobs:
            tile_w, n = tile_width_only(w, ROLL_WIDTH)
            if tile_w is None:
                return None
            for _ in range(q):
                for _ in range(n):
                    rects.append((pid, tile_w, h))
        return rects or None

    def _pack(order, cap=None, prefer="across"):
        """One greedy pass. `cap` bounds the length the nest may use, which is what
        forces a piece into the column beside the last one instead of a new row."""
        free = [(0.0, 0.0, 10_000_000.0 if cap is None else cap, ROLL_WIDTH)]
        placed = []
        total = 0.0
        for pid, across, along in order:
            opts = [(along, across)]                      # normal: length=along, width=across
            if AUTO_ROTATE and along <= ROLL_WIDTH + 1e-9 and abs(along - across) > 1e-9:
                opts.append((across, along))              # rotated 90°
            b = _roll_best(free, opts, prefer)
            if b is None:
                return None, None
            _, fx, fy, pl, pw = b
            total = max(total, fx + pl)
            placed.append((pid, fy, fx, pw, pl))          # (pid, x=across, y=along, w=across, h=along)
            free = _mr_split(free, fx, fy, pl, pw)
        return placed, total

    # =========================================
    # LEFTOVER: the biggest empty rectangle in the nest
    # A block that comes off the roll whole is stock the shop prints on again;
    # the same area shredded into slivers is bin liner. Exact — piece edges are
    # compressed into a grid and the largest-rectangle-in-a-histogram run over it.
    # =========================================
    def largest_free_rect(placed, length):
        if ROLL_WIDTH <= 0 or length <= 0:
            return 0.0, 0.0, 0.0, 0.0
        clamp = lambda v, hi: min(max(v, 0.0), hi)
        xs, ys = {0.0, float(ROLL_WIDTH)}, {0.0, float(length)}
        for _pid, x, y, w, h in placed:
            xs.add(clamp(x, ROLL_WIDTH)); xs.add(clamp(x + w, ROLL_WIDTH))
            ys.add(clamp(y, length)); ys.add(clamp(y + h, length))
        xv, yv = sorted(xs), sorted(ys)
        nx, ny = len(xv) - 1, len(yv) - 1
        if nx < 1 or ny < 1:
            return 0.0, 0.0, 0.0, 0.0

        def slot(vals, v):
            import bisect
            return min(max(bisect.bisect_left(vals, v - 1e-7), 0), len(vals) - 1)

        occ = [bytearray(nx) for _ in range(ny)]
        for _pid, x, y, w, h in placed:
            i0, i1 = slot(xv, x), min(slot(xv, x + w), nx)
            j0, j1 = slot(yv, y), min(slot(yv, y + h), ny)
            for j in range(j0, j1):
                for i in range(i0, i1):
                    occ[j][i] = 1

        heights = [0.0] * nx
        best = (0.0, 0.0, 0.0, 0.0, 0.0)      # (area, x, y, w, h)
        for j in range(ny):
            dy = yv[j + 1] - yv[j]
            for i in range(nx):
                heights[i] = 0.0 if occ[j][i] else heights[i] + dy
            stack = []
            for i in range(nx + 1):
                hgt = heights[i] if i < nx else 0.0
                start = i
                while stack and stack[-1][1] >= hgt:
                    si, sh = stack.pop()
                    wid = xv[i] - xv[si]
                    if wid * sh > best[0]:
                        best = (wid * sh, xv[si], yv[j + 1] - sh, wid, sh)
                    start = si
                stack.append((start, hgt))
        return best[1], best[2], best[3], best[4]

    def _measure(placed, total):
        used = sum(w * h for _pid, _x, _y, w, h in placed)
        waste = max(0.0, ROLL_WIDTH * total - used)
        lx, ly, lw, lh = largest_free_rect(placed, total)
        leftover = min(lw * lh, waste)
        return {
            "placed": placed, "total": total, "used": used, "waste": waste,
            "leftover": leftover, "lx": lx, "ly": ly, "lw": lw, "lh": lh,
            "scrap": waste - leftover,
        }

    def _stack_caps(alongs, floor_cm, ceil_cm, limit=6):
        """Length caps worth trying — the sums of piece lengths between the shortest
        nest and the ceiling. A column of stacked pieces ends exactly on one of them,
        and capping there is what puts the next piece under its neighbour."""
        vals = sorted({round(v, 4) for v in alongs if v > 0})
        if not vals:
            return []
        reach, frontier = {0.0}, [0.0]
        while frontier and len(reach) < 2000:
            nxt = []
            for s in frontier:
                for v in vals:
                    t = round(s + v, 4)
                    if t <= ceil_cm + 1e-9 and t not in reach:
                        reach.add(t); nxt.append(t)
            frontier = nxt
        caps = sorted(t for t in reach if floor_cm - 1e-9 <= t <= ceil_cm + 1e-9)
        base = round(floor_cm, 4)
        if not caps or abs(caps[0] - base) > 1e-9:
            caps.insert(0, base)
        return caps[:limit]

    def optimize_columns(jobs):
        """Nest the job, then try to leave the waste in ONE piece.

        The shortest nest is packed first and is always a candidate. Then the same
        pieces are re-packed against a few length caps, which turns rows into
        columns, and the cheapest layout wins — cheapest meaning the roll it takes
        LESS what the offcut is worth back (LEFTOVER_VALUE), never more than
        LENGTH_TOLERANCE longer than the shortest nest.

        Why not just "least waste": lengthening the roll always grows the block, so
        minimising scrap alone would buy 20 cm of roll to save 12 cm² of scrap. And
        why not length alone: 4×(18×9) + 4×(18×8) on a 127 roll is 16 cm with the
        eights strung out beside the nines and the free space in three strips, or
        17 cm with the eights UNDER the nines and the whole 55 × 17 right-hand side
        coming off whole. The second is the one to print.
        """
        rects = _tiled_rects(jobs)
        if rects is None:
            return None, None
        # biggest first lays the columns; small pieces fill the leftover
        order = sorted(rects, key=lambda r: (max(r[1], r[2]), r[1] * r[2]), reverse=True)
        placed, total = _pack(order)
        if placed is None:
            return None, None

        cands = [_measure(placed, total)]
        if CONSOLIDATE and len(rects) <= MAX_CONSOLIDATE_PIECES:
            # A turn swaps which side runs along the roll, so both sides can end a column.
            alongs = [r[2] for r in rects] + ([r[1] for r in rects] if AUTO_ROTATE else [])
            for cap in _stack_caps(alongs, total, total * (1.0 + LENGTH_TOLERANCE)):
                for prefer in ("stack", "across"):
                    p, t = _pack(order, cap=cap, prefer=prefer)
                    if p is not None:
                        cands.append(_measure(p, t))

        ceiling = min(c["total"] for c in cands) * (1.0 + LENGTH_TOLERANCE) + 1e-9
        allowed = [c for c in cands if c["total"] <= ceiling]
        # Ties keep the earliest candidate, and the shortest nest is offered first,
        # so nothing moves unless consolidating genuinely wins.
        best = min(allowed, key=lambda c: (
            round(ROLL_WIDTH * c["total"] - LEFTOVER_VALUE * c["leftover"], 3), c["total"]))
        return best, best["total"]

    # =========================================
    # RUN
    # =========================================
    # The nest is kept in session state rather than drawn straight from the button:
    # moving the ช่วงความยาว slider reruns the script with the button False, and a
    # picture that lives inside `if st.button(...)` disappears the moment you
    # scroll it. The roll width is stored with it so the drawing always matches the
    # nest that was actually solved, not whatever the sidebar says now.
    if st.button("Run RIP Optimizer"):
        if not jobs:
            st.error("❌ Add at least one panel with width, height and quantity.")
            st.stop()

        layout, total = optimize_columns(jobs)
        if not layout:
            st.session_state.pop("roll_nest", None)
            st.error(
                "❌ Some panels cannot fit the roll width, even tiled."
                if TILE else
                "❌ A panel is wider than the roll. Use a wider roll — or turn on "
                "**✂️ แบ่งภาพต่อแผ่น** if this artwork really may be split into strips "
                "(tiling sticker only)."
            )
            st.stop()

        st.session_state["roll_nest"] = {
            "layout": layout,
            "total": total,
            "roll_width": ROLL_WIDTH,
            "rotate": AUTO_ROTATE,
        }

    nest = st.session_state.get("roll_nest")
    if nest:
        layout, total = nest["layout"], nest["total"]
        roll_w = nest["roll_width"]
        best = layout["placed"]

        mode = "Auto Rotate ON" if nest["rotate"] else "Auto Rotate OFF"
        st.success(f"✅ RIP-Optimized Fabric Length = {total/100:.2f} meters  ({mode})")

        # ----- Summary metrics (mirrors ERP Material Optimizer → Roll Optimizer) -----
        # พื้นที่เสีย is split in two, because that is the choice the nest just made:
        # the block that comes off whole and can be printed again, and the rest.
        total_area = roll_w * total                         # cm²
        util = (layout["used"] / total_area * 100) if total_area else 0
        has_block = layout["lw"] >= 5 and layout["lh"] >= 5
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("ความยาวที่ใช้", f"{total / 100:.2f} ม.")
        c2.metric("การใช้วัสดุ", f"{util:.1f}%")
        c3.metric("เศษใช้ต่อได้",
                  f"{layout['lw']:.0f}×{layout['lh']:.0f} ซม." if has_block else "—")
        c4.metric("ทิ้งจริง", f"{layout['scrap'] / 10_000:.3f} ตร.ม.")
        c5.metric("ชิ้นที่วาง", f"{len(best)}")

        df = pd.DataFrame([(p, w, h) for p, _, _, w, h in best],
                          columns=["Panel", "Tile Width", "Tile Height"])
        st.dataframe(df, use_container_width=True)

        # ===== Visualization =====
        # หน้ากว้างม้วน across, ความยาว down the page — the way the roll comes off
        # the press. Drawn length-first a 743 m run on a 260 cm roll is a hairline
        # 0.3 mm tall on screen: the picture says nothing, whatever the nest did.
        # Width-first the scale is set by the roll, which is fixed, so a piece is
        # always the same size on screen and you read the run by moving down it.
        FIG_W_IN = 7.0                        # the roll fills this much of the page
        MAX_FIG_H_IN = 26.0                   # taller than this and the raster blows up
        in_per_cm = FIG_W_IN / roll_w
        win_cm = MAX_FIG_H_IN / in_per_cm     # length one figure can hold at scale

        # A roll longer than one figure is paged rather than squashed: same scale
        # every view, and the slider is how you get to the far end of the run.
        start = 0.0
        if total > win_cm:
            st.caption(
                f"ม้วนยาว {total / 100:.2f} ม. — แสดงทีละ {win_cm / 100:.1f} ม. "
                "ที่มาตราส่วนเดียวกัน เลื่อนเพื่อดูช่วงถัดไป"
            )
            last_m = max(round((total - win_cm) / 100, 1), 0.1)
            start = st.slider(
                "ช่วงความยาวที่แสดง (ม.)",
                0.0, last_m, 0.0,
                step=max(round(win_cm / 200, 1), 0.1),   # ~half a screen per notch
            ) * 100
        view = min(win_cm, total - start)

        fig, ax = plt.subplots(figsize=(FIG_W_IN, max(view * in_per_cm, 1.5)))
        # One colour per panel id, taken by position — random colours meant a panel
        # changed colour on every rerun, so the legend you built in your head while
        # scrolling the roll was wrong by the next slider move.
        order = list(dict.fromkeys(p for p, *_ in best))
        palette = matplotlib.colormaps["tab20"].colors
        colors = {pid: palette[i % len(palette)] for i, pid in enumerate(order)}

        for pid, x, y, w, h in best:
            ax.add_patch(plt.Rectangle((x, y), w, h, facecolor=colors[pid], edgecolor="black"))
            ax.text(
                x + w / 2,
                y + h / 2,
                f"{pid}\n{w:.0f}×{h:.0f}",
                ha="center",
                va="center",
                fontsize=8,
                weight="bold",
                # Text is not clipped to the axes by default, and Streamlit saves
                # with bbox_inches="tight": the labels of the 700 m that are NOT in
                # this window would drag the raster out to 367 million pixels.
                clip_on=True,
            )

        # The offcut, outlined. Knowing the run leaves 0.09 m² spare is not the same
        # as seeing it is one block against the far edge — that is what tells the
        # graphic team they can still drop another AW into this run.
        if has_block:
            ax.add_patch(plt.Rectangle(
                (layout["lx"], layout["ly"]), layout["lw"], layout["lh"],
                facecolor="none", edgecolor="crimson", linewidth=2, linestyle="--"))
            ax.text(
                layout["lx"] + layout["lw"] / 2,
                layout["ly"] + layout["lh"] / 2,
                f"OFFCUT\n{layout['lw']:.0f}×{layout['lh']:.0f}",
                ha="center", va="center", fontsize=9, weight="bold", color="crimson",
                clip_on=True)

        ax.set_xlim(0, roll_w)
        ax.set_ylim(start, start + view)
        ax.set_aspect("equal")   # a piece keeps its shape; nothing is stretched to fit
        ax.invert_yaxis()        # length grows downward, off the press
        ax.set_xlabel("Roll Width (cm)")
        # Pieces are cut in cm, but a run is measured off the roll in metres — so the
        # ruler down the side reads in metres even though the geometry is cm.
        ax.set_ylabel("Fabric Length (m)")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _pos: f"{v / 100:g}"))
        # Matplotlib's default font has no Thai glyphs — anything but ASCII in the
        # figure comes out as tofu boxes. Thai belongs in the Streamlit text around it.
        ax.set_title(
            "RIP-Grade Guillotine Nesting"
            if total <= win_cm else
            f"RIP-Grade Guillotine Nesting — {start / 100:.1f}-{(start + view) / 100:.1f} m "
            f"of {total / 100:.2f} m"
        )

        st.pyplot(fig)
        plt.close(fig)  # free the figure — they otherwise accumulate across reruns

# ============================================================
# PAGE 3 : RIGID BOARD OPTIMIZER
# ============================================================
else:

    st.header("🪟 Rigid Board Nesting Optimizer")
    st.caption("PP board • Foam board • PlastWood • Acrylic • Cardboard • Dibond • Correx …")

    # ---------------------------------------------------------
    # BOARD / SHEET SETTINGS
    # ---------------------------------------------------------
    st.sidebar.header("⚙️ Board Settings")
    BOARD_W = st.sidebar.number_input("Board Width (cm)", min_value=1.0, value=240.0)
    BOARD_H = st.sidebar.number_input("Board Height (cm)", min_value=1.0, value=120.0)
    st.sidebar.caption("Default = 240 × 120 cm sheet.")

    GAP = st.sidebar.number_input("Cut Gap between pieces (cm)", min_value=0.0, value=0.3, step=0.1)

    R_AUTO_ROTATE = st.sidebar.toggle("🔄 Auto Rotate", value=True)
    if R_AUTO_ROTATE:
        st.sidebar.caption("ON → pieces may rotate 90° to fit more per board.")
    else:
        st.sidebar.caption("OFF → pieces keep their given orientation.")

    # A virtual gap-inflated board so the cut gap also sits between adjacent
    # pieces without wrongly rejecting a piece that exactly matches the board.
    USABLE_W = BOARD_W + GAP
    USABLE_H = BOARD_H + GAP
    BOARD_AREA = BOARD_W * BOARD_H

    # ---------------------------------------------------------
    # GRAPHICS INPUT
    # ---------------------------------------------------------
    st.sidebar.header("Graphics")
    g_count = st.sidebar.number_input("Number of different graphics", 1, 50, 3)

    r_jobs = []
    for i in range(1, g_count + 1):
        st.sidebar.markdown(f"### Graphic {i}")
        gw = st.sidebar.number_input(f"Width {i} (cm)", 0.0, key=f"rgw{i}")
        gh = st.sidebar.number_input(f"Height {i} (cm)", 0.0, key=f"rgh{i}")
        gq = st.sidebar.number_input(f"Qty {i}", min_value=0.0, value=0.0, step=1.0, key=f"rgq{i}")
        if gw > 0 and gh > 0 and gq > 0:
            r_jobs.append((i, gw, gh, int(round(gq))))

    # ---------------------------------------------------------
    # HELPERS
    # ---------------------------------------------------------
    def orientations_for(w, h):
        outs = [(w, h)]
        if R_AUTO_ROTATE and abs(w - h) > 1e-9:
            outs.append((h, w))
        return outs

    def fits_board(w, h):
        for ow, oh in orientations_for(w, h):
            if ow <= BOARD_W + 1e-9 and oh <= BOARD_H + 1e-9:
                return True
        return False

    def board_used_area(board):
        return sum(ow * oh for _, _, _, ow, oh in board["placed"])

    # ---------------------------------------------------------
    # MAXRECTS PACKER  (column-first, gap-filling, rotation-aware)
    # Tracks every free rectangle — including enclosed voids — so small / rotated
    # pieces fill the gaps the big ones leave. Placement is column-first (leftmost
    # x, then snug width) so columns fill the full 120 cm height before moving
    # right → the layout also maps onto the 127 cm sticker roll.
    # ---------------------------------------------------------
    _MAX_FREE = 200  # cap free-rect list to keep big jobs fast

    def _mr_split(free, px, py, pw, ph):
        """Split every free rect overlapping the placed slot into maximal sub-rects."""
        res = []
        for fx, fy, fw, fh in free:
            if px >= fx + fw or px + pw <= fx or py >= fy + fh or py + ph <= fy:
                res.append((fx, fy, fw, fh))
                continue
            if fx < px:
                res.append((fx, fy, px - fx, fh))
            if fx + fw > px + pw:
                res.append((px + pw, fy, fx + fw - (px + pw), fh))
            if fy < py:
                res.append((fx, fy, fw, py - fy))
            if fy + fh > py + ph:
                res.append((fx, py + ph, fw, fy + fh - (py + ph)))
        pruned = []
        for i, (ax, ay, aw, ah) in enumerate(res):
            if aw <= 1e-9 or ah <= 1e-9:
                continue
            if any(bx <= ax + 1e-9 and by <= ay + 1e-9
                   and bx + bw >= ax + aw - 1e-9 and by + bh >= ay + ah - 1e-9
                   for j, (bx, by, bw, bh) in enumerate(res) if j != i):
                continue
            pruned.append((ax, ay, aw, ah))
        if len(pruned) > _MAX_FREE:
            pruned.sort(key=lambda r: r[2] * r[3], reverse=True)
            pruned = pruned[:_MAX_FREE]
        return pruned

    def _mr_best(free, w, h):
        """Best slot in one board's free rects. Column-first: leftmost x, then the
        snuggest width fit (fills narrow gaps), then topmost. Tries both rotations."""
        best = None
        for fx, fy, fw, fh in free:
            for ow, oh in orientations_for(w, h):
                sw, sh = ow + GAP, oh + GAP
                if sw <= fw + 1e-9 and sh <= fh + 1e-9:
                    score = (round(fx, 3), round(fw - sw, 3), round(fy, 3))
                    if best is None or score < best[0]:
                        best = (score, fx, fy, ow, oh, sw, sh)
        return best

    def pack_boards(pieces):
        # Largest pieces first set the layout; smaller / rotated ones fill the gaps.
        order = sorted(pieces, key=lambda p: (max(p[1], p[2]), p[1] * p[2]), reverse=True)
        boards = []

        for pid, w, h in order:
            placed_ok = False
            # Fill existing boards (board 1 fully) before opening a new one.
            for b in boards:
                r = _mr_best(b["free"], w, h)
                if r is not None:
                    _, fx, fy, ow, oh, sw, sh = r
                    b["placed"].append((pid, fx, fy, ow, oh))
                    b["free"] = _mr_split(b["free"], fx, fy, sw, sh)
                    placed_ok = True
                    break
            if placed_ok:
                continue
            b = {"free": [(0.0, 0.0, USABLE_W, USABLE_H)], "placed": []}
            boards.append(b)
            r = _mr_best(b["free"], w, h)
            if r is not None:
                _, fx, fy, ow, oh, sw, sh = r
                b["placed"].append((pid, fx, fy, ow, oh))
                b["free"] = _mr_split(b["free"], fx, fy, sw, sh)

        return [b for b in boards if b["placed"]]

    def additional_capacity(boards, w, h):
        """How many more w×h pieces fit into the existing boards' empty space
        (no new board). Used to suggest topping up the leftover."""
        total = 0
        for b in boards:
            free = list(b["free"])
            while True:
                r = _mr_best(free, w, h)
                if r is None:
                    break
                _, fx, fy, ow, oh, sw, sh = r
                free = _mr_split(free, fx, fy, sw, sh)
                total += 1
        return total

    # ---------------------------------------------------------
    # RUN
    # ---------------------------------------------------------
    if st.button("Run Rigid Board Optimizer"):
        if not r_jobs:
            st.error("❌ Add at least one graphic with width, height and quantity.")
            st.stop()

        pieces = []
        oversized = []
        for pid, w, h, q in r_jobs:
            if not fits_board(w, h):
                oversized.append((pid, w, h))
                continue
            for _ in range(q):
                pieces.append((pid, w, h))

        if oversized:
            txt = ", ".join(f"#{pid} ({w:.0f}×{h:.0f})" for pid, w, h in oversized)
            st.warning(
                f"⚠️ These graphics are bigger than the {BOARD_W:.0f}×{BOARD_H:.0f} cm board "
                f"and were skipped: {txt}. Split them into tiles first, or tell me to add "
                f"board-tiling for oversized graphics."
            )

        if not pieces:
            st.error("❌ No graphics fit the board.")
            st.stop()

        boards = pack_boards(pieces)

        # ----- Summary -----
        n_boards = len(boards)
        total_pieces = sum(len(b["placed"]) for b in boards)
        used_area = sum(board_used_area(b) for b in boards)
        total_area = n_boards * BOARD_AREA
        util = (used_area / total_area * 100) if total_area else 0

        st.success(
            f"✅ Needs {n_boards} board(s) of {BOARD_W:.0f}×{BOARD_H:.0f} cm  •  "
            f"{total_pieces} pieces placed  •  {util:.1f}% material used"
        )

        # ----- Summary metrics (mirrors ERP Material Optimizer → Rigid Board) -----
        free_area = total_area - used_area
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ต้องใช้แผ่น", n_boards)
        c2.metric("ชิ้นที่วาง", total_pieces)
        c3.metric("การใช้วัสดุเฉลี่ย", f"{util:.1f}%")
        c4.metric("พื้นที่เสีย", f"{free_area / 10_000:.3f} ตร.ม.")

        # ----- Per-graphic count check -----
        counts = {}
        for b in boards:
            for pid, _, _, _, _ in b["placed"]:
                counts[pid] = counts.get(pid, 0) + 1
        summary_df = pd.DataFrame(
            [(pid, w, h, q, counts.get(pid, 0)) for pid, w, h, q in r_jobs],
            columns=["Graphic", "Width", "Height", "Qty Requested", "Qty Placed"]
        )
        st.dataframe(summary_df, use_container_width=True)

        # ----- Fill-the-leftover suggestion -----
        # How many more of each graphic would fit into the empty space that's
        # already paid for (no extra board), so the wasted area becomes free output.
        if free_area > BOARD_AREA * 0.02:  # only worth suggesting if there's real space
            extra = [
                (pid, w, h, additional_capacity(boards, w, h))
                for pid, w, h, _ in r_jobs
            ]
            extra = [e for e in extra if e[3] > 0]
            if extra:
                st.markdown("#### 💡 Fill the leftover — free extra pieces (no new board)")
                st.caption(
                    f"{free_area:,.0f} cm² of empty space is already on these boards. "
                    "You could add up to:"
                )
                fill_df = pd.DataFrame(
                    [(f"Graphic {pid}", f"{w:.0f}×{h:.0f}", f"+{n}") for pid, w, h, n in extra],
                    columns=["Graphic", "Size (cm)", "Extra pieces that fit free"],
                )
                st.dataframe(fill_df, use_container_width=True, hide_index=True)

        # ----- Visualization (2 boards per row) -----
        MAX_SHOW = 24
        colors = {}
        show = boards[:MAX_SHOW]
        for bidx, board in enumerate(show):
            with st.container():
                fig, ax = plt.subplots(figsize=(14, 14 * BOARD_H / BOARD_W))
                used = board_used_area(board)
                ax.set_title(f"Board {bidx + 1} — {used / BOARD_AREA * 100:.1f}% used", fontsize=10)

                for pid, x, y, w, h in board["placed"]:
                    if pid not in colors:
                        colors[pid] = (
                            random.random() * 0.7 + 0.15,
                            random.random() * 0.7 + 0.15,
                            random.random() * 0.7 + 0.15,
                        )
                    ax.add_patch(plt.Rectangle((x, y), w, h,
                                               facecolor=colors[pid],
                                               edgecolor="black", linewidth=1))
                    ax.text(x + w / 2, y + h / 2, f"{pid}\n{w:.0f}×{h:.0f}",
                            ha="center", va="center", fontsize=7, weight="bold")

                ax.set_xlim(0, BOARD_W)
                ax.set_ylim(0, BOARD_H)
                ax.set_aspect("equal")
                ax.invert_yaxis()  # origin top-left, like a real sheet
                ax.set_xlabel("Width (cm)")
                ax.set_ylabel("Height (cm)")
                st.pyplot(fig)
                plt.close(fig)

        if n_boards > MAX_SHOW:
            st.info(f"… {n_boards - MAX_SHOW} more board(s) calculated but not drawn.")
