(() => {
  "use strict";
  const input = document.querySelector("#journal-search");
  if (!input) return;
  const results = document.querySelector("#search-results");
  const original = document.querySelector("#archive-original");
  const status = document.querySelector("#search-status");
  const clear = document.querySelector("#clear-search");
  let indexPromise;
  let request = 0;
  const text = (tag, value, className) => {
    const el = document.createElement(tag);
    el.textContent = value;
    if (className) el.className = className;
    return el;
  };
  async function search() {
    const current = ++request;
    const query = input.value.trim().toLowerCase();
    clear.hidden = !query;
    if (!query) {
      results.hidden = true;
      original.hidden = false;
      status.textContent = "";
      return;
    }
    try {
      indexPromise ||= fetch("/search-index.json", { credentials: "omit" }).then(r => {
        if (!r.ok) throw new Error("Search unavailable");
        return r.json();
      });
      const index = await indexPromise;
      if (current !== request) return;
      const words = query.split(/\s+/);
      const matches = index.filter(item => words.every(w =>
        (item.title + " " + item.text).toLowerCase().includes(w)));
      results.replaceChildren();
      original.hidden = true;
      results.hidden = false;
      status.textContent = matches.length + (matches.length === 1 ? " entry found." : " entries found.");
      matches.forEach(item => {
        const row = text("article", "", "entry-row");
        row.append(text("div", item.date, "entry-date"));
        const content = document.createElement("div");
        content.append(text("p", item.label, "eyebrow"));
        const heading = document.createElement("h3");
        const link = text("a", item.title);
        link.setAttribute("href", item.path);
        heading.append(link);
        content.append(heading, text("p", item.excerpt, "excerpt"));
        row.append(content);
        results.append(row);
      });
      if (!matches.length) results.append(text("p", "No entries match yet. Try a different word or browse the archive.", "no-results"));
    } catch (_) {
      indexPromise = undefined;
      status.textContent = "Search is temporarily unavailable. All entries are listed below.";
      original.hidden = false;
      results.hidden = true;
    }
  }
  input.addEventListener("input", search);
  input.form.addEventListener("submit", event => { event.preventDefault(); search(); });
  clear.addEventListener("click", () => { input.value = ""; search(); input.focus(); });
})();
