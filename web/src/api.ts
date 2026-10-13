// Typed client for the FastAPI backend (server/inventory/app.py).

export interface Item {
  id: number;
  name: string;
  description: string;
  category: string;
  tags: string[];
  brand: string;
  model: string;
  quantity: number;
  bin_id: number | null;
  bin_code: string | null;
  bin_name: string | null;
  bin_location: string | null;
  location_note: string;
  location_photo_id: number | null;
  primary_photo_id: number | null;
  checked_out: boolean;
  checked_out_at: string | null;
  checked_out_note: string;
  source: string;
  source_url: string;
  created_at: string;
  updated_at: string;
  match?: string[];
  score?: number;
}

export interface ItemDetail extends Item {
  photos: { id: number; kind: string; width: number; height: number }[];
  events: { kind: string; note: string; at: string; bin_code: string | null }[];
}

export interface Bin {
  id: number;
  code: string;
  name: string;
  location: string;
  notes: string;
  item_count: number;
  out_count: number;
  cover_photo_id?: number | null;
  items?: Item[];
}

export interface Candidate {
  name: string;
  source: string;
  description: string;
  category: string;
  brand: string;
  model: string;
  tags: string[];
  url: string;
  confidence: number;
}

export interface IdentifyResult {
  photo_id: number;
  candidates: Candidate[];
  similar: Item[];
  errors: string[];
  providers: { google: boolean; claude: boolean; embedder: string };
}

export interface Status {
  items: number;
  bins: number;
  checked_out: number;
  unbinned: number;
  identify: { google: boolean; claude: boolean };
  embedder: string;
  categories: string[];
  printer?: { reachable: boolean; present?: boolean; device?: string | null; error?: string; last_error?: string | null };
}

export interface ManifestGroup {
  bin_code: string | null;
  bin_name: string | null;
  bin_location: string | null;
  items: Item[];
}

export interface Group {
  name: string;
  items: Item[];
  target_bin: string | null;
  bins: Record<string, number>;
  unbinned: number;
  moves: number[];
  fragmentation: number;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "Can't reach the garage server. Check you're on the home network.");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg);
  }
  return (await res.json()) as T;
}

const enc = encodeURIComponent;

export const api = {
  status: (printer = false) => req<Status>("GET", `/api/status${printer ? "?printer=1" : ""}`),

  search: (q: string) => req<{ items: Item[] }>("GET", `/api/search?q=${enc(q)}`),
  searchImage: (photo: Blob) => {
    const f = new FormData();
    f.append("file", photo, "query.jpg");
    return req<{ items: Item[] }>("POST", "/api/search/image", f);
  },
  identify: (photo: Blob) => {
    const f = new FormData();
    f.append("file", photo, "photo.jpg");
    return req<IdentifyResult>("POST", "/api/identify", f);
  },
  uploadPhoto: (photo: Blob, kind: "item" | "location" | "bin" = "item") => {
    const f = new FormData();
    f.append("file", photo, "photo.jpg");
    f.append("kind", kind);
    return req<{ id: number }>("POST", "/api/photos", f);
  },

  items: (params: Record<string, string> = {}) =>
    req<{ items: Item[] }>("GET", `/api/items?${new URLSearchParams(params)}`),
  item: (id: number) => req<ItemDetail>("GET", `/api/items/${id}`),
  createItem: (body: Partial<Item> & { name: string; bin_code?: string | null; photo_ids?: number[] }) =>
    req<Item>("POST", "/api/items", body),
  updateItem: (id: number, body: Partial<Item>) => req<Item>("PATCH", `/api/items/${id}`, body),
  deleteItem: (id: number) => req<{ ok: boolean }>("DELETE", `/api/items/${id}`),
  addItemPhoto: (id: number, photo_id: number, primary = false) =>
    req<Item>("POST", `/api/items/${id}/photos`, { photo_id, primary }),
  move: (item_ids: number[], bin_code: string | null) =>
    req<{ items: Item[] }>("POST", "/api/items/move", { item_ids, bin_code }),
  checkout: (item_ids: number[], note = "") =>
    req<{ items: Item[] }>("POST", "/api/items/checkout", { item_ids, note }),
  checkin: (item_ids: number[], bin_code: string | null = null) =>
    req<{ items: Item[] }>("POST", "/api/items/checkin", { item_ids, bin_code }),
  manifest: () => req<{ count: number; groups: ManifestGroup[] }>("GET", "/api/manifest"),

  bins: () => req<{ bins: Bin[] }>("GET", "/api/bins"),
  bin: (code: string) => req<Bin & { items: Item[] }>("GET", `/api/bins/${enc(code)}`),
  createBins: (body: { name?: string; location?: string; count?: number; print?: boolean }) =>
    req<{ bins: Bin[]; printed: unknown }>("POST", "/api/bins", body),
  updateBin: (code: string, body: Partial<Bin>) => req<Bin>("PATCH", `/api/bins/${enc(code)}`, body),
  deleteBin: (code: string) => req<{ ok: boolean }>("DELETE", `/api/bins/${enc(code)}`),
  printBins: (codes: string[], copies = 1) => req<unknown>("POST", "/api/print", { codes, copies }),
  labelUrl: (code: string) => `/api/bins/${enc(code)}/label.png`,

  groups: (threshold: number, aiNames: boolean) =>
    req<{ method: string; groups: Group[] }>("GET", `/api/groups?threshold=${threshold}&ai_names=${aiNames}`),
};

export const photoUrl = (id: number, thumb = true) => (thumb ? `/photos/${id}/thumb.jpg` : `/photos/${id}.jpg`);
