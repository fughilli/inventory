// Add an item: photo -> identify (Google reverse search / Claude / lookalikes
// you already own) -> confirm details -> into a bin.

import { api, type Candidate, type IdentifyResult } from "../api";
import { pickPhoto, shrink } from "../camera";
import { pickBin, thumb } from "../components";
import { append, binChip, errorText, h, replace, toast } from "../dom";
import { navigate, type View } from "../router";
import { categories, refreshStatus, state } from "../state";

const SOURCE_LABEL: Record<string, string> = { google: "Google", claude: "Claude" };

export const addView: View = async (root) => {
  let file = state.pendingPhoto;
  state.pendingPhoto = null;
  if (!file) {
    append(root, 
      h("h1", null, "Add an item"),
      h("p", null, "Photograph the item on its own, on a plain surface if you can."),
      h("button", {
        class: "btn primary big",
        onclick: async () => {
          const f = await pickPhoto();
          if (f) {
            state.pendingPhoto = f;
            navigate("/add", true);
          }
        },
      }, "Take a photo"),
      h("button", {
        class: "btn",
        onclick: async () => {
          const f = await pickPhoto({ camera: false });
          if (f) {
            state.pendingPhoto = f;
            navigate("/add", true);
          }
        },
      }, "Choose from library"),
    );
    return;
  }

  const preview = URL.createObjectURL(file);
  const photoIds: number[] = [];
  let binCode: string | null = state.packing;
  let locationPhotoId: number | null = null;
  let source = "manual";
  let sourceUrl = "";

  // ---- form ----
  const name = h("input", { type: "text", required: true, autocomplete: "off", placeholder: "What is it?", "aria-label": "Name" });
  const category = h("select", { "aria-label": "Category" }, h("option", { value: "" }, "Category…"), categories().map((c) => h("option", { value: c }, c)));
  const tags = h("input", { type: "text", placeholder: "camping, spare, 12v", autocomplete: "off" });
  const qty = h("input", { type: "number", min: "1", value: "1", inputmode: "numeric" });
  const desc = h("textarea", { rows: 2, placeholder: "Size, colour, which car it fits…" });
  const brand = h("input", { type: "text", autocomplete: "off" });
  const model = h("input", { type: "text", autocomplete: "off" });
  const locNote = h("input", { type: "text", placeholder: "e.g. pegboard above the bench" });
  const binSlot = h("div", { class: "bin-slot" });
  const locBox = h("div", { class: "stack" });

  const drawBin = () => {
    replace(binSlot, 
      binCode ? binChip(binCode, { href: false, big: true }) : h("span", { class: "muted" }, "Not in a bin"),
      h("button", { type: "button", class: "btn small", onclick: chooseBin }, binCode ? "Change" : "Choose bin"),
    );
    locBox.hidden = !!binCode;
  };
  async function chooseBin() {
    const b = await pickBin("Where does it go?", true);
    if (b !== undefined) {
      binCode = b;
      drawBin();
    }
  }
  const locPhotoBtn = h("button", {
    type: "button",
    class: "btn small",
    onclick: async () => {
      const f = await pickPhoto();
      if (!f) return;
      try {
        locationPhotoId = (await api.uploadPhoto(await shrink(f), "location")).id;
        replace(locPhotoBtn, thumb(locationPhotoId, "spot", "mini-thumb"), " Retake photo of the spot");
      } catch (e) {
        toast(errorText(e), "err");
      }
    },
  }, "Photo of the spot");
  append(locBox, field("Where is it kept?", locNote), locPhotoBtn);
  drawBin();

  const apply = (c: Candidate) => {
    name.value = c.name;
    if (c.category && categories().includes(c.category)) category.value = c.category;
    if (c.tags.length) tags.value = c.tags.join(", ");
    if (c.description) desc.value = c.description;
    brand.value = c.brand || brand.value;
    model.value = c.model || model.value;
    source = c.source;
    sourceUrl = c.url;
  };

  const suggestions = h("section", { class: "suggest", "aria-live": "polite" },
    h("p", { class: "loading" }, h("span", { class: "spin", "aria-hidden": "true" }), "Identifying…"));

  const save = h("button", { class: "btn primary big", type: "submit", disabled: true }, "Save");
  const form = h(
    "form",
    {
      class: "item-form",
      onsubmit: async (e: Event) => {
        e.preventDefault();
        if (!name.value.trim()) return name.focus();
        save.disabled = true;
        try {
          const it = await api.createItem({
            name: name.value.trim(),
            category: category.value,
            tags: tags.value.split(","),
            quantity: Number(qty.value) || 1,
            description: desc.value,
            brand: brand.value,
            model: model.value,
            bin_code: binCode,
            photo_ids: photoIds,
            location_note: binCode ? "" : locNote.value,
            location_photo_id: binCode ? null : locationPhotoId,
            source,
            source_url: sourceUrl,
          });
          void refreshStatus();
          toast(binCode ? `Added to ${binCode}` : `Added ${it.name}`);
          done(it.id);
        } catch (err) {
          toast(errorText(err), "err");
          save.disabled = false;
        }
      },
    },
    field("Name", name),
    h("div", { class: "field" }, h("span", { class: "label" }, "Bin"), binSlot),
    locBox,
    h("div", { class: "two" }, field("Category", category), field("How many", qty)),
    field("Tags", tags),
    h("details", { class: "more" }, h("summary", null, "Brand, model, notes"),
      h("div", { class: "two" }, field("Brand", brand), field("Model", model)), field("Notes", desc)),
    save,
  );

  const done = (id: number) => {
    URL.revokeObjectURL(preview);
    replace(root, 
      h("h1", null, "Saved"),
      h("p", null, binCode ? ["It's recorded in ", binChip(binCode, { href: false }), "."] : "It's recorded with its spot."),
      h("button", {
        class: "btn primary big",
        onclick: async () => {
          const f = await pickPhoto();
          if (f) {
            state.pendingPhoto = f;
            navigate("/add", true);
          }
        },
      }, binCode ? `Add another to ${binCode}` : "Add another"),
      h("a", { class: "btn", href: `/item/${id}`, "data-link": true }, "View item"),
      binCode ? h("a", { class: "btn ghost", href: `/b/${binCode}`, "data-link": true }, `See everything in ${binCode}`) : null,
    );
  };

  append(root, 
    h("h1", null, "Add an item"),
    h("div", { class: "add-photo" }, h("img", { src: preview, alt: "The photo you just took" })),
    suggestions,
    form,
  );
  name.focus({ preventScroll: true });

  // ---- identify ----
  let result: IdentifyResult;
  try {
    const small = await shrink(file);
    file = null;
    result = await api.identify(small);
    photoIds.push(result.photo_id);
    save.disabled = false;
  } catch (e) {
    replace(suggestions, h("p", { class: "error" }, `Couldn't upload the photo: ${errorText(e)}`));
    return () => URL.revokeObjectURL(preview);
  }

  const parts: Node[] = [];
  if (result.similar.length) {
    parts.push(
      h("h2", { class: "section-h" }, "You may already have this"),
      h("ul", { class: "rows" }, result.similar.map((it) =>
        h("li", { class: "row" },
          h("a", { class: "row-main", href: `/item/${it.id}`, "data-link": true },
            thumb(it.primary_photo_id, it.name),
            h("span", { class: "row-text" }, h("span", { class: "row-title" }, it.name),
              h("span", { class: "where" }, binChip(it.bin_code, { href: false })))),
          h("button", {
            class: "btn small",
            onclick: async () => {
              try {
                await api.updateItem(it.id, { quantity: it.quantity + 1 });
                await api.addItemPhoto(it.id, result.photo_id);
                toast(`${it.name}: now ${it.quantity + 1}`);
                navigate(`/item/${it.id}`);
              } catch (e) {
                toast(errorText(e), "err");
              }
            },
          }, "+1 to this"),
        ))),
    );
  }
  if (result.candidates.length) {
    apply(result.candidates[0]!);
    parts.push(
      h("h2", { class: "section-h" }, "Is it…"),
      h("ul", { class: "candidates" }, result.candidates.slice(0, 6).map((c, i) => {
        const btn = h("button", {
          type: "button",
          class: `cand${i === 0 ? " picked" : ""}`,
          "aria-pressed": String(i === 0),
          onclick: () => {
            apply(c);
            suggestions.querySelectorAll(".cand").forEach((b) => (b.classList.remove("picked"), b.setAttribute("aria-pressed", "false")));
            btn.classList.add("picked");
            btn.setAttribute("aria-pressed", "true");
          },
        },
          h("span", { class: "cand-name" }, c.name),
          h("span", { class: "cand-meta" }, [SOURCE_LABEL[c.source] ?? c.source, c.brand].filter(Boolean).join(" · ")));
        return h("li", null, btn);
      })),
    );
  } else {
    const p = result.providers;
    parts.push(h("p", { class: "muted" },
      p.google || p.claude
        ? "No match found. Name it yourself; it's still searchable by how it looks."
        : "Automatic naming is off (no Google or Claude key on the server). Name it yourself; it's still searchable by how it looks."));
  }
  if (result.errors.length) parts.push(h("p", { class: "error small" }, result.errors.join("; ")));
  replace(suggestions, ...parts);
  return () => URL.revokeObjectURL(preview);
};

export function field(label: string, control: HTMLElement): HTMLElement {
  return h("label", { class: "field" }, h("span", { class: "label" }, label), control);
}

