import { api, type Item } from "../api";
import { pickPhoto, shrink } from "../camera";
import { emptyState, itemList, spinner } from "../components";
import { append, errorText, h, replace, toast } from "../dom";
import type { View } from "../router";
import { state } from "../state";

export const homeView: View = async (root, _p, query) => {
  const q0 = query.get("q") ?? "";
  const results = h("section", { class: "results", "aria-live": "polite" });
  const input = h("input", {
    type: "search",
    class: "search-input",
    placeholder: "Find anything — “tent stakes”, “something orange”",
    "aria-label": "Search items",
    value: q0,
    autocomplete: "off",
    enterkeyhint: "search",
  });

  let timer: number | undefined;
  let seq = 0;
  const run = async (q: string) => {
    history.replaceState(null, "", q ? `/?q=${encodeURIComponent(q)}` : "/");
    if (!q) return showHome();
    const mine = ++seq;
    replace(results, spinner("Searching…"));
    try {
      const { items } = await api.search(q);
      if (mine !== seq) return;
      replace(results, 
        items.length
          ? h("div", null, h("p", { class: "count" }, `${items.length} found`), itemList(items))
          : emptyState("Nothing matches", `No items match “${q}”. Try a broader word, or search with a photo.`),
      );
    } catch (e) {
      if (mine === seq) replace(results, emptyState("Search failed", errorText(e)));
    }
  };
  input.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => void run(input.value.trim()), 220);
  });

  const photoSearch = async () => {
    const f = await pickPhoto();
    if (!f) return;
    input.value = "";
    const mine = ++seq;
    replace(results, spinner("Looking for things like this…"));
    try {
      const { items } = await api.searchImage(await shrink(f, 800));
      if (mine !== seq) return;
      replace(results, 
        items.length
          ? h("div", null, h("p", { class: "count" }, "Looks like"), itemList(items))
          : emptyState("No lookalikes", "Nothing you've catalogued looks like that photo."),
      );
    } catch (e) {
      replace(results, emptyState("Photo search unavailable", errorText(e)));
    }
  };

  async function showHome() {
    // Shares the search sequence so a slow home load can't overwrite results
    // of a search typed while it was in flight.
    const mine = ++seq;
    replace(results, spinner());
    try {
      const [{ items: recent }, manifest] = await Promise.all([api.items({ limit: "400" }), api.manifest()]);
      if (mine !== seq) return;
      const sorted = [...recent].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 12);
      const parts: HTMLElement[] = [];
      if (manifest.count) {
        parts.push(
          h(
            "a",
            { class: "return-banner", href: "/return", "data-link": true },
            h("strong", null, manifest.count === 1 ? "1 item is checked out" : `${manifest.count} items are checked out`),
            h("span", null, "See where each one goes back"),
          ),
        );
      }
      if (state.status && state.status.items >= 6) {
        parts.push(
          h("a", { class: "tidy-link", href: "/groups", "data-link": true }, "Tidy up: see which things belong together"),
        );
      }
      parts.push(
        sorted.length
          ? h("div", null, h("h2", { class: "section-h" }, "Recently added"), itemList(sorted as Item[]))
          : emptyState(
              "Nothing catalogued yet",
              "Tap Add and photograph something. It's identified for you; then put it in a bin.",
            ),
      );
      replace(results, ...parts);
    } catch (e) {
      if (mine !== seq) return;
      replace(results, emptyState("Can't load", errorText(e)));
      toast(errorText(e), "err");
    }
  }

  append(root, 
    h("h1", { class: "visually-hidden" }, "Find"),
    h(
      "form",
      { class: "search-bar", role: "search", onsubmit: (e: Event) => (e.preventDefault(), input.blur(), void run(input.value.trim())) },
      input,
      h("button", { type: "button", class: "icon-btn camera-btn", onclick: photoSearch, "aria-label": "Search with a photo", title: "Search with a photo" }, cameraIcon()),
    ),
    results,
  );
  if (q0) void run(q0);
  else void showHome();
  return () => window.clearTimeout(timer);
};

export function cameraIcon(): SVGElement {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML =
    '<path d="M4 8h3l2-3h6l2 3h3v11H4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="12" cy="13" r="3.5" fill="none" stroke="currentColor" stroke-width="2"/>';
  return svg;
}

