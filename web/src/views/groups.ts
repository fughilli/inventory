// Tidy-up suggestions: items that belong together but are spread over bins.

import { api, type Group } from "../api";
import { emptyState, itemList, spinner } from "../components";
import { append, binChip, errorText, h, replace, toast } from "../dom";
import { navigate, type View } from "../router";
import { state } from "../state";

const KEY = "inventory.groupThreshold";

export const groupsView: View = async (root, _p, query) => {
  let threshold = Number(query.get("t") ?? (() => { try { return localStorage.getItem(KEY); } catch { return null; } })() ?? 0.3);
  const ai = query.get("ai") === "1";
  const out = h("div", { "aria-live": "polite" });
  const slider = h("input", { type: "range", min: "0.1", max: "0.6", step: "0.05", value: String(threshold), "aria-label": "How strict grouping is" });
  slider.addEventListener("change", () => {
    threshold = Number(slider.value);
    try { localStorage.setItem(KEY, slider.value); } catch { /* private mode */ }
    void load();
  });

  async function load() {
    replace(out, spinner("Grouping…"));
    let groups: Group[];
    let method: string;
    try {
      ({ groups, method } = await api.groups(threshold, ai));
    } catch (e) {
      replace(out, emptyState("Can't group", errorText(e)));
      return;
    }
    const messy = groups.filter((g) => g.fragmentation > 1);
    const tidy = groups.filter((g) => g.fragmentation <= 1);
    replace(out, 
      method === "category" ? h("p", { class: "muted small" }, "Grouped by category. Visual grouping turns on once the image model has loaded on the server.") : null,
      messy.length
        ? messy.map(groupCard)
        : emptyState("Nicely sorted", "No group of related things is split across bins at this setting."),
      tidy.length ? h("details", { class: "more" }, h("summary", null, `${tidy.length} groups already in one bin`), tidy.map(groupCard)) : null,
    );
  }

  function groupCard(g: Group): HTMLElement {
    const binList = Object.entries(g.bins);
    return h("section", { class: "group" },
      h("h2", null, g.name, h("small", null, ` ${g.items.length} items`)),
      h("p", { class: "spread" },
        binList.map(([code, n]) => h("span", null, binChip(code), ` ${n}`)),
        g.unbinned ? h("span", null, h("span", { class: "chip none" }, "No bin"), ` ${g.unbinned}`) : null),
      g.moves.length && g.target_bin
        ? h("div", { class: "suggestion" },
            h("p", null, `Move ${g.moves.length === 1 ? "1 item" : `${g.moves.length} items`} into `, binChip(g.target_bin), " to keep these together."),
            h("button", {
              class: "btn primary small",
              onclick: async () => {
                try {
                  await api.move(g.moves, g.target_bin);
                  toast(`Moved ${g.moves.length} into ${g.target_bin}. Physically move them too.`);
                  void load();
                } catch (e) {
                  toast(errorText(e), "err");
                }
              },
            }, "I moved them"))
        : null,
      h("details", null, h("summary", null, "Items"), itemList(g.items)));
  }

  append(root, 
    h("h1", null, "Tidy up"),
    h("p", { class: "lede" }, "Things that belong together but live in different bins."),
    h("div", { class: "slider" }, h("span", null, "Broad"), slider, h("span", null, "Strict")),
    state.status?.identify.claude && !ai
      ? h("button", { class: "btn ghost small", onclick: () => navigate(`/groups?t=${threshold}&ai=1`, true) }, "Name groups with Claude")
      : null,
    out,
  );
  void load();
};
