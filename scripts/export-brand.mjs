import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const source = path.join(root, "design/brand/emulytix-master.png");
const publicRoot = path.join(root, "web-ui/public");
const temporary = mkdtempSync(path.join(tmpdir(), "emulytix-brand-"));
const run = (command, args) => execFileSync(command, args, { encoding: "utf8" }).trim();
const convert = (...args) => run("convert", args);
const background = "#f8fafd";

mkdirSync(path.join(publicRoot, "brand"), { recursive: true });
mkdirSync(path.join(publicRoot, "icons"), { recursive: true });

try {
  // Fit the generated artwork optically, leaving its alpha and artwork unchanged.
  const bounds = convert(source, "-alpha", "extract", "-threshold", "50%", "-format", "%@", "info:");
  const dimensions = run("identify", ["-format", "%w %h", source]).split(" ").map(Number);
  const match = /^(\d+)x(\d+)\+(\d+)\+(\d+)$/.exec(bounds);
  if (!match) throw new Error("Cannot measure the source artwork");
  const [, width, height, x, y] = match.map(Number);
  const left = Math.max(0, x - 8), top = Math.max(0, y - 8);
  const crop = `${Math.min(dimensions[0] - left, width + 16)}x${Math.min(dimensions[1] - top, height + 16)}+${left}+${top}`;
  const artwork = path.join(temporary, "artwork.png");
  convert(source, "-crop", crop, "+repage", "-strip", artwork);

  function icon(file, size, markSize, opaque) {
    convert(artwork, "-filter", "Lanczos", "-resize", `${markSize}x${markSize}`,
      "-gravity", "center", "-background", opaque ? background : "none", "-extent", `${size}x${size}`,
      ...(opaque ? ["-alpha", "remove", "-alpha", "off"] : []), "-strip", path.join(publicRoot, file));
  }

  icon("brand/emulytix-mark.png", 256, 240, false);
  for (const size of [16, 32, 48]) icon(`icons/favicon-${size}.png`, size, size - 2, false);
  convert(...[16, 32, 48].map(size => path.join(publicRoot, `icons/favicon-${size}.png`)), path.join(publicRoot, "favicon.ico"));
  icon("apple-touch-icon.png", 180, 142, true);
  icon("icons/icon-192.png", 192, 152, true);
  icon("icons/icon-512.png", 512, 408, true);
  icon("icons/maskable-512.png", 512, 312, true);
  const outside = Number(convert(path.join(publicRoot, "icons/maskable-512.png"),
    "-alpha", "on", "-fuzz", "1%", "-transparent", background, "-alpha", "extract",
    "-fill", "black", "-draw", "circle 256,256 460.8,256", "-format", "%[fx:maxima]", "info:"));
  if (outside !== 0) throw new Error("The maskable mark extends outside the central safe circle");
  console.log("Emulytix brand exports generated: transparent mark, 3-frame ICO, Apple and manifest icons.");
} finally {
  // This private temporary directory is created and owned by this process.
  rmSync(temporary, { recursive: true, force: true });
}
