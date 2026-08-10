// The gloss pass's transport, kept apart from the engine that plans it.
//
// It is a plain script rather than part of worker.js so it can be driven in a
// test without booting Pyodide: what is worth testing here is the concurrency
// and the retries, and neither of those needs a Python runtime to be wrong.
// `pyodide` is read from the global scope at call time, so a test may stand in
// for it.

// How many gloss requests are in flight at once.
//
// The engine's own client blocks the worker until each answer arrives, which is
// right for a pipeline written straight through and is why glossing a book of
// 1,500 paragraphs took an afternoon: the work is nearly all waiting, and none
// of the waits overlapped. These calls are made here instead, so they can. Six
// is ordinary for a provider and well inside any rate limit worth the name.
//
// A model on the reader's own machine gets one. A second request there does not
// overlap the first, it queues behind it on the same card, and asking for six at
// once only makes the machine slower at all of them.
const GLOSS_AT_ONCE = 6;
const RETRY_AFTER = [2, 6, 15];  // seconds, for a provider saying "not so fast"

async function ask(cfg, system, user, maxTokens) {
  const anthropic = cfg.provider === "anthropic";
  const url = anthropic
    ? "https://api.anthropic.com/v1/messages"
    : (cfg.baseUrl || "https://api.openai.com/v1").replace(/\/+$/, "") + "/chat/completions";
  const headers = anthropic
    ? { "content-type": "application/json", "x-api-key": cfg.key,
        "anthropic-version": "2023-06-01",
        "anthropic-dangerous-direct-browser-access": "true" }
    : { "content-type": "application/json", authorization: "Bearer " + cfg.key,
        "x-title": "Lecteur bilingue" };
  const body = anthropic
    ? { model: cfg.model, max_tokens: maxTokens, system, messages: [{ role: "user", content: user }] }
    : { model: cfg.model, max_tokens: maxTokens,
        messages: [{ role: "system", content: system }, { role: "user", content: user }] };

  for (let go = 0; ; go++) {
    const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body) });
    if ((res.status === 429 || res.status >= 500) && go < RETRY_AFTER.length) {
      const said = Number(res.headers.get("retry-after"));
      await new Promise((r) => setTimeout(r, (said > 0 ? said : RETRY_AFTER[go]) * 1000));
      continue;
    }
    if (!res.status || res.status !== 200) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const usage = data.usage || {};
    if (anthropic) {
      return {
        text: (data.content || []).filter((b) => b.type === "text").map((b) => b.text).join(""),
        truncated: data.stop_reason === "max_tokens",
        in: usage.input_tokens || 0, out: usage.output_tokens || 0,
      };
    }
    const choice = (data.choices || [{}])[0];
    return {
      text: (choice.message || {}).content || "",
      truncated: choice.finish_reason === "length",
      in: usage.prompt_tokens || 0, out: usage.completion_tokens || 0,
    };
  }
}

// Every batch of the plan, several at a time. A batch nothing can be anchored in
// is asked for once more with the stricter note and then written off to the
// rescue pass — the same two attempts the engine has always made, and the same
// judgement about what may be kept, which lives in gloss.py and not here.
async function glossInParallel(task, cfg) {
  const take = pyodide.globals.get("gloss_take");
  const off = pyodide.globals.get("gloss_off");
  // `retryIn`/`retryOut` are the sends beyond one clean pass. An estimate prices
  // one send a batch, so a second one is spend nothing has ever counted; the
  // rescue pass counts itself, in gloss.py, because the engine makes those calls.
  const used = { in: 0, out: 0, retryIn: 0, retryOut: 0, resent: 0 };
  let next = 0;
  const worker = async () => {
    for (let i = next++; i < task.batches.length; i = next++) {
      const b = task.batches[i];
      for (let attempt = 0; attempt < 2; attempt++) {
        let reply;
        try {
          reply = await ask(cfg, attempt ? task.retry : task.system, b.prompt, task.maxTokens);
        } catch (err) {
          break;  // unreachable or refused: the rescue pass tries it alone
        }
        used.in += reply.in; used.out += reply.out;
        if (attempt) { used.resent++; used.retryIn += reply.in; used.retryOut += reply.out; }
        if (reply.truncated) break;
        if (take(b.n, reply.text)) break;
      }
      off(b.n);
    }
  };
  const hands = cfg.local ? 1 : Math.min(GLOSS_AT_ONCE, task.batches.length);
  await Promise.all(Array.from({ length: hands }, worker));
  take.destroy(); off.destroy();
  return used;
}
