const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadDetector() {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "detector.js"),
    "utf8",
  );
  class FakeEvent {
    constructor(type, options = {}) {
      this.type = type;
      this.bubbles = Boolean(options.bubbles);
    }
  }
  const context = {
    CSS: { escape: (value) => String(value) },
    Event: FakeEvent,
    URL,
    console,
  };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "detector.js" });
  return context.AskPickyDetector;
}

function element({
  tagName = "div",
  text = "",
  value,
  attrs = {},
  isContentEditable = false,
  parent = null,
} = {}) {
  const events = [];
  const node = {
    tagName,
    textContent: text,
    innerText: text,
    attrs,
    isContentEditable,
    events,
    focused: false,
    getAttribute(name) {
      return this.attrs[name] || null;
    },
    closest() {
      return parent;
    },
    focus() {
      this.focused = true;
    },
    dispatchEvent(event) {
      events.push(event.type);
    },
  };
  if (value !== undefined) {
    node.value = value;
  }
  return node;
}

function doc({ activeElement, labelByFor = {}, byId = {}, title = "Apply" } = {}) {
  return {
    activeElement,
    title,
    querySelector(selector) {
      const match = selector.match(/^label\[for="(.+)"\]$/);
      return match ? labelByFor[match[1]] || null : null;
    },
    getElementById(id) {
      return byId[id] || null;
    },
    execCommand(command, _show, value) {
      if (command === "insertText" && this.activeElement) {
        this.activeElement.innerText = value;
      }
      return true;
    },
  };
}

const detector = loadDetector();

{
  const manifest = JSON.parse(fs.readFileSync(
    path.join(__dirname, "..", "manifest.json"),
    "utf8",
  ));
  assert.deepEqual(
    manifest.permissions.sort(),
    ["activeTab", "scripting", "sidePanel", "storage"].sort(),
  );
  assert.deepEqual(manifest.host_permissions, ["https://askpicky.com/*"]);
  assert.equal(manifest.content_scripts, undefined);
  assert.deepEqual(manifest.externally_connectable.matches, ["https://askpicky.com/*"]);
}

{
  const label = element({ tagName: "label", text: "Describe a technical project" });
  const field = element({
    tagName: "textarea",
    value: "rough draft",
    attrs: { id: "answer" },
  });
  const context = detector.collectContext(
    doc({ activeElement: field, labelByFor: { answer: label } }),
    { getSelection: () => "highlighted JD" },
    { href: "https://jobs.example/apply" },
  );

  assert.equal(context.detectedQuestion, "Describe a technical project");
  assert.equal(context.fieldConfidence, "HIGH");
  assert.equal(context.activeFieldText, "rough draft");
  assert.equal(context.selectedText, "highlighted JD");
}

{
  const field = element({
    tagName: "div",
    text: "current answer",
    isContentEditable: true,
    attrs: { "aria-label": "Why do you want this role?" },
  });
  const context = detector.collectContext(
    doc({ activeElement: field }),
    { getSelection: () => "" },
    { href: "https://jobs.example/apply" },
  );

  assert.equal(context.detectedQuestion, "Why do you want this role?");
  assert.equal(context.fieldConfidence, "HIGH");
  assert.equal(context.activeFieldText, "current answer");
}

{
  const parent = element({
    tagName: "section",
    text: "Give an example of stakeholder communication under pressure",
  });
  const field = element({ tagName: "textarea", value: "", parent });
  const label = detector.nearbyLabel(field, doc({ activeElement: field }));

  assert.equal(label.text, "Give an example of stakeholder communication under pressure");
  assert.equal(label.confidence, "MEDIUM");
}

{
  const parent = element({
    tagName: "div",
    text: "Greenhouse question: Describe the data platform you owned",
  });
  const field = element({ tagName: "textarea", value: "draft", parent });
  const context = detector.collectContext(
    doc({ activeElement: field }),
    { getSelection: () => "" },
    { href: "https://boards.greenhouse.io/acme/jobs/123" },
  );

  assert.equal(context.adapter, "greenhouse");
  assert.equal(context.fieldConfidence, "HIGH");
  assert.equal(context.detectedQuestion, "Greenhouse question: Describe the data platform you owned");
}

{
  const parent = element({
    tagName: "div",
    text: "Lever question: Why do you want to work with this product team?",
  });
  const field = element({ tagName: "textarea", value: "", parent });
  const context = detector.collectContext(
    doc({ activeElement: field }),
    { getSelection: () => "" },
    { href: "https://jobs.lever.co/acme/abc" },
  );

  assert.equal(context.adapter, "lever");
  assert.equal(context.fieldConfidence, "HIGH");
  assert.equal(context.detectedQuestion, "Lever question: Why do you want to work with this product team?");
}

{
  const parent = element({
    tagName: "fieldset",
    text: "Workday question: Explain your experience with Python and SQL",
  });
  const field = element({ tagName: "textarea", value: "", parent });
  const context = detector.collectContext(
    doc({ activeElement: field }),
    { getSelection: () => "" },
    { href: "https://acme.wd3.myworkdayjobs.com/en-US/jobs/job/123" },
  );

  assert.equal(context.adapter, "workday");
  assert.equal(context.fieldConfidence, "HIGH");
  assert.equal(context.detectedQuestion, "Workday question: Explain your experience with Python and SQL");
}

{
  const field = element({ tagName: "textarea", value: "old" });
  const result = detector.writeAnswer("approved answer", doc({ activeElement: field }));

  assert.equal(result.ok, true);
  assert.equal(result.method, "value");
  assert.equal(field.value, "approved answer");
  assert.deepEqual(field.events, ["input", "change"]);
}

{
  const result = detector.writeAnswer("approved answer", doc({
    activeElement: element({ tagName: "button" }),
  }));

  assert.equal(result.ok, false);
  assert.equal(result.reason, "no_active_editable_field");
}

console.log("extension detector fixtures passed");
