(function () {
  function visibleText(node) {
    if (!node) return "";
    return (node.innerText || node.textContent || "").replace(/\s+/g, " ").trim();
  }

  function fieldValue(element) {
    if (!element) return "";
    if ("value" in element) return element.value || "";
    if (element.isContentEditable) return element.innerText || "";
    return "";
  }

  function isEditable(element) {
    if (!element) return false;
    const tag = element.tagName?.toLowerCase();
    return tag === "textarea" || tag === "input" || element.isContentEditable;
  }

  function explicitLabelFor(element, doc) {
    const id = element?.getAttribute?.("id");
    if (!id) return "";
    const escape = globalThis.CSS?.escape || ((value) => String(value).replace(/"/g, '\\"'));
    return visibleText(doc.querySelector?.(`label[for="${escape(id)}"]`));
  }

  function ariaLabelFor(element, doc) {
    const ariaLabel = element?.getAttribute?.("aria-label");
    if (ariaLabel) return ariaLabel;

    const labelledBy = element?.getAttribute?.("aria-labelledby");
    if (!labelledBy) return "";
    return labelledBy
      .split(/\s+/)
      .map((part) => visibleText(doc.getElementById?.(part)))
      .filter(Boolean)
      .join(" ");
  }

  function nearbyLabel(element, doc = globalThis.document) {
    if (!element || !doc) return { text: "", confidence: "LOW" };

    const explicit = explicitLabelFor(element, doc);
    if (explicit) return { text: explicit, confidence: "HIGH" };

    const aria = ariaLabelFor(element, doc);
    if (aria) return { text: aria, confidence: "HIGH" };

    const parent = element.closest?.("label, fieldset, section, div");
    if (parent) {
      const text = visibleText(parent).slice(0, 500);
      if (text) return { text, confidence: text.length > 30 ? "MEDIUM" : "LOW" };
    }

    return { text: "", confidence: "LOW" };
  }

  function collectContext(
    doc = globalThis.document,
    win = globalThis.window,
    loc = globalThis.location,
  ) {
    const selection = String(win?.getSelection?.() || "").trim();
    const active = doc?.activeElement;
    const editable = isEditable(active) ? active : null;
    const label = nearbyLabel(editable, doc);
    return {
      selectedText: selection,
      activeFieldText: fieldValue(editable),
      detectedQuestion: label.text,
      fieldConfidence: label.confidence,
      pageTitle: doc?.title || "",
      pageUrl: loc?.href || ""
    };
  }

  function dispatchInputEvents(element) {
    element.dispatchEvent?.(new Event("input", { bubbles: true }));
    element.dispatchEvent?.(new Event("change", { bubbles: true }));
  }

  function writeAnswer(answer, doc = globalThis.document) {
    const active = doc?.activeElement;
    if (!isEditable(active)) {
      return { ok: false, reason: "no_active_editable_field" };
    }

    if ("value" in active) {
      active.focus?.();
      active.value = answer;
      dispatchInputEvents(active);
      return { ok: true, method: "value" };
    }

    if (active.isContentEditable) {
      active.focus?.();
      if (typeof doc.execCommand === "function") {
        doc.execCommand("selectAll", false, null);
        doc.execCommand("insertText", false, answer);
      } else {
        active.innerText = answer;
      }
      active.dispatchEvent?.(new Event("input", { bubbles: true }));
      return { ok: true, method: "contenteditable" };
    }

    return { ok: false, reason: "unsupported_field" };
  }

  globalThis.AskPickyDetector = {
    collectContext,
    fieldValue,
    isEditable,
    nearbyLabel,
    visibleText,
    writeAnswer
  };
})();
