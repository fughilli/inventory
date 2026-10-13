// Shared UI pieces built on dom.ts.

import { api, photoUrl, type Bin, type Item } from "./api";
import { canScanLive, binCodeFromText, decodeQrFromPhoto, pickPhoto, scanLive } from "./camera";
import { append, binChip, errorText, h, relTime, replace, sheet, toast } from "./dom";
import { navigate } from "./router";

export function thumb(id: number | null, alt: string, cls = "thumb"): HTMLElement {
  return id
    ? h("img", { class: cls, src: photoUrl(id), alt, loading: "lazy", decoding: "async" })
    : h("div", { class: `${cls} empty`, "aria-hidden": "true" }, alt.slice(0, 1).toUpperCase());
}

/** Where an item lives, as one line: bin chip + location / out status. */
export function whereLine(it: Item): HTMLElement {
  return h(
    "span",
    { class: "where" },
    it.bin_code ? binChip(it.bin_code, { href: false }) : null,
    it.bin_code
      ? it.bin_location
        ? h("span", { class: "muted" }, it.bin_location)
        : null
      : h("span", { class: "muted" }, it.location_note || "No bin yet"),
    it.checked_out ? h("span", { class: "out-tag" }, `Out ${relTime(it.checked_out_at)}`) : null,
  );
}

export function itemRow(it: Item, opts: { selectable?: Set<number>; onToggle?: () => void; trailing?: Node } = {}): HTMLElement {
  const sel = opts.selectable;
  const body = h(
    "a",
    { class: "row-main", href: `/item/${it.id}`, "data-link": true },
    thumb(it.primary_photo_id, it.name),
    h(
      "span",
      { class: "row-text" },
      h("span", { class: "row-title" }, it.name, it.quantity > 1 ? h("span", { class: "qty" }, ` ×${it.quantity}`) : null),
      whereLine(it),
    ),
  );
  const row = h("li", { class: `row${it.checked_out ? " is-out" : ""}` });
  if (sel) {
    const box = h("input", {
      type: "checkbox",
      class: "row-check",
      "aria-label": `Select ${it.name}`,
      checked: sel.has(it.id),
      onchange: (e: Event) => {
        if ((e.target as HTMLInputElement).checked) sel.add(it.id);
        else sel.delete(it.id);
        opts.onToggle?.();
      },
    });
    append(row, box);
  }
  append(row, body);
  if (opts.trailing) append(row, opts.trailing);
  return row;
}

export function itemList(items: Item[], opts: Parameters<typeof itemRow>[1] = {}): HTMLElement {
  return h("ul", { class: "rows" }, items.map((i) => itemRow(i, opts)));
}

export function spinner(text = "Loading…"): HTMLElement {
  return h("p", { class: "loading", role: "status" }, h("span", { class: "spin", "aria-hidden": "true" }), text);
}

export function emptyState(title: string, body: string, action?: HTMLElement): HTMLElement {
  return h("div", { class: "empty-state" }, h("h2", null, title), h("p", null, body), action ?? null);
}

/** Scan a bin label: live camera when allowed, otherwise from a still photo. */
export function scanBinCode(): Promise<string | null> {
  let found: string | null = null;
  return sheet("Scan a bin label", (close) => {
    const status = h("p", { class: "muted" }, "Point the camera at the QR code on the label.");
    const done = (text: string | null) => {
      const code = text ? binCodeFromText(text) : null;
      if (code) {
        found = code;
        close();
      } else if (text) {
        status.textContent = `That QR code isn't a bin label (${text.slice(0, 40)}).`;
      }
    };
    const photoBtn = h(
      "button",
      {
        class: "btn",
        onclick: async () => {
          const f = await pickPhoto();
          if (!f) return;
          status.textContent = "Reading the label…";
          const text = await decodeQrFromPhoto(f);
          if (!text) status.textContent = "Couldn't find a QR code. Get closer and keep the label flat and lit.";
          done(text);
        },
      },
      "Take a photo of the label",
    );
    const box = h("div", { class: "stack" });
    if (canScanLive()) {
      const video = h("video", { class: "scanner", muted: true, playsInline: true, "aria-label": "Camera preview" });
      append(box, h("div", { class: "scanner-frame" }, video, h("div", { class: "reticle", "aria-hidden": "true" })));
      const s = scanLive(video);
      s.result.then(done, (e: unknown) => {
        if (errorText(e) !== "stopped") status.textContent = `Camera unavailable: ${errorText(e)}`;
      });
      const obs = new MutationObserver(() => {
        if (!video.isConnected) {
          s.stop();
          obs.disconnect();
        }
      });
      obs.observe(document.body, { childList: true, subtree: true });
    }
    const typed = h("input", { type: "text", inputmode: "numeric", placeholder: "or type it: 7, B007", "aria-label": "Bin code" });
    append(box, 
      status,
      photoBtn,
      h(
        "form",
        { class: "inline-form", onsubmit: (e: Event) => (e.preventDefault(), done(/^\d+$/.test(typed.value.trim()) ? `B${typed.value.trim().padStart(3, "0")}` : typed.value)) },
        typed,
        h("button", { class: "btn", type: "submit" }, "Go"),
      ),
    );
    return box;
  }).then(() => found);
}

/** Choose a destination bin: scan, pick from the list, or make a new one. */
export async function pickBin(title = "Choose a bin", allowNone = false): Promise<string | null | undefined> {
  let picked: string | null | undefined = undefined;
  let scanAfter = false;
  let bins: Bin[] = [];
  try {
    bins = (await api.bins()).bins;
  } catch (e) {
    toast(errorText(e), "err");
  }
  await sheet(title, (close) => {
    const filter = h("input", { type: "search", placeholder: "Filter bins", "aria-label": "Filter bins" });
    const list = h("ul", { class: "bin-pick" });
    const draw = () => {
      const q = filter.value.trim().toLowerCase();
      replace(list, 
        ...bins
          .filter((b) => !q || `${b.code} ${b.name} ${b.location}`.toLowerCase().includes(q))
          .map((b) =>
            h(
              "li",
              null,
              h(
                "button",
                { class: "bin-pick-btn", onclick: () => ((picked = b.code), close()) },
                binChip(b.code, { href: false }),
                h("span", null, b.name || h("span", { class: "muted" }, "Unnamed"), h("small", null, `${b.item_count} items${b.location ? ` · ${b.location}` : ""}`)),
              ),
            ),
          ),
      );
    };
    filter.addEventListener("input", draw);
    draw();
    return h(
      "div",
      { class: "stack" },
      h("div", { class: "btn-row" },
        h("button", { class: "btn primary", onclick: () => ((scanAfter = true), close()) }, "Scan label"),
        h("button", {
          class: "btn",
          onclick: async () => {
            try {
              const b = (await api.createBins({})).bins[0]!;
              toast(`Created ${b.code}. Print its label from the bin page.`);
              picked = b.code;
              close();
            } catch (e) {
              toast(errorText(e), "err");
            }
          },
        }, "New bin"),
      ),
      allowNone ? h("button", { class: "btn ghost", onclick: () => ((picked = null), close()) }, "Not in a bin") : null,
      bins.length > 6 ? filter : null,
      list,
    );
  });
  // Scanning opens its own sheet, so it runs after this one has closed.
  if (scanAfter) picked = (await scanBinCode()) ?? undefined;
  return picked;
}

export function goBack(fallback = "/"): void {
  if (history.length > 1) history.back();
  else navigate(fallback);
}
