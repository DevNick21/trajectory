const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function loadClient() {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "assistClient.js"),
    "utf8",
  );
  const context = { console };
  context.globalThis = context;
  vm.createContext(context);
  vm.runInContext(source, context, { filename: "assistClient.js" });
  return context.AskPickyAssistClient;
}

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return payload;
    },
  };
}

async function main() {
  const client = loadClient();

  {
    const html = fs.readFileSync(
      path.join(__dirname, "..", "src", "sidepanel.html"),
      "utf8",
    );
    assert.ok(html.indexOf("assistClient.js") < html.indexOf("sidepanel.js"));
    assert.match(html, /<input id="includePrivate" type="checkbox" \/>/);
  }

  {
    assert.equal(client.DEFAULT_API_BASE, "http://localhost:8000");
    assert.equal(client.cleanApiBase("http://localhost:8000/"), "http://localhost:8000");
    assert.deepEqual(
      Array.from(client.selectedMemoryIds(
        { suggestions: [{ memory_id: "m1" }, { memory_id: "m2" }] },
        { critique: { suggested_angles: [{ memory_id: "m2" }, { memory_id: "m3" }] } },
      )),
      ["m1", "m2", "m3"],
    );
  }

  {
    const calls = [];
    const fetchImpl = async (url, options) => {
      calls.push({ url, options, body: JSON.parse(options.body) });
      if (url.endsWith("/api/assist/start")) {
        return response({ assist_session: { assist_session_id: "assist-1" } });
      }
      if (url.endsWith("/api/assist/suggest-memory")) {
        return response({
          pattern: {
            question_type: "technical",
            what_testing: "Depth of technical ownership",
            structure_hint: "Use problem-action-result",
          },
          suggestions: [
            {
              memory_id: "story-1",
              memory_kind: "story_frame",
              title: "Data migration",
              text: "Migrated a warehouse",
              rationale: "Matches technical ownership",
              score: 0.91,
            },
          ],
          advice_snippets: [],
        });
      }
      if (url.endsWith("/api/assist/critique-draft")) {
        return response({
          attempt_id: "attempt-1",
          save_indicator: "Saved privately",
          critique: {
            question_type: "technical",
            what_testing: "Depth of technical ownership",
            missing_evidence: ["Add the production outcome"],
            targeted_nudge: "Add one concrete result.",
            suggested_angles: [
              {
                memory_id: "story-1",
                title: "Data migration",
                rationale: "Strong fit",
              },
            ],
          },
        });
      }
      throw new Error(`unexpected ${url}`);
    };

    const state = await client.reviewApplicationQuestion({
      apiBase: "http://localhost:8000/",
      context: {
        pageUrl: "https://jobs.example/apply",
        activeFieldText: "I improved the pipeline.",
      },
      question: "Describe a technical project",
      jdContext: "Python data platform",
      includePrivate: true,
      fetchImpl,
    });

    assert.equal(calls.length, 3);
    assert.equal(calls[0].url, "http://localhost:8000/api/assist/start");
    assert.equal(calls[0].options.headers.Authorization, undefined);
    assert.equal(calls[0].body.private_mode, true);
    assert.equal(calls[0].body.job_url, "https://jobs.example/apply");
    assert.equal(calls[1].body.include_private, true);
    assert.equal(calls[2].body.raw_draft, "I improved the pipeline.");
    assert.deepEqual(Array.from(calls[2].body.selected_memory_ids), ["story-1"]);
    assert.equal(state.assistSessionId, "assist-1");
    assert.equal(state.attemptId, "attempt-1");
    assert.equal(state.questionType, "technical");
    assert.equal(state.saveIndicator, "Saved privately");
  }

  {
    const calls = [];
    const fetchImpl = async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      if (url.endsWith("/api/assist/polish")) {
        return response({
          attempt_id: "attempt-1",
          output: {
            final_answer: "Polished answer",
            question_type: "technical",
            save_indicator: "Saved privately",
          },
        });
      }
      if (url.endsWith("/api/assist/approve")) {
        return response({
          attempt_id: "attempt-1",
          memory_items_created: 2,
          inbox_status: "pending_review",
          save_indicator: "Pending review",
        });
      }
      throw new Error(`unexpected ${url}`);
    };
    const baseState = {
      assistSessionId: "assist-1",
      attemptId: "attempt-1",
      question: "Describe a technical project",
      jdContext: "Python data platform",
      questionType: "technical",
      includePrivate: false,
      selectedMemoryIds: ["story-1"],
      saveIndicator: "Saved privately",
    };

    const polished = await client.polishApplicationAnswer({
      apiBase: "http://localhost:8000",
      state: baseState,
      draft: "rough answer",
      fetchImpl,
    });
    assert.equal(calls[0].url, "http://localhost:8000/api/assist/polish");
    assert.equal(calls[0].body.raw_draft, "rough answer");
    assert.equal(calls[0].body.include_private, false);
    assert.equal(polished.polished.output.final_answer, "Polished answer");

    const approved = await client.approveApplicationAnswer({
      apiBase: "http://localhost:8000",
      state: polished,
      finalAnswer: "Polished answer",
      fetchImpl,
    });
    assert.equal(calls[1].url, "http://localhost:8000/api/assist/approve");
    assert.equal(calls[1].body.final_answer, "Polished answer");
    assert.deepEqual(Array.from(calls[1].body.selected_memory_ids), ["story-1"]);
    assert.equal(approved.saveIndicator, "Pending review");
  }

  {
    await assert.rejects(
      () => client.postJson({
        apiBase: "http://localhost:8000",
        path: "/api/assist/start",
        body: {},
        fetchImpl: async () => response({ detail: "no" }, 401),
      }),
      /askpicky_401/,
    );
  }

  console.log("extension assist client fixtures passed");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
