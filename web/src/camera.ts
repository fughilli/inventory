// Photo capture + QR scanning.
//
// Capture uses <input type=file capture=environment>: it opens the phone's
// native camera (full quality, works over plain http on the LAN). Live QR
// scanning needs getUserMedia, which browsers only allow in a secure context
// (https, e.g. via `tailscale serve`); without it we decode the QR from a still.

import jsQR from "jsqr";

const MAX_EDGE = 1600;

/** Must be called synchronously from a user gesture (tap). */
export function pickPhoto(opts: { camera?: boolean } = { camera: true }): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    if (opts.camera !== false) input.setAttribute("capture", "environment");
    input.style.display = "none";
    let done = false;
    const finish = (f: File | null) => {
      if (done) return;
      done = true;
      input.remove();
      resolve(f);
    };
    input.addEventListener("change", () => finish(input.files?.[0] ?? null));
    input.addEventListener("cancel", () => finish(null));
    document.body.append(input);
    input.click();
  });
}

async function toBitmap(file: Blob): Promise<ImageBitmap> {
  // from-image honours EXIF orientation from phone cameras.
  return createImageBitmap(file, { imageOrientation: "from-image" });
}

/** Downscale a phone photo to <=1600px JPEG before upload (12MP -> ~300KB). */
export async function shrink(file: Blob, maxEdge = MAX_EDGE): Promise<Blob> {
  const bmp = await toBitmap(file);
  const s = Math.min(1, maxEdge / Math.max(bmp.width, bmp.height));
  const w = Math.round(bmp.width * s);
  const hgt = Math.round(bmp.height * s);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = hgt;
  canvas.getContext("2d")!.drawImage(bmp, 0, 0, w, hgt);
  bmp.close();
  return new Promise((res, rej) =>
    canvas.toBlob((b) => (b ? res(b) : rej(new Error("could not encode photo"))), "image/jpeg", 0.85),
  );
}

/** Pull a bin code out of whatever a QR held: our URL (…/b/B007) or a bare code. */
export function binCodeFromText(text: string): string | null {
  const m = text.match(/\/b\/(B\d{3,})\b/i) ?? text.trim().match(/^(B\d{3,})$/i);
  return m?.[1]?.toUpperCase() ?? null;
}

function decodeCanvas(ctx: CanvasRenderingContext2D, w: number, hgt: number): string | null {
  const data = ctx.getImageData(0, 0, w, hgt);
  return jsQR(data.data, w, hgt, { inversionAttempts: "dontInvert" })?.data ?? null;
}

export async function decodeQrFromPhoto(file: Blob): Promise<string | null> {
  const bmp = await toBitmap(file);
  // Try a couple of scales: jsQR prefers modules a few px wide.
  for (const edge of [1000, 1600, 700]) {
    const s = Math.min(1, edge / Math.max(bmp.width, bmp.height));
    const w = Math.round(bmp.width * s);
    const hgt = Math.round(bmp.height * s);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = hgt;
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    ctx.drawImage(bmp, 0, 0, w, hgt);
    const r = decodeCanvas(ctx, w, hgt);
    if (r) {
      bmp.close();
      return r;
    }
  }
  bmp.close();
  return null;
}

export const canScanLive = (): boolean => window.isSecureContext && !!navigator.mediaDevices?.getUserMedia;

interface Detector {
  detect(src: CanvasImageSource): Promise<{ rawValue: string }[]>;
}

/** Live camera QR scanning into `video`. Resolves with the first decode; call stop() to abort. */
export function scanLive(video: HTMLVideoElement): { result: Promise<string>; stop: () => void } {
  let stopped = false;
  let stream: MediaStream | null = null;
  const stop = () => {
    stopped = true;
    stream?.getTracks().forEach((t) => t.stop());
  };
  const result = (async () => {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment", width: { ideal: 1280 } },
      audio: false,
    });
    if (stopped) {
      stop();
      throw new Error("stopped");
    }
    video.srcObject = stream;
    video.setAttribute("playsinline", "");
    await video.play();
    const BD = (window as unknown as { BarcodeDetector?: new (o: object) => Detector }).BarcodeDetector;
    const detector = BD ? new BD({ formats: ["qr_code"] }) : null;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    while (!stopped) {
      await new Promise((r) => requestAnimationFrame(r));
      if (video.readyState < 2) continue;
      try {
        if (detector) {
          const codes = await detector.detect(video);
          if (codes[0]) return codes[0].rawValue;
        } else {
          const s = Math.min(1, 720 / video.videoWidth);
          canvas.width = Math.round(video.videoWidth * s);
          canvas.height = Math.round(video.videoHeight * s);
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          const r = decodeCanvas(ctx, canvas.width, canvas.height);
          if (r) return r;
        }
      } catch {
        /* transient frame errors */
      }
      await new Promise((r) => setTimeout(r, 120));
    }
    throw new Error("stopped");
  })().finally(stop);
  return { result, stop };
}
