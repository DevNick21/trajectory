chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const detector = globalThis.AskPickyDetector;
  if (!detector) {
    sendResponse({ ok: false, reason: "detector_not_loaded" });
    return true;
  }

  if (message?.type === "ASKPICKY_COLLECT_CONTEXT") {
    sendResponse(detector.collectContext());
    return true;
  }

  if (message?.type === "ASKPICKY_WRITE_APPROVED_ANSWER") {
    sendResponse(detector.writeAnswer(message.answer || ""));
    return true;
  }

  return false;
});
