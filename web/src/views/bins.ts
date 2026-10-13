import { api, photoUrl, type Bin } from "../api";
import { emptyState, spinner } from "../components";
import { append, errorText, h, replace, sheet, toast } from "../dom";
import { navigate, type View } from "../router";

export const binsView: View = async (root) => {
  append(root, h("h1", null, "Bins"), spinner());
  let bins: Bin[];
  try {
    bins = (await api.bins()).bins;
  } catch (e) {
    replace(root, h("h1", null, "Bins"), emptyState("Can't load bins", errorText(e)));
    return;
  }
  const filter = h("input", { type: "search", placeholder: "Filter by code, name or shelf", "aria-label": "Filter bins" });
  const grid = h("ul", { class: "bin-grid" });
  const draw = () => {
    const q = filter.value.trim().toLowerCase();
    replace(grid, ...bins
      .filter((b) => !q || `${b.code} ${b.name} ${b.location}`.toLowerCase().includes(q))
      .map((b) => h("li", null, h("a", { class: "bin-tile", href: `/b/${b.code}`, "data-link": true },
        h("span", { class: "tile-code" }, b.code),
        h("span", { class: "tile-name" }, b.name || "Unnamed"),
        h("span", { class: "tile-meta" },
          b.item_count === 1 ? "1 item" : `${b.item_count} items`,
          b.out_count ? h("span", { class: "out-tag" }, `${b.out_count} out`) : null),
        b.cover_photo_id ? h("img", { class: "tile-photo", src: photoUrl(b.cover_photo_id), alt: "", loading: "lazy" }) : null))));
  };
  filter.addEventListener("input", draw);
  draw();

  replace(root, 
    h("h1", null, "Bins"),
    h("div", { class: "btn-row" },
      h("button", { class: "btn primary", onclick: () => newBinsSheet() }, "New bins"),
      h("a", { class: "btn", href: "/groups", "data-link": true }, "Tidy up")),
    bins.length > 8 ? filter : null,
    bins.length ? grid : emptyState("No bins yet", "Make a bin and print its label, then stick the label on the tote."),
  );
};

function newBinsSheet(): Promise<void> {
  return sheet("New bins", (close) => {
    const count = h("input", { type: "number", min: "1", max: "100", value: "1", inputmode: "numeric" });
    const name = h("input", { type: "text", placeholder: "e.g. Camping (optional)" });
    const location = h("input", { type: "text", placeholder: "e.g. Rack A, top shelf (optional)" });
    const print = h("input", { type: "checkbox", checked: true });
    const go = h("button", { class: "btn primary", type: "submit" }, "Create");
    return h("form", {
      class: "item-form",
      onsubmit: async (e: Event) => {
        e.preventDefault();
        go.disabled = true;
        const n = Math.max(1, Number(count.value) || 1);
        try {
          const r = await api.createBins(n > 1 ? { count: n, print: print.checked } : { name: name.value, location: location.value, print: print.checked });
          const codes = r.bins.map((b) => b.code);
          toast(`${codes.length > 1 ? `${codes[0]}–${codes[codes.length - 1]}` : codes[0]} created${print.checked ? " and sent to the printer" : ""}`);
          close();
          navigate(codes.length === 1 ? `/b/${codes[0]}` : "/bins", true);
        } catch (err) {
          toast(errorText(err), "err");
          go.disabled = false;
          if (print.checked) navigate("/bins", true); // bins exist even if printing failed
        }
      },
    },
      h("label", { class: "field" }, h("span", { class: "label" }, "How many"), count),
      h("p", { class: "muted small" }, "Codes are numbered automatically. Name and shelf apply when making one bin; add them later otherwise."),
      h("label", { class: "field" }, h("span", { class: "label" }, "Name"), name),
      h("label", { class: "field" }, h("span", { class: "label" }, "Shelf / location"), location),
      h("label", { class: "check" }, print, " Print labels now"),
      go);
  });
}
