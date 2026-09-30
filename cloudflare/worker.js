const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const MAX_BODY = 1024;

async function readVote(request) {
  if (!request.headers.get("Content-Type")?.toLowerCase().startsWith("application/json")) {
    throw new Error("Use application/json.");
  }
  if (!request.body) throw new Error("A vote is required.");
  const reader = request.body.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > MAX_BODY) {
        await reader.cancel();
        throw new Error("Vote request is too large.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  const data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  if (data?.choice !== "diddly" && data?.choice !== "drake") throw new Error("Choose diddly or drake.");
  return data.choice;
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const allowed = (env.ALLOWED_ORIGINS || "").split(",").map((value) => value.trim()).filter(Boolean);
    const headers = new Headers({
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Vary": "Origin"
    });
    const json = (status, value) => new Response(JSON.stringify(value), { status, headers });
    if (!allowed.includes(origin)) return json(403, { error: "Origin not allowed." });
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
    headers.set("Access-Control-Allow-Headers", "Authorization, Content-Type");
    headers.set("Access-Control-Max-Age", "86400");
    if (new URL(request.url).pathname !== "/api/votes") return json(404, { error: "Not found." });
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers });
    if (request.method !== "GET" && request.method !== "POST") {
      headers.set("Allow", "GET, POST, OPTIONS");
      return json(405, { error: "Method not allowed." });
    }

    const authorization = request.headers.get("Authorization");
    const token = authorization?.startsWith("Bearer ") ? authorization.slice(7) : "";
    if ((authorization && !TOKEN.test(token)) || (request.method === "POST" && !TOKEN.test(token))) {
      return json(400, { error: "A valid voter token is required." });
    }
    let choice;
    if (request.method === "POST") {
      try {
        choice = await readVote(request);
      } catch {
        return json(400, { error: "Send a small JSON object with choice diddly or drake." });
      }
    }

    try {
      let voterId = "";
      if (token) {
        const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(token));
        voterId = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
      }
      const statements = [];
      if (choice) {
        statements.push(env.DB.prepare(
          "INSERT INTO votes (voter_id, choice) VALUES (?, ?) " +
          "ON CONFLICT(voter_id) DO UPDATE SET choice = excluded.choice WHERE votes.choice <> excluded.choice"
        ).bind(voterId, choice));
      }
      statements.push(env.DB.prepare("SELECT choice, count FROM vote_totals"));
      statements.push(env.DB.prepare("SELECT choice FROM votes WHERE voter_id = ?").bind(voterId));
      // D1 executes the batch as a transaction; the counts match the saved vote.
      const rows = await env.DB.batch(statements);
      const counts = { diddly: 0, drake: 0 };
      for (const row of rows[rows.length - 2].results) counts[row.choice] = row.count;
      return json(200, {
        votes: counts,
        total: counts.diddly + counts.drake,
        choice: rows[rows.length - 1].results[0]?.choice || null
      });
    } catch {
      return json(503, { error: "Voting is temporarily unavailable. Please try again." });
    }
  }
};
