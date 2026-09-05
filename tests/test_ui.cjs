const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const elements = new Map();
let optionIds = [];
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', checked: true, disabled: false, dataset: {}, handlers: {},
    classList: { add() {}, toggle() {} },
    addEventListener(name, fn) { this.handlers[name] = fn; },
    set innerHTML(value) {
      this.html = value;
      if (id === 'options-block') optionIds = [...value.matchAll(/id="(f-opt-\d+)"/g)].map(m => m[1]);
    },
    get innerHTML() { return this.html || ''; },
  });
  return elements.get(id);
}
const context = vm.createContext({
  document: { getElementById: element, querySelectorAll: () => optionIds.map(element) },
  window: {}, setTimeout: () => 0, clearTimeout() {}, URLSearchParams,
});
const source = fs.readFileSync('static/app.js', 'utf8');
// Load first-party UI functions without binding the application's global events.
vm.runInContext(source.slice(0, source.indexOf("document.querySelectorAll('textarea, #editor input, #editor select')")), context);
const run = code => vm.runInContext(code, context);
assert.equal(run("safeUrl('/uploads/q1-source-abcdef.png')"), '/uploads/q1-source-abcdef.png');
assert.equal(run("safeUrl('/uploads/q1-chemical_structure-abcdef.png')"), '/uploads/q1-chemical_structure-abcdef.png');
assert.equal(run("safeUrl('/uploads/../.env')"), '');
assert.equal(run("toHtml('[open](javascript:alert%281%29)')"), 'open');
assert.ok(run("toHtml('![source](/uploads/q1-source-abcd.png)')").includes('<img'));
assert.ok(run("toHtml('<script>alert(1)</script>')").includes('&lt;script&gt;'));
assert.equal(run("toHtml('$x^2$')"), '$x^2$');
run("fillForm({statement:'Example', options:['1','2','3','4','5','6','7','8'], qtype:'assertion_reason'})");
assert.equal(run('formValue().options.length'), 8);
assert.equal(run('formValue().options[7]'), '8');
assert.equal(run('formValue().qtype'), 'assertion_reason');
run('previewConfirmed = true');
element('f-opt-7').handlers.input();
assert.equal(run('previewConfirmed'), false);
assert.equal(element('btn-save').disabled, true);
const statement = element('f-statement').value;
run("insertSnippet(document.getElementById('f-statement'), undefined)");
assert.equal(element('f-statement').value, statement);
console.log('UI regression checks passed: asset URLs, markdown, option round-trip, preview invalidation, toolbar guards.');

const evidenceCard = run("cardHtml({id:1, statement:'Q', options:[], source_image:'/uploads/first.png', source_segments:[{page:1,image:'/uploads/first.png'},{page:2,image:'/uploads/second.png'}]}, false)");
assert.ok(evidenceCard.includes('/uploads/first.png'));
assert.ok(evidenceCard.includes('/uploads/second.png'));
assert.equal(run("cardHtml({id:1, statement:'Q', hide_source:true, source_segments:[{page:1,image:'/uploads/first.png'}]}, false)").includes('Complete original source evidence'), false);
console.log('All source segments render, and side-by-side review avoids duplicate evidence.');
