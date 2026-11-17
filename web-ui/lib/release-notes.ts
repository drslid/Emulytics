export type ReleaseNoteBlock =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph" | "code"; text: string }
  | { kind: "list"; start: number | null; items: string[] };

type ReleaseNoteInline =
  | { kind: "text" | "code" | "strong"; text: string }
  | { kind: "link"; text: string; href: string };

export function releaseNoteBlocks(notes: string): ReleaseNoteBlock[] {
  const blocks: ReleaseNoteBlock[] = [];
  const paragraph: string[] = [];
  let list: Extract<ReleaseNoteBlock, { kind: "list" }> | undefined;
  let fence: { marker: string; lines: string[] } | undefined;

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", text: paragraph.splice(0).join(" ") });
  };

  for (const line of notes.split(/\r?\n/)) {
    const marker = line.match(/^ {0,3}(`{3,}|~{3,})/);
    if (fence) {
      if (marker?.[1].startsWith(fence.marker) && !line.slice(marker[0].length).trim()) {
        blocks.push({ kind: "code", text: fence.lines.join("\n") });
        fence = undefined;
      } else {
        fence.lines.push(line);
      }
      continue;
    }
    const heading = line.match(/^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$/);
    const item = line.match(/^ {0,3}([-+*]|\d{1,9}[.)])[ \t]+(.+)$/);
    if (marker || heading || item || !line.trim()) flushParagraph();
    if (item) {
      const start = item[1].length > 1 ? Number.parseInt(item[1], 10) : null;
      if (!list || (list.start === null) !== (start === null)) {
        list = { kind: "list", start, items: [] };
        blocks.push(list);
      }
      list.items.push(item[2]);
      continue;
    }
    list = undefined;
    if (marker) fence = { marker: marker[1], lines: [] };
    else if (heading) blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] });
    else if (line.trim()) paragraph.push(line.trim());
  }
  flushParagraph();
  if (fence) blocks.push({ kind: "code", text: fence.lines.join("\n") });
  return blocks;
}

function safeLink(value: string): string | undefined {
  if (!/^https:\/\//i.test(value)) return;
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && !url.username && !url.password) return url.href;
  } catch {
    return;
  }
}

export function releaseNoteInline(text: string): ReleaseNoteInline[] {
  const result: ReleaseNoteInline[] = [];
  const tokens = /(!?)\[([^\]\r\n]{1,512})\]\(([^\s()]{1,2048})(?:[ \t]+"[^"\r\n]*")?\)|`([^`]+)`|\*\*([^*\r\n]+)\*\*/g;
  let offset = 0;
  for (const match of text.matchAll(tokens)) {
    const [source, image, label, url, code, strong] = match;
    const index = match.index ?? offset;
    if (index > offset) result.push({ kind: "text", text: text.slice(offset, index) });
    if (label !== undefined) {
      const href = image ? undefined : safeLink(url);
      result.push(href ? { kind: "link", href, text: label } : { kind: "text", text: label });
    } else if (code !== undefined) result.push({ kind: "code", text: code });
    else result.push({ kind: "strong", text: strong });
    offset = index + source.length;
  }
  if (offset < text.length) result.push({ kind: "text", text: text.slice(offset) });
  return result;
}
