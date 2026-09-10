/* Structured editors built from the same typed contracts enforced by the API. */
window.BlueprintForms = (() => {
  let sequence = 0;
  const title = key => key.replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase());
  function editor(host, schema, value, definitions = schema.$defs || {}) {
    host.replaceChildren();
    function field(raw, val, name, optional = false) {
      let spec = raw.$ref ? definitions[raw.$ref.split('/').pop()] : raw;
      const nullable = spec.anyOf?.some(s => s.type === 'null');
      if (spec.anyOf) spec = {...spec, ...spec.anyOf.find(s => s.type !== 'null')};
      const wrapper = document.createElement('div'); wrapper.className = 'blueprint-field';
      if (spec.type === 'object') {
        const box = document.createElement('fieldset'), legend = document.createElement('legend'); legend.textContent = title(name); box.append(legend); wrapper.append(box);
        const children = [];
        for (const [key, sub] of Object.entries(spec.properties || {})) {
          const child = field(sub, val?.[key], key, !(spec.required || []).includes(key)); box.append(child.node); children.push([key, child]);
        }
        return {node: wrapper, read: () => Object.fromEntries(children.map(([key, child]) => [key, child.read()]).filter(([,v]) => v !== undefined))};
      }
      if (spec.type === 'array') {
        const box = document.createElement('fieldset'), legend = document.createElement('legend'), rows = [];
        legend.textContent = title(name); box.append(legend); wrapper.append(box);
        const add = document.createElement('button'); add.type = 'button'; add.textContent = 'Add ' + title(name);
        function append(item) {
          const row = document.createElement('div'), child = field(spec.items, item, 'Item'), remove = document.createElement('button');
          row.className = 'blueprint-array-row'; remove.type = 'button'; remove.textContent = 'Remove';
          const entry = {row, child}; rows.push(entry); remove.onclick = () => {rows.splice(rows.indexOf(entry), 1); row.remove();};
          row.append(child.node, remove); box.insertBefore(row, add);
        }
        const enabled=document.createElement('input');enabled.type='checkbox';enabled.checked=val!==undefined;
        if(optional){const label=document.createElement('label');label.append(enabled,document.createTextNode('Override list (an empty list clears inherited values)'));box.append(label);}
        box.append(add); add.onclick = () => {enabled.checked=true;append(undefined);}; (val || spec.default || []).forEach(append);
        return {node: wrapper, read: () => optional && !enabled.checked ? undefined : rows.map(r => r.child.read())};
      }
      const label = document.createElement('label'); label.textContent = title(name);
      let input;
      if (spec.enum || spec.const !== undefined || spec.type === 'boolean') {
        input = document.createElement('select');
        const options = spec.enum ? [...spec.enum] : (spec.const !== undefined ? [spec.const] : [true, false]);
        if (nullable || optional && spec.default === undefined) options.unshift('');
        for (const option of options) {const el = document.createElement('option'); el.value = String(option); el.textContent = option === '' ? 'Inherit / unset' : String(option); input.append(el);}
      } else {
        input = document.createElement('input'); input.type = ['integer','number'].includes(spec.type) ? 'number' : 'text';
        if (input.type === 'number') {input.step = spec.type === 'integer' ? '1' : 'any'; if(spec.minimum !== undefined) input.min=spec.minimum; if(spec.exclusiveMinimum !== undefined) input.min=spec.exclusiveMinimum + (spec.type==='integer'?1:0.0001);}
        if(spec.maxLength) input.maxLength=spec.maxLength;
      }
      input.id = 'blueprint-field-' + ++sequence; label.htmlFor=input.id;
      input.value = val ?? spec.default ?? (spec.const !== undefined ? spec.const : ''); input.required = !optional && !nullable;
      wrapper.append(label, input);
      return {node: wrapper, read: () => {
        if (input.value === '') return nullable ? null : optional ? undefined : '';
        return spec.type === 'integer' || spec.type === 'number' ? Number(input.value) : spec.type === 'boolean' ? input.value === 'true' : input.value;
      }};
    }
    const root = field(schema, value, schema.title || 'Configuration'); host.append(root.node); return root;
  }
  return {editor};
})();
