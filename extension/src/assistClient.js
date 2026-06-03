(function attachAssistClient(global) {
  function cleanApiBase(apiBase) {
    return (apiBase || "https://askpicky.com").replace(/\/+$/, "");
  }

  async function postJson({ apiBase, token, path, body, fetchImpl }) {
    const fetcher = fetchImpl || global.fetch;
    if (!fetcher) {
      throw new Error("fetch_unavailable");
    }
    const response = await fetcher(`${cleanApiBase(apiBase)}${path}`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body)
    });
    if (!response.ok) {
      throw new Error(`askpicky_${response.status}`);
    }
    return response.json();
  }

  function selectedMemoryIds(memoryResponse, critiqueResponse) {
    const ids = [];
    const sources = [
      ...(memoryResponse?.suggestions || []),
      ...(critiqueResponse?.critique?.suggested_angles || [])
    ];
    for (const item of sources) {
      if (item?.memory_id && !ids.includes(item.memory_id)) {
        ids.push(item.memory_id);
      }
    }
    return ids;
  }

  async function reviewApplicationQuestion({
    apiBase,
    token,
    context = {},
    question,
    jdContext = "",
    includePrivate = false,
    fetchImpl
  }) {
    const started = await postJson({
      apiBase,
      token,
      path: "/api/assist/start",
      fetchImpl,
      body: {
        jd_text: jdContext,
        job_url: context.pageUrl || undefined,
        private_mode: true
      }
    });
    const assistSessionId = started?.assist_session?.assist_session_id;
    const memory = await postJson({
      apiBase,
      token,
      path: "/api/assist/suggest-memory",
      fetchImpl,
      body: {
        assist_session_id: assistSessionId,
        question_text: question,
        jd_text: jdContext,
        include_private: includePrivate,
        k: 5
      }
    });
    const questionType = memory?.pattern?.question_type;
    const critique = await postJson({
      apiBase,
      token,
      path: "/api/assist/critique-draft",
      fetchImpl,
      body: {
        assist_session_id: assistSessionId,
        question_text: question,
        jd_text: jdContext,
        raw_draft: context.activeFieldText || "",
        question_type: questionType,
        include_private: includePrivate,
        selected_memory_ids: selectedMemoryIds(memory, null)
      }
    });
    return {
      assistSessionId,
      attemptId: critique?.attempt_id,
      questionType: critique?.critique?.question_type || questionType,
      question,
      jdContext,
      includePrivate,
      selectedMemoryIds: selectedMemoryIds(memory, critique),
      memory,
      critique,
      saveIndicator: critique?.save_indicator || ""
    };
  }

  async function polishApplicationAnswer({
    apiBase,
    token,
    state,
    draft,
    fetchImpl
  }) {
    const polished = await postJson({
      apiBase,
      token,
      path: "/api/assist/polish",
      fetchImpl,
      body: {
        assist_session_id: state.assistSessionId,
        attempt_id: state.attemptId,
        question_text: state.question,
        jd_text: state.jdContext || "",
        raw_draft: draft || "",
        question_type: state.questionType,
        include_private: Boolean(state.includePrivate),
        selected_memory_ids: state.selectedMemoryIds || []
      }
    });
    return {
      ...state,
      attemptId: polished?.attempt_id || state.attemptId,
      polished,
      saveIndicator: polished?.output?.save_indicator || state.saveIndicator || ""
    };
  }

  async function approveApplicationAnswer({
    apiBase,
    token,
    state,
    finalAnswer,
    fetchImpl
  }) {
    if (!state?.attemptId) {
      return { approved: false, saveIndicator: state?.saveIndicator || "" };
    }
    const approved = await postJson({
      apiBase,
      token,
      path: "/api/assist/approve",
      fetchImpl,
      body: {
        attempt_id: state.attemptId,
        final_answer: finalAnswer || "",
        selected_memory_ids: state.selectedMemoryIds || []
      }
    });
    return {
      ...state,
      approved,
      saveIndicator: approved?.save_indicator || state.saveIndicator || ""
    };
  }

  global.AskPickyAssistClient = {
    cleanApiBase,
    postJson,
    selectedMemoryIds,
    reviewApplicationQuestion,
    polishApplicationAnswer,
    approveApplicationAnswer
  };
})(globalThis);
