"use strict";

const choices = [...document.querySelectorAll("[data-choice]")];
const message = document.querySelector("#vote-message");
const totalVotes = document.querySelector("#total-votes");
const diddlyVotes = document.querySelector("#diddly-votes");
const drakeVotes = document.querySelector("#drake-votes");
const names = { diddly: "Diddly", drake: "Drake" };
const numberFormat = new Intl.NumberFormat("en-US");
const configuredUrl = (window.POLL_CONFIG?.apiUrl || "").trim();
const localPreview = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
const apiUrl = localPreview ? new URL("api/votes", document.baseURI).href :
  (location.protocol === "file:" ? "" : configuredUrl);
const remoteBackend = Boolean(apiUrl) && !localPreview;
let voterToken = null;
let busy = false;
let requestVersion = 0;

function savedVoterToken() {
  const storageKey = "diddly-or-drake.voter";
  let token = localStorage.getItem(storageKey);
  if (!/^[A-Za-z0-9_-]{43}$/.test(token || "")) {
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    token = btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
    localStorage.setItem(storageKey, token);
  }
  return token;
}

function renderVote(data) {
  totalVotes.textContent = numberFormat.format(data.total);
  totalVotes.setAttribute("aria-label", numberFormat.format(data.total) + " total votes");
  diddlyVotes.textContent = numberFormat.format(data.votes.diddly);
  drakeVotes.textContent = numberFormat.format(data.votes.drake);
  for (const button of choices) {
    button.setAttribute("aria-pressed", String(data.choice === button.dataset.choice));
  }
  message.textContent = data.choice ? "You voted for " + names[data.choice] + "." : "";
}

async function voteRequest(options = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const headers = new Headers(options.headers);
    if (remoteBackend && voterToken) headers.set("Authorization", "Bearer " + voterToken);
    const response = await fetch(apiUrl, {
      ...options,
      credentials: remoteBackend ? "omit" : "same-origin",
      cache: "no-store",
      headers,
      signal: controller.signal
    });
    if (!response.ok) throw new Error("Voting request failed");
    const data = await response.json();
    if (!data.votes || !Number.isSafeInteger(data.votes.diddly) ||
        !Number.isSafeInteger(data.votes.drake) || data.votes.diddly < 0 ||
        data.votes.drake < 0 || !Number.isSafeInteger(data.total) ||
        data.total !== data.votes.diddly + data.votes.drake ||
        (data.choice !== null && !Object.hasOwn(names, data.choice))) {
      throw new Error("Invalid voting response");
    }
    return data;
  } finally {
    clearTimeout(timeout);
  }
}

async function refreshVote() {
  if (busy) return;
  const version = ++requestVersion;
  try {
    const data = await voteRequest();
    if (version === requestVersion) renderVote(data);
  } catch {
    if (version === requestVersion) message.textContent = "Voting is unavailable. Try again shortly.";
  }
}

for (const button of choices) {
  button.addEventListener("click", async () => {
    if (busy || !apiUrl) return;
    busy = true;
    ++requestVersion;
    choices.forEach((choice) => { choice.disabled = true; });
    message.textContent = "Saving your vote…";
    try {
      renderVote(await voteRequest({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ choice: button.dataset.choice })
      }));
    } catch {
      message.textContent = "Couldn’t confirm your vote. Click a name to retry.";
    } finally {
      busy = false;
      choices.forEach((choice) => { choice.disabled = false; });
      if (document.activeElement === document.body || document.activeElement === button) {
        button.focus({ preventScroll: true });
      }
    }
  });
}

function initializeVoting() {
  if (!apiUrl) {
    message.textContent = "Voting opens soon.";
    choices.forEach((choice) => { choice.disabled = true; });
    return;
  }
  if (remoteBackend) {
    try {
      const target = new URL(apiUrl);
      if (target.protocol !== "https:" && !["localhost", "127.0.0.1", "[::1]"].includes(target.hostname)) {
        throw new Error("HTTPS required");
      }
      voterToken = savedVoterToken();
    } catch {
      message.textContent = "Voting is unavailable. Allow site storage and try again.";
      choices.forEach((choice) => { choice.disabled = true; });
      return;
    }
  }
  refreshVote();
  window.addEventListener("focus", refreshVote);
}
initializeVoting();

const answerDetails = document.querySelector("#coin-flip-faq");
const answer = document.querySelector("#alternating-answer");
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let answerTimer;
let answerIsDrake = false;
function updateAnswer() {
  clearInterval(answerTimer);
  answerTimer = undefined;
  answerIsDrake = false;
  answer.textContent = reducedMotion.matches ? "diddly💀 or drake🤡" : "diddly💀";
  answer.className = reducedMotion.matches ? "" : "diddly";
  if (!answerDetails.open || reducedMotion.matches || document.hidden) return;
  answerTimer = setInterval(() => {
    answerIsDrake = !answerIsDrake;
    answer.textContent = answerIsDrake ? "drake🤡" : "diddly💀";
    answer.className = answerIsDrake ? "drake" : "diddly";
  }, 850);
}
answerDetails.addEventListener("toggle", updateAnswer);
reducedMotion.addEventListener("change", updateAnswer);
document.addEventListener("visibilitychange", updateAnswer);
updateAnswer();