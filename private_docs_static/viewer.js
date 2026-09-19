(function () {
  "use strict";

  var main = document.getElementById("content");
  var toc = document.getElementById("toc");
  var name = main.dataset.doc;

  function fail(message) {
    main.innerHTML = "";
    var p = document.createElement("p");
    p.className = "error";
    p.textContent = message;
    main.appendChild(p);
  }

  // Headings get ids so that in-document links and the table of contents work.
  function slugify(text) {
    return text.trim().toLowerCase()
      .replace(/[^\p{L}\p{N}\s-]/gu, "")
      .replace(/\s+/g, "-");
  }

  function addHeadingIds() {
    var used = {};
    main.querySelectorAll("h1, h2, h3, h4").forEach(function (h) {
      var base = slugify(h.textContent) || "section";
      var id = base;
      var n = 1;
      while (used[id]) { n += 1; id = base + "-" + n; }
      used[id] = true;
      h.id = id;
    });
  }

  function buildToc() {
    var heads = main.querySelectorAll("h2, h3");
    if (heads.length < 3) { toc.hidden = true; return; }
    var list = document.createElement("ul");
    heads.forEach(function (h) {
      var li = document.createElement("li");
      li.className = h.tagName === "H3" ? "sub" : "top";
      var a = document.createElement("a");
      a.href = "#" + h.id;
      a.textContent = h.textContent;
      li.appendChild(a);
      list.appendChild(li);
    });
    var title = document.createElement("strong");
    title.textContent = "목차";
    toc.appendChild(title);
    toc.appendChild(list);
  }

  // Links to other documents stay inside this server; anything not published here is shown as plain text.
  function rewriteLinks(known) {
    main.querySelectorAll("a[href]").forEach(function (a) {
      var href = a.getAttribute("href");
      if (href.charAt(0) === "#") { return; }
      if (/^https?:\/\//i.test(href)) {
        a.rel = "noopener noreferrer";
        a.target = "_blank";
        return;
      }
      var m = href.match(/^(?:\.\/)?([^#?\/]+\.md)(#.*)?$/);
      if (m) {
        var target = decodeURIComponent(m[1]);
        if (known[target]) {
          a.setAttribute("href", "/doc/" + encodeURIComponent(target) + (m[2] || ""));
          return;
        }
      }
      var span = document.createElement("span");
      span.className = "unpublished";
      span.title = "이 서버에 공개되지 않은 문서";
      span.textContent = a.textContent;
      a.replaceWith(span);
    });
  }

  function wrapTables() {
    main.querySelectorAll("table").forEach(function (table) {
      var wrap = document.createElement("div");
      wrap.className = "tablewrap";
      table.parentNode.insertBefore(wrap, table);
      wrap.appendChild(table);
    });
  }

  Promise.all([
    fetch("/raw/" + encodeURIComponent(name)),
    fetch("/api/docs")
  ]).then(function (responses) {
    if (!responses[0].ok) { throw new Error("문서를 불러오지 못했다 (HTTP " + responses[0].status + ")"); }
    return Promise.all([responses[0].text(), responses[1].ok ? responses[1].json() : []]);
  }).then(function (result) {
    var known = {};
    result[1].forEach(function (d) { known[d.name] = true; });

    // Remote images are dropped before the HTML is inserted, so the browser never even tries to load them
    // (the Content-Security-Policy would block them too). The alt text explains the gap.
    DOMPurify.addHook("afterSanitizeAttributes", function (node) {
      if (node.tagName !== "IMG") { return; }
      var src = node.getAttribute("src") || "";
      if (/^(https?:)?\/\//i.test(src)) {
        node.removeAttribute("src");
        node.setAttribute("alt", "[외부 이미지 차단] " + (node.getAttribute("alt") || ""));
      }
    });

    var dirty = marked.parse(result[0], { gfm: true, breaks: false });
    main.innerHTML = DOMPurify.sanitize(dirty, {
      FORBID_ATTR: ["style"],
      FORBID_TAGS: ["style", "form", "input", "button", "iframe", "object", "embed"]
    });

    addHeadingIds();
    rewriteLinks(known);
    wrapTables();
    buildToc();

    var h1 = main.querySelector("h1");
    if (h1) { document.title = h1.textContent; }
    if (location.hash) {
      var target = document.getElementById(decodeURIComponent(location.hash.slice(1)));
      if (target) { target.scrollIntoView(); }
    }
  }).catch(function (err) {
    fail(err.message || "문서를 표시하지 못했다");
  });
})();
