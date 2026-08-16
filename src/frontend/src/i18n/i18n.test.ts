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

test("locale resolution accepts exact supported values and otherwise falls back to English", () => {
  for (const locale of SUPPORTED_LOCALES) assert.equal(resolveLocale(locale), locale);
  for (const value of [undefined, null, "", "zh", "zh-tw", "en-US", "fr", 7]) assert.equal(resolveLocale(value), DEFAULT_LOCALE);
  assert.equal(translate("unknown", "common.cancel"), catalogs[DEFAULT_LOCALE]["common.cancel"]);
});

test("English and Simplified Chinese catalogs do not inherit known Traditional-Chinese chrome", () => {
  assert.equal(DEFAULT_LOCALE, "en");
  const traditionalChrome = /專案|選擇|節點|資料庫|匯入|匯出|復原|啟用|授權|封存|歷史|建立|刪除|儲存|設定|內容|對話|主線|搜尋/;
  for (const locale of ["en", "zh-CN"] as const) {
    const leaks = Object.entries(catalogs[locale]).filter(([, value]) => traditionalChrome.test(value));
    assert.deepEqual(leaks, [], `${locale} inherited zh-TW chrome: ${JSON.stringify(leaks)}`);
  }
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

test("activation is directly reachable before a project exists", () => {
  const file = path.resolve(__dirname, "../app/page.tsx");
  const sourceText = fs.readFileSync(file, "utf8");
  const source = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let panel: ts.JsxElement | undefined;
  function walk(node: ts.Node) {
    if (ts.isJsxElement(node) && node.openingElement.attributes.properties.some((item) =>
      ts.isJsxAttribute(item) && item.name.getText(source) === "data-testid" &&
      item.initializer && ts.isStringLiteral(item.initializer) && item.initializer.text === "activation-panel")) panel = node;
    ts.forEachChild(node, walk);
  }
  walk(source);
  assert.ok(panel, "activation panel must be rendered");
  let ancestor: ts.Node | undefined = panel?.parent;
  while (ancestor) {
    if (ts.isJsxExpression(ancestor) && ancestor.expression?.getText(source).includes("currentProject"))
      assert.fail("activation must not depend on currentProject or the More menu");
    ancestor = ancestor.parent;
  }
});

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

function scanProductionHan(sourceText: string, file: string): string[] {
  const source = ts.createSourceFile(file, sourceText, ts.ScriptTarget.Latest, true, file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const violations: string[] = [];
  const approvedModule = "@/i18n/ui";
  const scopes = new Map<ts.Node, Map<string, ts.Declaration>>();
  const scopeOf = (node: ts.Node): ts.Node => {
    let current: ts.Node | undefined = node.parent;
    while (current && !ts.isSourceFile(current) && !ts.isBlock(current) && !ts.isFunctionLike(current)) current = current.parent;
    return current ?? source;
  };
  const bind = (scope: ts.Node, name: string, declaration: ts.Declaration) => {
    const bindings = scopes.get(scope) ?? new Map<string, ts.Declaration>();
    bindings.set(name, declaration); scopes.set(scope, bindings);
  };
  const collectBindings = (node: ts.Node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier) && node.importClause?.namedBindings && ts.isNamedImports(node.importClause.namedBindings)) {
      for (const specifier of node.importClause.namedBindings.elements) bind(source, specifier.name.text, specifier);
    } else if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) bind(scopeOf(node), node.name.text, node);
    else if (ts.isParameter(node) && ts.isIdentifier(node.name)) bind(scopeOf(node), node.name.text, node);
    else if (ts.isFunctionDeclaration(node) && node.name) bind(scopeOf(node), node.name.text, node);
    ts.forEachChild(node, collectBindings);
  };
  collectBindings(source);
  const resolve = (identifier: ts.Identifier): ts.Declaration | undefined => {
    let current: ts.Node | undefined = identifier;
    while (current) {
      if (ts.isSourceFile(current) || ts.isBlock(current) || ts.isFunctionLike(current)) {
        const declaration = scopes.get(current)?.get(identifier.text);
        if (declaration) return declaration;
      }
      current = current.parent;
    }
    return undefined;
  };
  const importedExport = (declaration: ts.Declaration | undefined, exportName: string): boolean => {
    if (!declaration || !ts.isImportSpecifier(declaration)) return false;
    const imported = declaration.propertyName?.text ?? declaration.name.text;
    const importDeclaration = declaration.parent.parent.parent;
    return imported === exportName && ts.isImportDeclaration(importDeclaration) && ts.isStringLiteral(importDeclaration.moduleSpecifier)
      && importDeclaration.moduleSpecifier.text === approvedModule;
  };
  const unwrap = (expression: ts.Expression): ts.Expression => {
    while (ts.isParenthesizedExpression(expression)) expression = expression.expression;
    return expression;
  };
  const propertyName = (name: ts.PropertyName): string | null => {
    if (ts.isIdentifier(name) || ts.isStringLiteral(name)) return name.text;
    return null;
  };
  const exactLocaleObject = (expression: ts.Expression, values?: readonly string[]): boolean => {
    expression = unwrap(expression);
    if (!ts.isObjectLiteralExpression(expression) || expression.properties.length !== 3) return false;
    const expected = ["zh-TW", "zh-CN", "en"];
    return expression.properties.every((property, index) => {
      if (ts.isSpreadAssignment(property) || !ts.isPropertyAssignment(property) && !ts.isShorthandPropertyAssignment(property)) return false;
      if (propertyName(property.name) !== expected[index]) return false;
      if (!values) return ts.isPropertyAssignment(property) && isLocalizationExpression(property.initializer);
      const value = ts.isShorthandPropertyAssignment(property) ? property.name : unwrap(property.initializer);
      return ts.isIdentifier(value) && value.text === values[index];
    });
  };
  const isLocalizationExpression = (expression: ts.Expression): boolean => {
    expression = unwrap(expression);
    return ts.isStringLiteralLike(expression) || ts.isTemplateExpression(expression);
  };
  const approvedTripletWrapper = (declaration: ts.Declaration | undefined): boolean => {
    if (!declaration || !ts.isVariableDeclaration(declaration) || !ts.isIdentifier(declaration.name) || !["u", "m", "ui"].includes(declaration.name.text) || !declaration.initializer) return false;
    let initializer = unwrap(declaration.initializer);
    if (ts.isCallExpression(initializer) && ts.isIdentifier(initializer.expression) && initializer.expression.text === "useCallback" && initializer.arguments.length >= 1)
      initializer = unwrap(initializer.arguments[0]);
    if (!ts.isArrowFunction(initializer) && !ts.isFunctionExpression(initializer) || initializer.parameters.length !== 3 || initializer.parameters.some(parameter => !ts.isIdentifier(parameter.name))) return false;
    const body = ts.isBlock(initializer.body) ? initializer.body.statements.length === 1 && ts.isReturnStatement(initializer.body.statements[0]) ? initializer.body.statements[0].expression : undefined : initializer.body;
    if (!body) return false;
    const call = unwrap(body);
    if (!ts.isCallExpression(call) || !ts.isIdentifier(call.expression)) return false;
    const values = initializer.parameters.map(parameter => (parameter.name as ts.Identifier).text);
    if (importedExport(resolve(call.expression), "msg")) return call.arguments.length === 2 && exactLocaleObject(call.arguments[1], values);
    return importedExport(resolve(call.expression), "activeMsg") && call.arguments.length === 1 && exactLocaleObject(call.arguments[0], values);
  };
  const approvedLocalizedCall = (node: ts.CallExpression): boolean => {
    if (!ts.isIdentifier(node.expression)) return false;
    const declaration = resolve(node.expression);
    if (importedExport(declaration, "activeMsg")) return node.arguments.length === 1 && exactLocaleObject(node.arguments[0]);
    return approvedTripletWrapper(declaration) && node.arguments.length === 3 && node.arguments.every(isLocalizationExpression);
  };
  const visit = (node: ts.Node, localized = false) => {
    const inside = localized || (ts.isCallExpression(node) && approvedLocalizedCall(node));
    if (!inside && (ts.isStringLiteralLike(node) || ts.isTemplateLiteralToken(node)) && /[\u3400-\u9fff]/u.test(node.text)) violations.push(`${file}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}:${node.text}`);
    if (!inside && ts.isJsxText(node) && /[\u3400-\u9fff]/u.test(node.text)) violations.push(`${file}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}:${node.text.trim()}`);
    ts.forEachChild(node, child => visit(child, inside));
  }; visit(source); return violations;
}
test("production components, stores, and libraries have no unlocalized Han UI literals", () => {
  const roots = ["../components", "../stores", "../lib"].map(dir => path.resolve(__dirname, dir)); const files: string[] = [];
  const walk = (dir: string) => { for (const entry of fs.readdirSync(dir, { withFileTypes: true })) { const full = path.join(dir, entry.name); if (entry.isDirectory()) walk(full); else if (/\.(tsx?|jsx?)$/.test(entry.name) && !/\.test\./.test(entry.name)) files.push(full); } }; roots.forEach(walk);
  assert.deepEqual(files.flatMap(file => scanProductionHan(fs.readFileSync(file, "utf8"), file)), []);
});
test("broad Han guard catches JSX, templates, and conditional UI leakage", () => {
  const fixture = 'const x=<div>繁體外洩</div>; const y=`錯誤：${code}`; const z=ok ? "設定" : "內容";';
  assert.equal(scanProductionHan(fixture, "negative.tsx").length, 4);
});

