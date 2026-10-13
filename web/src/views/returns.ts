// The check-in manifest: everything checked out, grouped by the bin it goes back to.

import { api } from "../api";
import { emptyState, spinner, thumb } from "../components";
import { append, binChip, errorText, h, relTime, replace, toast } from "../dom";
import { navigate, type View } from "../router";
import { refreshStatus } from "../state";

export const returnsView: View = async (root) => {
  append(root, h("h1", null, "Check in"), spinner());
  let m;
  try {
    m = await api.manifest();
  } catch (e) {
    replace(root, h("h1", null, "Check in"), emptyState("Can't load", errorText(e)));
    return;
  }
  const reload = () => navigate("/return", true);
  const checkin = async (ids: number[], msg: string) => {
    try {
      await api.checkin(ids);
      toast(msg);
      void refreshStatus();
      reload();
    } catch (e) {
      toast(errorText(e), "err");
    }
  };

  if (!m.count) {
    replace(root, h("h1", null, "Check in"),
      emptyState("Everything's home", "Nothing is checked out. When you take something out of a bin, check it out so it shows up here."));
    return;
  }

  replace(root, 
    h("h1", null, "Check in"),
    h("p", { class: "lede" }, m.count === 1 ? "1 item to put back." : `${m.count} items to put back, by bin.`),
    ...m.groups.map((g) =>
      h("section", { class: "manifest-group" },
        h("header", null,
          g.bin_code ? binChip(g.bin_code, { big: true }) : h("span", { class: "chip none big" }, "No bin"),
          h("div", null,
            h("strong", null, g.bin_name || (g.bin_code ? "Unnamed bin" : "Put back in their spots")),
            g.bin_location ? h("small", null, g.bin_location) : null),
          g.items.length > 1 && g.bin_code
            ? h("button", { class: "btn small", onclick: () => checkin(g.items.map((i) => i.id), `${g.items.length} back in ${g.bin_code}`) }, "All back")
            : null),
        h("ul", { class: "rows" }, g.items.map((it) =>
          h("li", { class: "row" },
            h("a", { class: "row-main", href: `/item/${it.id}`, "data-link": true },
              thumb(it.primary_photo_id, it.name),
              h("span", { class: "row-text" },
                h("span", { class: "row-title" }, it.name),
                h("span", { class: "muted" }, g.bin_code ? `Out ${relTime(it.checked_out_at)}` : it.location_note || "No spot recorded"))),
            h("button", { class: "btn small primary", onclick: () => checkin([it.id], g.bin_code ? `Back in ${g.bin_code}` : "Checked in") }, "Back"))))),
    ),
  );
};
