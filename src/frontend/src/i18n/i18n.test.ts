import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
import { catalogs, DEFAULT_LOCALE, resolveLocale, SUPPORTED_LOCALES, translate } from "./catalog";
import { getLocalStorage, LOCALE_STORAGE_KEY, persistLocale, readStoredLocale, StorageHost, StorageLike } from "./provider";

test("all locale catalogs have exact deep-key parity", () => {
  const expected = Object.keys(catalogs[DEFAULT_LOCALE]).sort();
  for (const locale of SUPPORTED_LOCALES) assert.deepEqual(Object.keys(catalogs[locale]).sort(), expected, locale);
});

test("locale resolution accepts exact supported values and otherwise falls back to zh-TW", () => {
  for (const locale of SUPPORTED_LOCALES) assert.equal(resolveLocale(locale), locale);
  for (const value of [undefined, null, "", "zh", "zh-tw", "en-US", "fr", 7]) assert.equal(resolveLocale(value), DEFAULT_LOCALE);
  assert.equal(translate("unknown", "common.cancel"), catalogs[DEFAULT_LOCALE]["common.cancel"]);
});

test("storage reads, writes, and fails safely when unavailable or corrupt", () => {
  const values = new Map<string, string>();
  const storage: StorageLike = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => { values.set(key, value); } };
  assert.equal(readStoredLocale(storage), DEFAULT_LOCALE);
  assert.equal(persistLocale(storage, "en"), true);
  assert.equal(values.get(LOCALE_STORAGE_KEY), "en");
  assert.equal(readStoredLocale(storage), "en");
  values.set(LOCALE_STORAGE_KEY, "{corrupt");
  assert.equal(readStoredLocale(storage), DEFAULT_LOCALE);
  const broken: StorageLike = { getItem: () => { throw new Error("unavailable"); }, setItem: () => { throw new Error("quota"); } };
  assert.equal(readStoredLocale(broken), DEFAULT_LOCALE);
  assert.equal(persistLocale(broken, "zh-CN"), false);
  assert.equal(readStoredLocale(null), DEFAULT_LOCALE);
});

test("localStorage property access itself is guarded against SecurityError", () => {
  const host = Object.defineProperty({}, "localStorage", { get() { throw new DOMException("denied", "SecurityError"); } }) as StorageHost;
  assert.equal(getLocalStorage(host), null);
  assert.equal(readStoredLocale(getLocalStorage(host)), DEFAULT_LOCALE);
  assert.equal(persistLocale(getLocalStorage(host), "en"), false);
  assert.equal(getLocalStorage(null), null);
});

type StringLeaf = { text: string; node: ts.Node };

function visitStringLeaves(node: ts.Node | undefined, visit: (leaf: StringLeaf) => void): void {
  if (!node) return;
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
    visit({ text: node.text, node });
    return;
  }
  if (ts.isParenthesizedExpression(node)) {
    visitStringLeaves(node.expression, visit);
    return;
  }
  if (ts.isConditionalExpression(node)) {
    visitStringLeaves(node.whenTrue, visit);
    visitStringLeaves(node.whenFalse, visit);
    return;
  }
  if (ts.isBinaryExpression(node)) {
    const operator = node.operatorToken.kind;
    if (operator === ts.SyntaxKind.AmpersandAmpersandToken) visitStringLeaves(node.right, visit);
    else if ([ts.SyntaxKind.BarBarToken, ts.SyntaxKind.QuestionQuestionToken, ts.SyntaxKind.PlusToken].includes(operator)) {
      visitStringLeaves(node.left, visit);
      visitStringLeaves(node.right, visit);
    }
    return;
  }
  if (ts.isArrayLiteralExpression(node)) {
    for (const element of node.elements) visitStringLeaves(ts.isSpreadElement(element) ? element.expression : element, visit);
    return;
  }
  if (ts.isObjectLiteralExpression(node)) {
    for (const property of node.properties) {
      if (ts.isPropertyAssignment(property)) visitStringLeaves(property.initializer, visit);
      else if (ts.isSpreadAssignment(property)) visitStringLeaves(property.expression, visit);
    }
    return;
  }
  if (ts.isTemplateExpression(node)) {
    if (node.head.text) visit({ text: node.head.text, node: node.head });
    for (const span of node.templateSpans) {
      visitStringLeaves(span.expression, visit);
      if (span.literal.text) visit({ text: span.literal.text, node: span.literal });
    }
  }
}

