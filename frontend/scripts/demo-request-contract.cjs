// Capture la requête du vrai client TypeScript ; aucune requête réseau ni clé réelle.
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/lib/demo-api.ts'), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2022}}).outputText;
let payload;
const sandbox = { exports: {}, require: (name) => {
  if(name === '@/lib/incidents') return {reportIncident:()=>{}};
  if(name !== '@/lib/api') throw Error('Unexpected runtime import: '+name);
  return {API_BASE_URL:'https://api.example.test/api/v1'};
}, fetch: async (_url, init) => { payload=JSON.parse(init.body);return {ok:false,json:async()=>({detail:'contract capture'})};} };
vm.runInNewContext(compiled, sandbox);
sandbox.exports.streamPublicAsk({message:'Question de contrat technique',turnstileToken:'test-token'}, {
 onSources:()=>{}, onDelta:()=>{}, onDone:()=>{}, onError:()=>{},
}).then(()=>process.stdout.write(JSON.stringify(payload)));
