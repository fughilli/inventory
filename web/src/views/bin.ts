import { api, type Bin, type Item } from "../api";
import { pickPhoto } from "../camera";
import { emptyState, goBack, itemList, pickBin, spinner } from "../components";
import { append, confirmSheet, errorText, h, replace, sheet, toast } from "../dom";
import { navigate, type View } from "../router";
import { refreshStatus, setPacking, state } from "../state";
import { field } from "./add";

export const binView: View = async (root, { code }) => {
  append(root, spinner());
  let bin: Bin & { items: Item[] };
  try {
    bin = await api.bin(code!);
  } catch (e) {
    replace(root, emptyState(`No bin ${code?.toUpperCase()}`, errorText(e), h("a", { class: "btn", href: "/bins", "data-link": true }, "All bins")));
    return;
  }
  if (bin.code !== code) history.replaceState(null, "", `/b/${bin.code}`);
  const reload = () => navigate(`/b/${bin.code}`, true);
  const selected = new Set<number>();
  const bar = h("div", { class: "select-bar", hidden: true });

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

  const drawBar = () => {
    bar.hidden = selected.size === 0;
    const ids = [...selected];
    const anyIn = bin.items.some((i) => selected.has(i.id) && !i.checked_out);
    replace(bar, 
      h("span", null, `${selected.size} selected`),
      anyIn
        ? h("button", { class: "btn primary small", onclick: () => act(() => api.checkout(ids), `Checked out ${ids.length}`) }, "Check out")
        : h("button", { class: "btn primary small", onclick: () => act(() => api.checkin(ids), `Checked in ${ids.length}`) }, "Check in"),
      h("button", {
        class: "btn small",
        onclick: async () => {
          const b = await pickBin(`Move ${ids.length} to…`, true);
          if (b !== undefined) await act(() => api.move(ids, b), b ? `Moved to ${b}` : "Taken out of the bin");
        },
      }, "Move"),
    );
  };

  const packing = state.packing === bin.code;
  const inItems = bin.items.filter((i) => !i.checked_out);
  const outItems = bin.items.filter((i) => i.checked_out);

  replace(root, 
    h("button", { class: "back", onclick: () => goBack("/bins") }, "‹ Back"),
    h("header", { class: "label-hero" },
      h("h1", { class: "label-code" }, bin.code),
      h("p", { class: "label-name" }, bin.name || "Unnamed bin"),
      bin.location ? h("p", { class: "label-loc" }, bin.location) : null,
      h("p", { class: "label-count" }, `${bin.item_count} ${bin.item_count === 1 ? "item" : "items"}${bin.out_count ? `, ${bin.out_count} checked out` : ""}`)),
    h("div", { class: "btn-row" },
      packing
        ? h("button", { class: "btn", onclick: () => (setPacking(null), reload()) }, "Stop packing")
        : h("button", { class: "btn primary", onclick: () => (setPacking(bin.code), toast(`New items go into ${bin.code}`), reload()) }, "Pack this bin"),
      h("button", {
        class: "btn",
        onclick: async () => {
          try {
            await api.printBins([bin.code]);
            toast(`Printing ${bin.code}`);
          } catch (e) {
            toast(errorText(e), "err");
          }
        },
      }, "Print label"),
      h("button", { class: "btn", onclick: () => editBin(bin).then((c) => c && reload()) }, "Edit")),
    packing ? h("button", {
      class: "btn primary big",
      onclick: async () => {
        const f = await pickPhoto();
        if (f) {
          state.pendingPhoto = f;
          navigate("/add");
        }
      },
    }, `Photograph the next item for ${bin.code}`) : null,
    bin.items.length
      ? [
          h("h2", { class: "section-h" }, "In this bin"),
          inItems.length ? itemList(inItems, { selectable: selected, onToggle: drawBar }) : h("p", { class: "muted" }, "Everything from this bin is checked out."),
          outItems.length ? [h("h2", { class: "section-h" }, "Checked out"), itemList(outItems, { selectable: selected, onToggle: drawBar })] : null,
        ]
      : emptyState("Empty bin", "Tap “Pack this bin”, then photograph each thing as it goes in."),
    bar,
    h("details", { class: "more" }, h("summary", null, "Label preview"),
      h("img", { class: "label-preview", src: api.labelUrl(bin.code), alt: `Printed label for ${bin.code}`, loading: "lazy" })),
    bin.item_count === 0 ? h("button", {
      class: "btn ghost danger-text",
      onclick: async () => {
        if (await confirmSheet(`Delete ${bin.code}?`, "The empty bin is removed from the list. Its code won't be reused unless it was the newest.", "Delete bin", true)) {
          try {
            await api.deleteBin(bin.code);
            if (state.packing === bin.code) setPacking(null);
            navigate("/bins", true);
          } catch (e) {
            toast(errorText(e), "err");
          }
        }
      },
    }, "Delete bin") : null,
  );
};

function editBin(bin: Bin): Promise<boolean> {
  let changed = false;
  return sheet(`Edit ${bin.code}`, (close) => {
    const name = h("input", { type: "text", value: bin.name, placeholder: "e.g. Camping" });
    const location = h("input", { type: "text", value: bin.location, placeholder: "e.g. Rack A, top shelf" });
    const notes = h("textarea", { rows: 2 }, bin.notes);
    return h("form", {
      class: "item-form",
      onsubmit: async (e: Event) => {
        e.preventDefault();
        try {
          await api.updateBin(bin.code, { name: name.value, location: location.value, notes: notes.value });
          changed = true;
          toast("Saved");
          close();
        } catch (err) {
          toast(errorText(err), "err");
        }
      },
    }, field("Name", name), field("Shelf / location", location), field("Notes", notes),
      h("p", { class: "muted small" }, "The name is printed on the label; reprint it after renaming."),
      h("button", { class: "btn primary", type: "submit" }, "Save changes"));
  }).then(() => changed);
}