function scanPageUserFacingStrings(sourceText: string, file = "page.tsx"): string[] {
  const source = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const violations: string[] = [];
  const tagName = (element: ts.JsxElement | ts.JsxSelfClosingElement): string =>
    (ts.isJsxElement(element) ? element.openingElement.tagName : element.tagName).getText(source);
  const attributes = (element: ts.JsxElement | ts.JsxSelfClosingElement) =>
    ts.isJsxElement(element) ? element.openingElement.attributes.properties : element.attributes.properties;
  const stringAttribute = (element: ts.JsxElement | ts.JsxSelfClosingElement, name: string): string | null => {
    const attribute = attributes(element).find((item): item is ts.JsxAttribute => ts.isJsxAttribute(item) && item.name.getText(source) === name);
    return attribute?.initializer && ts.isStringLiteral(attribute.initializer) ? attribute.initializer.text : null;
  };
  const elementOf = (node: ts.Node): ts.JsxElement | ts.JsxSelfClosingElement | null => {
    let current: ts.Node | undefined = node.parent;
    while (current) {
      if (ts.isJsxElement(current) || ts.isJsxSelfClosingElement(current)) return current;
      current = current.parent;
    }
    return null;
  };
  const allowedJsxText = (node: ts.JsxText, text: string): boolean => {
    const element = elementOf(node);
    if (!element) return false;
    const tag = tagName(element);
    const testId = stringAttribute(element, "data-testid");
    if (tag === "h1" && testId === "growthmap-title" && text === "🌳 GrowthMap") return true;
    if (tag === "button" && testId === "database-workspace-button" && text === "🗄️ DB") return true;
    if (tag === "button" && testId === "desktop-settings-button" && text === "⚙️ LLM") return true;
    if (tag === "button" && ["⌨️", "×", "✕"].includes(text)) return true;
    if (tag === "button" && text === "🗃️") return true;
    if (tag === "span" && ["(", ")"].includes(text)) return true;
    return false;
  };
  const isArchivedOptionFormat = (expression: ts.Node, text: string): boolean => {
    const element = elementOf(expression);
    return Boolean(element && tagName(element) === "option" && (text === "🗄 " || text === ""));
  };
  const rejectLeaves = (node: ts.Node | undefined, context: string, allow?: (leaf: StringLeaf) => boolean) =>
    visitStringLeaves(node, (leaf) => { if (!allow?.(leaf)) violations.push(`${context}:${leaf.text}`); });

  const textProps = new Set(["aria-label", "title", "placeholder", "alt"]);
  const userFacingCalls = new Set(["confirm", "setToast"]);
  function walk(node: ts.Node) {
    if (ts.isJsxText(node)) {
      const text = node.text.trim();
      if (text && !allowedJsxText(node, text)) violations.push(`JSX:${text}`);
    }
    if (ts.isJsxAttribute(node) && textProps.has(node.name.getText(source))) {
      if (node.initializer && ts.isStringLiteral(node.initializer)) violations.push(`prop:${node.name.getText(source)}:${node.initializer.text}`);
      else if (node.initializer && ts.isJsxExpression(node.initializer))
        rejectLeaves(node.initializer.expression, `prop:${node.name.getText(source)}`);
    }
    if (ts.isJsxExpression(node) && node.expression && (ts.isJsxElement(node.parent) || ts.isJsxFragment(node.parent)))
      rejectLeaves(node.expression, "render", (leaf) => isArchivedOptionFormat(node.expression!, leaf.text));
    if (ts.isCallExpression(node) && userFacingCalls.has(node.expression.getText(source)))
      rejectLeaves(node.arguments[0], `call:${node.expression.getText(source)}`);
    if (ts.isNewExpression(node) && node.expression.getText(source) === "Error")
      rejectLeaves(node.arguments?.[0], "new Error");
    ts.forEachChild(node, walk);
  }
  walk(source);
  return violations;
}

test("page has no bare user-facing strings outside contextual brand/format/keyboard allowances", () => {
  const file = path.resolve(__dirname, "../app/page.tsx");
  const sourceText = fs.readFileSync(file, "utf8");
  assert.deepEqual(scanPageUserFacingStrings(sourceText, file), []);

  const source = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const literalText = (node: ts.Node | undefined): string | null =>
    node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) ? node.text : null;
  function collectShortcutArrays(node: ts.Node): ts.ArrayLiteralExpression[] {
    const found: ts.ArrayLiteralExpression[] = [];
    if (ts.isArrayLiteralExpression(node) && node.elements.some((item) => ts.isArrayLiteralExpression(item) && literalText(item.elements[0]) === "Esc")) found.push(node);
    ts.forEachChild(node, (child) => found.push(...collectShortcutArrays(child)));
    return found;
  }
  const shortcutArray = source.statements.flatMap(collectShortcutArrays);
  assert.equal(shortcutArray.length, 1, "expected one contextual keyboard-shortcut table");
  assert.deepEqual(shortcutArray[0].elements.map((row) => ts.isArrayLiteralExpression(row) ? literalText(row.elements[0]) : null),
    ["Esc", "Delete / Backspace", "E", "D", "Ctrl+Z"]);
  for (const row of shortcutArray[0].elements) {
    assert.ok(ts.isArrayLiteralExpression(row) && ts.isCallExpression(row.elements[1]) && row.elements[1].expression.getText(source) === "t",
      "shortcut descriptions must be translated, while only fixed keyboard tokens are allowed");
  }
});

test("scanner rejects English and CJK conditional leaves in props and user-facing calls", () => {
  const fixture = `
    const view = <button title={ready ? "English title" : "中文標題"} aria-label={(ready && "English label") || "中文標籤"} />;
    confirm(ready ? "English confirmation" : "中文確認");
    setToast((ready ? "English toast" : "中文提示"));
    throw new Error(ready ? ` + "`English ${code}`" + ` : ` + "`中文 ${code}`" + `);
  `;
  const violations = scanPageUserFacingStrings(fixture, "negative-fixture.tsx");
  for (const expected of [
    "prop:title:English title", "prop:title:中文標題", "prop:aria-label:English label", "prop:aria-label:中文標籤",
    "call:confirm:English confirmation", "call:confirm:中文確認", "call:setToast:English toast", "call:setToast:中文提示",
    "new Error:English ", "new Error:中文 ",
  ]) assert.ok(violations.includes(expected), `missing scanner violation: ${expected}\n${violations.join("\n")}`);
});
