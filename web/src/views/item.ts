import { api, photoUrl, type ItemDetail } from "../api";
import { pickPhoto, shrink } from "../camera";
import { emptyState, goBack, pickBin, spinner } from "../components";
import { append, binChip, confirmSheet, errorText, h, relTime, replace, sheet, toast } from "../dom";
import { navigate, type View } from "../router";
import { categories, refreshStatus } from "../state";
import { field } from "./add";

const EVENT_TEXT: Record<string, string> = {
  created: "Added",
  binned: "Put in",
  moved: "Moved to",
  unbinned: "Taken out of its bin",
  checked_out: "Checked out of",
  checked_in: "Checked in to",
};

export const itemView: View = async (root, { id }) => {
  append(root, spinner());
  let it: ItemDetail;
  try {
    it = await api.item(Number(id));
  } catch (e) {
    replace(root, emptyState("Item not found", errorText(e), h("a", { class: "btn", href: "/", "data-link": true }, "Back to search")));
    return;
  }
  const reload = () => navigate(`/item/${it.id}`, true);

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try {
      await fn();
      toast(msg);
      void refreshStatus();
      reload();
    } catch (e) {
      toast(errorText(e), "err");
    }
  };

  const photos = it.photos.filter((p) => p.kind === "item");
  const gallery = photos.length
    ? h("div", { class: "gallery" }, photos.map((p) =>
        h("img", { src: photoUrl(p.id, false), alt: it.name, loading: "lazy", width: p.width, height: p.height })))
    : h("div", { class: "gallery empty" }, h("span", null, "No photo"));

  const locPhoto = it.location_photo_id
    ? h("figure", { class: "spot" }, h("img", { src: photoUrl(it.location_photo_id, false), alt: `Where ${it.name} is kept` }),
        h("figcaption", null, it.location_note || "Where it's kept"))
    : null;

  const status = it.checked_out
    ? h("div", { class: "status out" },
        h("strong", null, `Checked out ${relTime(it.checked_out_at)}`),
        h("span", null, it.bin_code ? ["Goes back in ", binChip(it.bin_code)] : it.location_note || "No home bin set"),
        it.checked_out_note ? h("span", { class: "muted" }, it.checked_out_note) : null)
    : h("div", { class: "status" },
        it.bin_code
          ? [binChip(it.bin_code, { big: true }), h("span", null, it.bin_name || "", it.bin_location ? h("small", null, it.bin_location) : null)]
          : h("span", null, it.location_note || "Not in a bin, and no spot recorded"));

  const primary = it.checked_out
    ? h("button", { class: "btn primary big", onclick: () => act(() => api.checkin([it.id]), it.bin_code ? `Checked in to ${it.bin_code}` : "Checked in") },
        it.bin_code ? `Check in to ${it.bin_code}` : "Check in")
    : h("button", { class: "btn primary big", onclick: () => act(() => api.checkout([it.id]), "Checked out") }, "Check out");

  const actions = h("div", { class: "btn-row" },
    h("button", {
      class: "btn",
      onclick: async () => {
        const b = await pickBin(`Move ${it.name} to…`, true);
        if (b !== undefined) await act(() => api.move([it.id], b), b ? `Moved to ${b}` : "Taken out of its bin");
      },
    }, it.checked_out ? "Check in elsewhere" : "Move"),
    h("button", { class: "btn", onclick: () => editSheet(it).then((changed) => changed && reload()) }, "Edit"),
    h("button", {
      class: "btn",
      onclick: async () => {
        const f = await pickPhoto();
        if (!f) return;
        try {
          const p = await api.uploadPhoto(await shrink(f));
          await act(() => api.addItemPhoto(it.id, p.id), "Photo added");
        } catch (e) {
          toast(errorText(e), "err");
        }
      },
    }, "Add photo"),
  );

  const facts = [
    it.category && ["Category", it.category],
    it.brand && ["Brand", it.brand],
    it.model && ["Model", it.model],
    it.quantity > 1 && ["Quantity", String(it.quantity)],
  ].filter(Boolean) as [string, string][];

  replace(root, 
    h("button", { class: "back", onclick: () => goBack() }, "‹ Back"),
    gallery,
    h("h1", { class: "item-title" }, it.name),
    status,
    primary,
    actions,
    it.description ? h("p", { class: "desc" }, it.description) : null,
    it.tags.length ? h("ul", { class: "tags" }, it.tags.map((t) =>
      h("li", null, h("a", { href: `/?q=${encodeURIComponent(t)}`, "data-link": true }, t)))) : null,
    facts.length ? h("dl", { class: "facts" }, facts.map(([k, v]) => [h("dt", null, k), h("dd", null, v)])) : null,
    it.source_url ? h("p", null, h("a", { href: it.source_url, target: "_blank", rel: "noopener" }, "Product page")) : null,
    locPhoto,
    h("h2", { class: "section-h" }, "History"),
    h("ol", { class: "history" }, it.events.map((e) =>
      h("li", null, h("span", null, EVENT_TEXT[e.kind] ?? e.kind, " ", e.bin_code && e.kind !== "created" ? binChip(e.bin_code, { href: false }) : null),
        h("time", { datetime: e.at }, relTime(e.at))))),
    h("button", {
      class: "btn ghost danger-text",
      onclick: async () => {
        if (await confirmSheet("Delete this item?", `${it.name} and its photos will be removed for good.`, "Delete item", true)) {
          try {
            await api.deleteItem(it.id);
            toast("Deleted");
            void refreshStatus();
            navigate("/", true);
          } catch (e) {
            toast(errorText(e), "err");
          }
        }
      },
    }, "Delete item"),
  );
};

function editSheet(it: ItemDetail): Promise<boolean> {
  let changed = false;
  return sheet("Edit item", (close) => {
    const name = h("input", { type: "text", value: it.name, required: true });
    const category = h("select", null, h("option", { value: "" }, "None"),
      [...new Set([...categories(), it.category].filter(Boolean))].map((c) => h("option", { value: c, selected: c === it.category }, c)));
    const tags = h("input", { type: "text", value: it.tags.join(", ") });
    const qty = h("input", { type: "number", min: "1", value: String(it.quantity) });
    const brand = h("input", { type: "text", value: it.brand });
    const model = h("input", { type: "text", value: it.model });
    const desc = h("textarea", { rows: 3 }, it.description);
    const loc = h("input", { type: "text", value: it.location_note, placeholder: "Only used when it's not in a bin" });
    return h("form", {
      class: "item-form",
      onsubmit: async (e: Event) => {
        e.preventDefault();
        try {
          await api.updateItem(it.id, {
            name: name.value, category: category.value, tags: tags.value.split(","),
            quantity: Number(qty.value) || 1, brand: brand.value, model: model.value,
            description: desc.value, location_note: loc.value,
          });
          changed = true;
          toast("Saved");
          close();
        } catch (err) {
          toast(errorText(err), "err");
        }
      },
    },
      field("Name", name), h("div", { class: "two" }, field("Category", category), field("How many", qty)),
      field("Tags", tags), h("div", { class: "two" }, field("Brand", brand), field("Model", model)),
      field("Notes", desc), field("Spot (if not in a bin)", loc),
      h("button", { class: "btn primary", type: "submit" }, "Save changes"));
  }).then(() => changed);
}
