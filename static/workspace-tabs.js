/* Keep form nodes mounted so switching sections preserves unsaved edits. */
window.WorkspaceTabs = {
  mount(host, groups, key) {
    const sections = groups.map(([label, nodes]) => ({label, nodes: nodes.filter(Boolean)})).filter(s => s.nodes.length);
    if (sections.length < 2) return;
    const nav = document.createElement('nav'); nav.className = 'workspace-tabs'; nav.setAttribute('aria-label', 'Workspace sections');
    const select = index => {
      host.dataset.workspaceSection = sections[index].label;
      sections.forEach((s, i) => { s.nodes.forEach(n => { n.hidden = i !== index; }); nav.children[i].setAttribute('aria-pressed', String(i === index)); });
      window.dispatchEvent(new Event('resize'));
    };
    sections.forEach((s, i) => { const b = document.createElement('button'); b.type = 'button'; b.textContent = s.label; b.onclick = () => select(i); nav.append(b); });
    const heading=host.querySelector('.page-header');
    if(heading)heading.after(nav);else sections[0].nodes[0].before(nav);
    const previous = host.dataset.workspaceKey === key ? host.dataset.workspaceSection : '';
    host.dataset.workspaceKey = key;
    select(Math.max(0, sections.findIndex(s => s.label === previous)));
  }
};
