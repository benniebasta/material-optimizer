import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
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
    OVERLAP = st.sidebar.number_input("Tile Overlap (cm)", value=1.0)

    # ===============================
    # AUTO ROTATE TOGGLE
    # ===============================
    AUTO_ROTATE = st.sidebar.toggle("🔄 Auto Rotate", value=False)
    if AUTO_ROTATE:
        st.sidebar.caption("ON → tries rotating panels 90° to use the least material.")
    else:
        st.sidebar.caption("OFF → panels keep their given orientation.")

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

    def _roll_best(free, opts):
        """Column-first slot: leftmost length, then topmost across-width, then snug."""
        best = None
        for fx, fy, fw, fh in free:
            for pl, pw in opts:          # pl = along-length, pw = across-width
                if pl <= fw + 1e-9 and pw <= fh + 1e-9:
                    score = (round(fx, 3), round(fy, 3), round(fw - pl, 3))
                    if best is None or score < best[0]:
                        best = (score, fx, fy, pl, pw)
        return best

    def optimize_columns(jobs):
        # tile oversize panels across the width → flat list of (pid, across, along)
        rects = []
        for pid, w, h, q in jobs:
            tile_w, n = tile_width_only(w, ROLL_WIDTH)
            if tile_w is None:
                return None, None
            for _ in range(q):
                for _ in range(n):
                    rects.append((pid, tile_w, h))
        if not rects:
            return None, None
        # biggest first lays the columns; small pieces fill the leftover
        order = sorted(rects, key=lambda r: (max(r[1], r[2]), r[1] * r[2]), reverse=True)
        free = [(0.0, 0.0, 10_000_000.0, ROLL_WIDTH)]   # (Lx=length, Wy=width, Lw, Wh)
        placed = []
        total = 0.0
        for pid, across, along in order:
            opts = [(along, across)]                      # normal: length=along, width=across
            if AUTO_ROTATE and along <= ROLL_WIDTH + 1e-9 and abs(along - across) > 1e-9:
                opts.append((across, along))              # rotated 90°
            b = _roll_best(free, opts)
            if b is None:
                return None, None
            _, fx, fy, pl, pw = b
            total = max(total, fx + pl)
            placed.append((pid, fy, fx, pw, pl))          # (pid, x=across, y=along, w=across, h=along)
            free = _mr_split(free, fx, fy, pl, pw)
        return placed, total

    # =========================================
    # RUN
    # =========================================
    if st.button("Run RIP Optimizer"):
        if not jobs:
            st.error("❌ Add at least one panel with width, height and quantity.")
            st.stop()

        best, total = optimize_columns(jobs)
        if not best:
            st.error("❌ Some panels cannot fit the roll width, even tiled.")
            st.stop()

        mode = "Auto Rotate ON" if AUTO_ROTATE else "Auto Rotate OFF"
        st.success(f"✅ RIP-Optimized Fabric Length = {total/100:.2f} meters  ({mode})")

        # ----- Summary metrics (mirrors ERP Material Optimizer → Roll Optimizer) -----
        used_area  = sum(w * h for _, _, _, w, h in best)   # cm²
        total_area = ROLL_WIDTH * total                     # cm²
        waste_area = total_area - used_area
        util = (used_area / total_area * 100) if total_area else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("ความยาวที่ใช้", f"{total / 100:.2f} ม.")
        c2.metric("การใช้วัสดุ", f"{util:.1f}%")
        c3.metric("พื้นที่เสีย", f"{waste_area / 10_000:.3f} ตร.ม.")
        c4.metric("ชิ้นที่วาง", f"{len(best)}")

        df = pd.DataFrame([(p, w, h) for p, _, _, w, h in best],
                          columns=["Panel", "Tile Width", "Tile Height"])
        st.dataframe(df, use_container_width=True)

        # ===== Visualization =====
        fig, ax = plt.subplots(figsize=(14, 8))
        colors = {}

        for pid, x, y, w, h in best:
            if pid not in colors:
                colors[pid] = (random.random(), random.random(), random.random())
            ax.add_patch(plt.Rectangle((y, x), h, w, facecolor=colors[pid], edgecolor="black"))
            ax.text(
                y + h / 2,
                x + w / 2,
                f"{pid}\n{w:.0f}×{h:.0f}",
                ha="center",
                va="center",
                fontsize=8,
                weight="bold"
            )

        ax.set_xlim(0, total)
        ax.set_ylim(0, ROLL_WIDTH)
        ax.set_xlabel("Fabric Length (cm)")
        ax.set_ylabel("Roll Width (cm)")
        ax.set_title("RIP-Grade Guillotine Nesting")

        st.pyplot(fig)

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
