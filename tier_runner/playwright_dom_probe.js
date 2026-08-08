({
  startIndex = 0,
  probeNonce = "tier",
  viewportExpansion = 500,
  highlight = true,
  maxVisibleTextChars = 24000,
} = {}) => {
  const ATTR = "data-tier-browser-id";
  const CONTAINER = "tier-browser-highlight-container";
  const old = document.getElementById(CONTAINER);
  if (old) old.remove();
  document.querySelectorAll(`[${ATTR}]`).forEach((node) => node.removeAttribute(ATTR));

  const interactiveTags = new Set([
    "a", "button", "input", "select", "textarea", "details", "summary",
    "option", "label", "menuitem", "canvas"
  ]);
  const interactiveRoles = new Set([
    "button", "checkbox", "combobox", "link", "listbox", "menuitem", "option",
    "radio", "searchbox", "slider", "spinbutton", "switch", "tab", "textbox",
    "treeitem"
  ]);
  const results = [];
  let nextIndex = startIndex;

  const normalize = (value, limit = 500) => String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);

  const visible = (element) => {
    if (!(element instanceof Element)) return false;
    const style = getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") {
      return false;
    }
    const rect = element.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return false;
    if (viewportExpansion === -1) return true;
    return !(
      rect.bottom < -viewportExpansion ||
      rect.top > innerHeight + viewportExpansion ||
      rect.right < -viewportExpansion ||
      rect.left > innerWidth + viewportExpansion
    );
  };

  const topmost = (element) => {
    const rect = element.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > innerHeight || rect.right < 0 || rect.left > innerWidth) {
      return true;
    }
    const x = Math.max(0, Math.min(innerWidth - 1, rect.left + rect.width / 2));
    const y = Math.max(0, Math.min(innerHeight - 1, rect.top + rect.height / 2));
    const root = element.getRootNode();
    const candidate = root && typeof root.elementFromPoint === "function"
      ? root.elementFromPoint(x, y)
      : document.elementFromPoint(x, y);
    return Boolean(candidate && (candidate === element || element.contains(candidate)));
  };

  const accessibleName = (element) => {
    const labelledBy = element.getAttribute("aria-labelledby");
    if (labelledBy) {
      const text = labelledBy.split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent || "")
        .join(" ");
      if (normalize(text)) return normalize(text);
    }
    const labels = element.labels ? Array.from(element.labels).map((label) => label.textContent || "") : [];
    return normalize(
      element.getAttribute("aria-label") ||
      labels.join(" ") ||
      element.getAttribute("alt") ||
      element.getAttribute("title") ||
      element.getAttribute("placeholder") ||
      element.getAttribute("name") ||
      element.innerText ||
      element.textContent ||
      ""
    );
  };

  const isInteractive = (element) => {
    const tag = element.tagName.toLowerCase();
    const role = normalize(element.getAttribute("role"), 80).toLowerCase();
    const tabindex = element.getAttribute("tabindex");
    return (
      interactiveTags.has(tag) ||
      interactiveRoles.has(role) ||
      element.isContentEditable ||
      element.getAttribute("contenteditable") === "true" ||
      element.hasAttribute("onclick") ||
      element.hasAttribute("ng-click") ||
      element.hasAttribute("@click") ||
      element.hasAttribute("v-on:click") ||
      element.hasAttribute("aria-expanded") ||
      element.hasAttribute("aria-pressed") ||
      element.hasAttribute("aria-selected") ||
      element.hasAttribute("aria-checked") ||
      (tabindex !== null && tabindex !== "-1")
    );
  };

  const cssEscape = (value) => {
    if (globalThis.CSS && typeof globalThis.CSS.escape === "function") return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, (char) => `\\${char.codePointAt(0).toString(16)} `);
  };

  const cssPath = (element) => {
    const parts = [];
    let current = element;
    while (current && current instanceof Element) {
      if (current.id) {
        parts.unshift(`#${cssEscape(current.id)}`);
        break;
      }
      const testId = current.getAttribute("data-testid") || current.getAttribute("data-test") ||
        current.getAttribute("data-qa") || current.getAttribute("data-cy");
      if (testId) {
        parts.unshift(`[data-testid="${String(testId).replace(/"/g, '\\"')}"]`);
        break;
      }
      const tag = current.tagName.toLowerCase();
      const parent = current.parentElement;
      if (!parent) {
        parts.unshift(tag);
        break;
      }
      const siblings = Array.from(parent.children).filter((node) => node.tagName === current.tagName);
      const suffix = siblings.length > 1 ? `:nth-of-type(${siblings.indexOf(current) + 1})` : "";
      parts.unshift(tag + suffix);
      const root = current.getRootNode();
      if (root instanceof ShadowRoot) {
        current = root.host;
        parts.unshift(">>>");
      } else {
        current = parent;
      }
    }
    return parts.join(" > ").replace(/ > >>> > /g, " >>> ");
  };

  const roleFor = (element) => normalize(element.getAttribute("role"), 80).toLowerCase();
  const usefulAttributes = (element) => {
    const allowed = [
      "id", "name", "type", "role", "aria-label", "aria-expanded", "aria-checked",
      "placeholder", "title", "alt", "href", "value", "autocomplete", "data-testid",
      "data-test", "data-qa", "data-cy"
    ];
    const result = {};
    for (const name of allowed) {
      const value = element.getAttribute(name);
      if (value !== null) result[name] = normalize(value, name === "value" ? 120 : 500);
    }
    return result;
  };

  const overlayRoot = (() => {
    if (!highlight) return null;
    const container = document.createElement("div");
    container.id = CONTAINER;
    Object.assign(container.style, {
      position: "fixed", inset: "0", pointerEvents: "none", zIndex: "2147483647"
    });
    document.documentElement.appendChild(container);
    return container;
  })();

  const mark = (element, index) => {
    if (!overlayRoot) return;
    const rect = element.getBoundingClientRect();
    const box = document.createElement("div");
    Object.assign(box.style, {
      position: "fixed",
      left: `${rect.left}px`, top: `${rect.top}px`,
      width: `${rect.width}px`, height: `${rect.height}px`,
      border: "2px solid #ff2d55", background: "rgba(255,45,85,.08)",
      boxSizing: "border-box", pointerEvents: "none"
    });
    const label = document.createElement("div");
    label.textContent = String(index);
    Object.assign(label.style, {
      position: "absolute", right: "0", top: "0", transform: "translateY(-100%)",
      background: "#ff2d55", color: "white", padding: "1px 4px", borderRadius: "3px",
      font: "11px/14px sans-serif"
    });
    box.appendChild(label);
    overlayRoot.appendChild(box);
  };

  const visit = (node) => {
    if (!(node instanceof Element)) return;
    if (node.id === CONTAINER) return;
    if (visible(node) && topmost(node) && isInteractive(node)) {
      const index = nextIndex++;
      const probeId = `${probeNonce}:${index}`;
      node.setAttribute(ATTR, probeId);
      const rect = node.getBoundingClientRect();
      const attributes = usefulAttributes(node);
      const name = accessibleName(node);
      const text = normalize(node.innerText || node.textContent || "", 1000);
      const descriptor = {
        index,
        probe_id: probeId,
        tag: node.tagName.toLowerCase(),
        role: roleFor(node),
        name,
        text,
        attributes,
        css_path: cssPath(node),
        input_type: normalize(node.getAttribute("type"), 80).toLowerCase(),
        editable: Boolean(node.isContentEditable || ["input", "textarea", "select"].includes(node.tagName.toLowerCase())),
        disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true"),
        bbox: {
          x: Math.round(rect.x), y: Math.round(rect.y),
          width: Math.round(rect.width), height: Math.round(rect.height)
        }
      };
      descriptor.signature = JSON.stringify([
        descriptor.tag, descriptor.role, descriptor.name,
        attributes.id || "", attributes.name || "", attributes.href || "",
        descriptor.css_path
      ]);
      results.push(descriptor);
      mark(node, index);
    }
    if (node.shadowRoot) {
      for (const child of node.shadowRoot.children) visit(child);
    }
    for (const child of node.children) visit(child);
  };

  if (document.body) visit(document.body);
  const visibleText = normalize(document.body?.innerText || "", maxVisibleTextChars);
  return {
    elements: results,
    nextIndex,
    visibleText,
    scroll: {
      pixelsAbove: Math.max(0, Math.round(scrollY)),
      pixelsBelow: Math.max(0, Math.round(document.documentElement.scrollHeight - scrollY - innerHeight)),
      viewportHeight: Math.round(innerHeight),
      documentHeight: Math.round(document.documentElement.scrollHeight)
    }
  };
};
