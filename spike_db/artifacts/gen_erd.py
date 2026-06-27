"""Generate the spike ERD as an Excalidraw diagram. Run with any python3."""
import sys
sys.path.insert(0, "/Users/malan/.claude/skills/draw/lib")
from excalidraw import make_box, make_text, make_arrow, bind_arrow, write_diagram, seed, idx  # noqa: E402

DATA_FILL, DATA_STROKE = "#a5d8ff", "#1971c2"      # tables (data/storage)
VIEW_FILL, VIEW_STROKE = "#dee2e6", "#495057"      # the read-only view
TITLE = "#1e1e1e"

elements = []


def table(name, x, y, title, cols, fill=DATA_FILL, stroke=DATA_STROKE):
    """A table box with a title line + left-aligned column list bound inside."""
    lines = [title] + ["─" * (len(title) + 2)] + cols
    longest = max(len(l) for l in lines)
    w = int(longest * 9.6 + 34)
    h = int(len(lines) * 16 * 1.55 + 22)
    box_id = f"tbl-{name}"
    txt_id = f"txt-{name}"
    box = make_box(box_id, x, y, w, h, fill, stroke,
                   bound_elements=[{"id": txt_id, "type": "text"}])
    label = "\n".join(lines)
    txt = make_text(txt_id, x + 16, y + 12, w - 30, h - 22, label,
                    font_size=16, container_id=box_id, color="#0b3a5e", align="left")
    elements.extend([box, txt])
    return box_id, (x, y, w, h)


# ── tables ───────────────────────────────────────────────────────────────────
prop_id, prop = table(
    "properties", 90, 150, "properties",
    ["🔑 id  serial",
     "✦ lodge_slug      text  ┐ UNIQUE",
     "✦ property_slug   text  ┘",
     "  name            text",
     "  currency        text",
     "  benchmark_year  int",
     "  benchmark_applicable bool",
     "  inclusion       text",
     "  pricing_script_path text",
     "  dossier_path    text"])

eval_id, ev = table(
    "evaluations", 90, 560, "evaluations",
    ["🔑↗ property_id → properties",
     "  adr_json    jsonb   (the blob)",
     "  fx_date     date",
     "  evaluated_at timestamptz"])

cat_id, cat = table(
    "categories", 860, 150, "categories",
    ["🔑 slug   text",
     "  label  text",
     "  ages   int[]"])

mem_id, mem = table(
    "category_membership", 500, 470, "category_membership",
    ["🔑↗ category_slug → categories",
     "🔑↗ property_id   → properties",
     "  rank            int",
     "  low_usd         numeric",
     "  high_usd        numeric",
     "  feasible_months int",
     "  included        bool"])

view_id, vw = table(
    "category_listing", 500, 820, "category_listing  (VIEW)",
    ["reads: membership ⋈ categories ⋈ properties",
     "→ category · property · lodge · adr range",
     "the human-readable surface"],
    fill=VIEW_FILL, stroke=VIEW_STROKE)


def edge(a_id, b_id, points, x, y, color="#1971c2", dashed=False, label=None,
         lx=0, ly=0):
    aid = f"arr-{a_id}-{b_id}"
    arr = make_arrow(aid, x, y, points, start_id=a_id, end_id=b_id, color=color,
                     stroke_width=2)
    if dashed:
        arr["strokeStyle"] = "dashed"
    elements.append(arr)
    bind_arrow(elements, aid, a_id)
    bind_arrow(elements, aid, b_id)
    if label:
        t = make_text(f"lbl-{aid}", lx, ly, len(label) * 7, 18, label,
                      font_size=13, color="#495057", align="left")
        elements.append(t)


# ── FK edges (child → parent) ────────────────────────────────────────────────
# evaluations.property_id → properties (1:1, sits directly below)
edge(eval_id, prop_id, [[0, 0], [0, -90]], ev[0] + 150, ev[1], label="1:1", lx=ev[0] + 165, ly=ev[1] - 60)
# membership.property_id → properties
edge(mem_id, prop_id, [[0, 0], [-180, -160]], mem[0] + 20, mem[1] + 30, label="N:1", lx=330, ly=430)
# membership.category_slug → categories
edge(mem_id, cat_id, [[0, 0], [320, -300]], mem[0] + mem[2], mem[1] + 30, label="N:1", lx=820, ly=430)
# view ← membership / categories / properties (read-only, dashed grey)
edge(view_id, mem_id, [[0, 0], [0, -60]], vw[0] + 150, vw[1], color="#868e96", dashed=True)

# ── title + legend ───────────────────────────────────────────────────────────
elements.append(make_text("title", 90, 70, 760, 30,
                "spoor → DB spike — ERD (later ETL stages)", font_size=26, color=TITLE, align="left"))
elements.append(make_text("sub", 92, 108, 900, 22,
                "evaluate persists → evaluations · categorise writes → category_membership · pricing NOT persisted (recomputed) · FKs ON DELETE CASCADE",
                font_size=14, color="#495057", align="left"))

out = "/Users/malan/Coding (local)/spoor-spike/spike_db/artifacts/erd.excalidraw"
write_diagram(out, elements)
print("wrote", out, "with", len(elements), "elements")
