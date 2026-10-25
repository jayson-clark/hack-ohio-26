// Hash routes, so the page works from any static host and links survive reloads:
//   #/            overview          #/digest      since you last looked
//   #/questions   open questions    #/claims      who's editing what
//   #/github      PRs and issues    #/activity    everything agents did
//   #/knowledge?kind=&tag=          #/tags        #/e/<id>   one entry
//   #/c/<channel>                   #/c/<channel>/t/<id>     a thread
//   #/u/<person>

import { useSyncExternalStore } from "react";

export interface Route {
  view: string;
  arg: string;
  thread: number | null;
  params: URLSearchParams;
  hash: string;
}

function parse(hash: string): Route {
  const h = hash.replace(/^#\/?/, "");
  const [path, query = ""] = h.split("?");
  const parts = path.split("/").map((p) => decodeURIComponent(p));
  const view = parts[0] || "overview";
  const thread = view === "c" && parts[2] === "t" ? Number(parts[3]) || null : null;
  return { view, arg: parts[1] || "", thread, params: new URLSearchParams(query), hash };
}

let current = parse(location.hash);
const listeners = new Set<() => void>();
window.addEventListener("hashchange", () => {
  current = parse(location.hash);
  listeners.forEach((l) => l());
});

export function useRoute() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => current,
  );
}
export const getRoute = () => current;

export function go(hash: string) {
  if (location.hash !== hash) location.hash = hash;
}

export const hrefs = {
  channel: (c: string) => `#/c/${encodeURIComponent(c)}`,
  thread: (c: string, id: number) => `#/c/${encodeURIComponent(c)}/t/${id}`,
  entry: (id: number) => `#/e/${id}`,
  user: (u: string) => `#/u/${encodeURIComponent(u)}`,
  tag: (t: string) => `#/knowledge?tag=${encodeURIComponent(t)}`,
};
