import ts from 'typescript';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Source labels only: never read requests, database rows, logs or authored workflow content.
export function collectUISources(root = fileURLToPath(new URL('../', import.meta.url))) {
  const keys = new Set();
  function value(node) {
    if (!node) return;
    if (ts.isStringLiteral(node)) keys.add(node.text);
    else if (ts.isConditionalExpression(node)) { value(node.whenTrue); value(node.whenFalse); }
    else if (ts.isBinaryExpression(node) && [ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.BarBarToken].includes(node.operatorToken.kind)) { value(node.left); value(node.right); }
    else if (ts.isElementAccessExpression(node)) value(node.expression);
    else if (ts.isObjectLiteralExpression(node)) for (const property of node.properties) if (ts.isPropertyAssignment(property)) value(property.initializer);
  }
  function walk(directory) {
    for (const name of readdirSync(directory)) {
      const file = path.join(directory, name);
      if (statSync(file).isDirectory()) { if (!['node_modules', '.next', 'locales'].includes(name)) walk(file); continue; }
      if (!/\.tsx?$/.test(name)) continue;
      const source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, name.endsWith('tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
      function visit(node) {
        if (ts.isCallExpression(node)) {
          const name = node.expression.getText(source);
          if (['t', 'browserT', 'node'].includes(name)) value(node.arguments[0]);
          if (name === 'setError' && node.arguments[0] && ts.isStringLiteral(node.arguments[0]) && /[A-Za-zÀ-ÿ]/.test(node.arguments[0].text)) value(node.arguments[0]);
        }
        if (ts.isPropertyAssignment(node) && ['label', 'title', 'subtitle', 'note', 'copy'].includes(node.name.getText(source))) value(node.initializer);
        if (ts.isVariableDeclaration(node) && ['eventLabels', 'messages', 'labels', 'descriptions', 'actions', 'editorActions'].includes(node.name.getText(source))) value(node.initializer);
        ts.forEachChild(node, visit);
      }
      visit(source);
    }
  }
  for (const directory of ['components', 'app', 'lib']) walk(path.join(root, directory));
  // Display names returned by helper functions and translated role ids.
  for (const key of ['Langue', 'Recherche Wikipédia', 'Admin', 'Builder', 'Operator', 'Viewer', 'Auditor', 'Dimanche', 'Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi']) keys.add(key);
  return [...keys].filter(Boolean).sort();
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.stdout.write(JSON.stringify(collectUISources(), null, 2) + '\n');
