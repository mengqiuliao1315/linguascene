"use client";

import { useMemo, type ReactNode } from "react";

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function safeUrl(raw: string): string | null {
  const url = raw.trim();
  if (/^https?:\/\//i.test(url)) return url;

  if (/^\/(?!\/)/.test(url)) return url;
  return null;
}

function inline(text: string): string {
  let html = escapeHtml(text);

  html = html.replace(/`([^`]+)`/g, (_m, code) => `<code>${code}</code>`);
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");

  html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (match, alt, url) => {
    const href = safeUrl(url);
    if (!href) return match;
    return `<img src="${href}" alt="${alt}" />`;
  });

  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, label, url) => {
    const href = safeUrl(url);
    if (!href) return match;
    return `<a href="${href}" target="_blank" rel="noreferrer noopener">${label}</a>`;
  });

  return html;
}

export function Markdown({ content }: { content: string }): ReactNode {
  const blocks = useMemo(() => {
    const lines = (content || "").replace(/\r\n/g, "\n").split("\n");
    const out: string[] = [];
    let listType: "ul" | "ol" | null = null;
    let paragraph: string[] = [];

    const flushParagraph = () => {
      if (paragraph.length) {
        out.push(`<p>${inline(paragraph.join(" "))}</p>`);
        paragraph = [];
      }
    };
    const closeList = () => {
      if (listType) {
        out.push(`</${listType}>`);
        listType = null;
      }
    };

    for (const raw of lines) {
      const line = raw.trimEnd();

      if (!line.trim()) {
        flushParagraph();
        closeList();
        continue;
      }

      const heading = /^(#{1,3})\s+(.*)$/.exec(line);
      if (heading) {
        flushParagraph();
        closeList();
        const level = heading[1].length + 1;
        out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
        continue;
      }

      if (/^(---|\*\*\*)$/.test(line.trim())) {
        flushParagraph();
        closeList();
        out.push("<hr />");
        continue;
      }

      const quote = /^>\s?(.*)$/.exec(line);
      if (quote) {
        flushParagraph();
        closeList();
        out.push(`<blockquote>${inline(quote[1])}</blockquote>`);
        continue;
      }

      const bullet = /^[-*]\s+(.*)$/.exec(line);
      if (bullet) {
        flushParagraph();
        if (listType !== "ul") {
          closeList();
          out.push("<ul>");
          listType = "ul";
        }
        out.push(`<li>${inline(bullet[1])}</li>`);
        continue;
      }

      const ordered = /^\d+\.\s+(.*)$/.exec(line);
      if (ordered) {
        flushParagraph();
        if (listType !== "ol") {
          closeList();
          out.push("<ol>");
          listType = "ol";
        }
        out.push(`<li>${inline(ordered[1])}</li>`);
        continue;
      }

      closeList();
      paragraph.push(line.trim());
    }

    flushParagraph();
    closeList();
    return out.join("");
  }, [content]);

  return (
    <div
      className="post-body space-y-3 text-[15px] leading-8 text-slate-700"
      dangerouslySetInnerHTML={{ __html: blocks }}
    />
  );
}