test("production Han guard resolves approved helper bindings and requires exact call shapes", () => {
  const valid = `
    import { msg, activeMsg } from "@/i18n/ui";
    const locale = "en";
    const u = (tw: string, cn: string, en: string) => msg(locale, {"zh-TW": tw, "zh-CN": cn, en});
    const m = (tw: string, cn: string, en: string) => msg(locale, {"zh-TW": tw, "zh-CN": cn, en});
    const ui = (tw: string, cn: string, en: string) => activeMsg({"zh-TW": tw, "zh-CN": cn, en});
    export const view = <>{u("設定", "设置", "Settings")}{m("錯誤", "错误", "Error")}{ui("內容", "内容", "Content")}{activeMsg({"zh-TW":"儲存","zh-CN":"保存",en:"Save"})}</>;
  `;
  assert.deepEqual(scanProductionHan(valid, "valid.tsx"), []);

  const negatives = [
    `const u=(x:string)=>x; export const x=<button>{u("只剩繁體")}</button>`,
    'const msg=(x:string)=>x; const u=msg; export const x=<div>{u(`錯誤：${code}`)}</div>',
    `const activeMsg=(x:unknown)=>String(x); export const x=<div>{activeMsg({"zh-TW":"設定","zh-CN":"设置"})}</div>`,
    `import { activeMsg } from "@/i18n/ui"; export const x=activeMsg({"zh-TW":"設定",en:"Settings"})`,
    `import { activeMsg } from "@/i18n/ui"; export const x=activeMsg({"zh-TW":"設定","zh-CN":"设置",en:"Settings",ja:"設定"})`,
    `import { msg } from "@/i18n/ui"; const u=(tw:string,cn:string,en:string)=>msg("en",{"zh-TW":tw,"zh-CN":cn,en}); export const x=u("設定","设置")`,
    'const u=(x:string)=>x; export const x=ok ? u(`設定`) : <span>{u("內容")}</span>',
    `import { msg } from "not-approved"; const u=(tw:string,cn:string,en:string)=>msg("en",{"zh-TW":tw,"zh-CN":cn,en}); export const x=u("設定","设置","Settings")`,
    `import { msg } from "@/i18n/ui"; const u=(tw:string,cn:string,en:string)=>msg("en",{"zh-TW":tw,"zh-CN":cn,en}); { const u=(x:string)=>x; export const x=u("內容"); }`,
    `import { activeMsg } from "@/i18n/ui"; export const x=activeMsg({"zh-TW":"設定",[key]:"设置",en:"Settings"})`,
    `import { activeMsg } from "@/i18n/ui"; export const x=activeMsg({...base,"zh-TW":"設定","zh-CN":"设置",en:"Settings"})`,
    `import { msg } from "@/i18n/ui"; const u=(tw:string,cn:string,en:string)=>msg("en",{"zh-TW":tw,"zh-CN":cn,en}); export const x=u(ok ? "設定" : "內容","设置","Settings")`,
  ];
  negatives.forEach((fixture, index) => assert.ok(scanProductionHan(fixture, `negative-${index}.tsx`).length > 0, `fixture ${index} bypassed the guard`));
});
