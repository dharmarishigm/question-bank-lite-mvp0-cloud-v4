/* Public descriptions: escaped Markdown, with no executable HTML. */
window.renderPublicMarkdown = (() => {
function renderTables(lines) {
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const isRow = (s) => /^\s*\|.*\|\s*$/.test(s);
    if (isRow(lines[i]) && isRow(lines[i + 1] || '') && /^[\s|:-]+$/.test(lines[i + 1])) {
      const cells = (s) => s.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      const header = cells(lines[i]);
      const body = [];
      i += 2;
      while (i < lines.length && isRow(lines[i])) body.push(cells(lines[i++]));
      i--;
      out.push(
        '<table><thead><tr>' + header.map((c) => `<th>${c}</th>`).join('') + '</tr></thead><tbody>' +
        body.map((r) => '<tr>' + r.map((c) => `<td>${c}</td>`).join('') + '</tr>').join('') +
        '</tbody></table>'
      );
    } else {
      out.push(lines[i]);
    }
  }
  return out;
}

/** Markdown-lite + LaTeX: math segments are shielded from markdown rewriting. */
function renderMarkdownBlocks(text) {
  const lines = text.split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && /^[\s|:-]+$/.test(lines[i+1] || '') && (lines[i+1] || '').includes('|')) {
      const table = [lines[i++], lines[i++]];
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) table.push(lines[i++]);
      blocks.push(renderTables(table).join(''));
      continue;
    }
    if (/^#{1,6}\s+/.test(line)) {
      const match = line.match(/^(#{1,6})\s+(.*)$/);
      if (match) {
        const level = Math.min(6, match[1].length);
        blocks.push(`<h${level}>${match[2].trim()}</h${level}>`);
        i += 1;
        continue;
      }
    }
    if (/^>\s?/.test(line)) {
      const items = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        items.push(lines[i].replace(/^>\s?/, '').trim());
        i += 1;
      }
      blocks.push(`<blockquote>${items.join('<br>')}</blockquote>`);
      continue;
    }
    if (/^[-*]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(`<li>${lines[i].replace(/^[-*]\s+/, '').trim()}</li>`);
        i += 1;
      }
      blocks.push(`<ul>${items.join('')}</ul>`);
      continue;
    }
    if (/^\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i])) {
        items.push(`<li>${lines[i].replace(/^\d+\.\s+/, '').trim()}</li>`);
        i += 1;
      }
      blocks.push(`<ol>${items.join('')}</ol>`);
      continue;
    }
    const paragraph = [];
    while (i < lines.length && lines[i].trim() && !/^#{1,6}\s+/.test(lines[i]) && !/^>\s?/.test(lines[i]) && ! /^[-*]\s+/.test(lines[i]) && !/^\d+\.\s+/.test(lines[i])) {
      paragraph.push(lines[i].trim());
      i += 1;
    }
    if (paragraph.length) {
      blocks.push(`<p>${paragraph.join('<br>')}</p>`);
    }
  }
  return blocks.join('');
}

return source => {
  let text=String(source||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  text=text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,'<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g,'$1<em>$2</em>')
    .replace(/`([^`]+)`/g,'<code>$1</code>');
  return renderMarkdownBlocks(text);
};
})();
