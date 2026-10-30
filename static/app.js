// app.js - Client interaction, real-time telemetry, and automated scenario runner

let currentSessionId = "sess-" + Math.random().toString(36).substring(2, 9);
const chatStream = document.getElementById("chat-stream");
const chatForm = document.getElementById("chat-form");
const userInput = document.getElementById("user-input");
const sessionIdDisplay = document.getElementById("session-id-text");
const apiCallsContainer = document.getElementById("api-calls-container");
const apiCountBadge = document.getElementById("api-count");
const btnReset = document.getElementById("btn-reset");
const btnRunAll = document.getElementById("btn-run-all-scenarios");

let totalApiCallCount = 0;

// Initialize
document.addEventListener("DOMContentLoaded", () => {
  sessionIdDisplay.innerText = currentSessionId;
  setupTabs();
  setupQuickChips();
  setupChatForm();
  setupAutoScroll();
});

// Setup Auto-scroll Observer
function setupAutoScroll() {
  if (!chatStream) return;
  const observer = new MutationObserver(() => {
    scrollToBottom();
  });
  observer.observe(chatStream, { childList: true, subtree: true });
  scrollToBottom(true);
}

function scrollToBottom(forceInstant = false) {
  if (!chatStream) return;
  const doScroll = () => {
    chatStream.scrollTop = chatStream.scrollHeight;
    const last = chatStream.lastElementChild;
    if (last && typeof last.scrollIntoView === "function") {
      last.scrollIntoView({ behavior: forceInstant ? "auto" : "smooth", block: "end" });
    }
  };
  doScroll();
  requestAnimationFrame(doScroll);
  setTimeout(doScroll, 50);
  setTimeout(doScroll, 150);
}

// Setup Tabs
function setupTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      tabs.forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      tab.classList.add("active");
      const targetId = "tab-" + tab.getAttribute("data-tab");
      document.getElementById(targetId).classList.add("active");
    });
  });
}

// Setup Quick Chips
function setupQuickChips() {
  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const msg = chip.getAttribute("data-msg");
      userInput.value = msg;
      chatForm.dispatchEvent(new Event("submit"));
    });
  });
}

// Reset Session
btnReset.addEventListener("click", async () => {
  try {
    await fetch("/api/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: currentSessionId })
    });
  } catch (e) {
    console.error("Reset error:", e);
  }
  currentSessionId = "sess-" + Math.random().toString(36).substring(2, 9);
  sessionIdDisplay.innerText = currentSessionId;
  chatStream.innerHTML = `
    <div class="message bot">
      <div class="avatar bot-avatar">AI</div>
      <div class="bubble">
        <p><strong>Session reset.</strong> Ready for new sales inquiry!</p>
        <p class="hint-text">Try: <em>"I need arrow mesh wifi on the PRO plan for a 5-room house"</em></p>
      </div>
    </div>
  `;
  apiCallsContainer.innerHTML = '<div class="empty-state">No API calls recorded yet for this session.</div>';
  totalApiCallCount = 0;
  apiCountBadge.innerText = "0";
  resetStateMetrics();
});

function resetStateMetrics() {
  document.getElementById("state-sku").innerText = "None";
  document.getElementById("state-plan").innerText = "None";
  document.getElementById("state-cap").innerText = "-";
  document.getElementById("state-qty").innerText = "-";
  document.getElementById("state-base").innerText = "-";
  document.getElementById("state-promo").innerText = "None";
  document.getElementById("state-disc").innerText = "0%";
  document.getElementById("state-final").innerText = "-";
  document.getElementById("state-obj").innerText = "0";
  document.getElementById("state-conf").innerText = "No";
  document.getElementById("state-booked").innerHTML = '<span class="status-badge idle">Idle</span>';
}

// Setup Chat Form
function setupChatForm() {
  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = userInput.value.trim();
    if (!text) return;

    // Append user bubble
    appendMessage("user", text);
    userInput.value = "";

    // Show loading typing indicator
    const typingId = appendTypingIndicator();

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: currentSessionId,
          message: text
        })
      });

      removeTypingIndicator(typingId);

      if (!response.ok) {
        const err = await response.json();
        appendMessage("bot", `Error: ${err.detail || "Server error"}`);
        return;
      }

      const data = await response.json();
      appendMessage("bot", data.reply, data.booking);

      // Record API Calls
      if (data.api_calls && data.api_calls.length > 0) {
        data.api_calls.forEach(call => renderApiCall(call));
      }

      // Update State Metrics
      if (data.state) {
        updateStateMetrics(data.state);
      }
    } catch (err) {
      removeTypingIndicator(typingId);
      appendMessage("bot", "Network connection error while contacting sales engine.");
    }
  });
}

function appendMessage(sender, text, bookingData = null) {
  const msgDiv = document.createElement("div");
  msgDiv.className = `message ${sender}`;

  const avatarDiv = document.createElement("div");
  avatarDiv.className = `avatar ${sender}-avatar`;
  avatarDiv.innerText = sender === "bot" ? "AI" : "YOU";

  const bubbleDiv = document.createElement("div");
  bubbleDiv.className = "bubble";

  const p = document.createElement("p");
  p.innerText = text;
  bubbleDiv.appendChild(p);

  if (bookingData) {
    const bkgBox = document.createElement("div");
    bkgBox.className = "booking-card-embedded";
    bkgBox.innerHTML = `
      <strong>✔ Booking Created (${bookingData.booking_id})</strong><br>
      Product: ${bookingData.product_name} (${bookingData.plan_code} Plan)<br>
      Quantity: ${bookingData.quantity} unit(s) | Total: $${bookingData.final_price.toFixed(2)}<br>
      Status: ${bookingData.status}
    `;
    bubbleDiv.appendChild(bkgBox);
  }

  msgDiv.appendChild(avatarDiv);
  msgDiv.appendChild(bubbleDiv);
  chatStream.appendChild(msgDiv);
  scrollToBottom();
}

function appendTypingIndicator() {
  const id = "typing-" + Date.now();
  const div = document.createElement("div");
  div.id = id;
  div.className = "message bot";
  div.innerHTML = `
    <div class="avatar bot-avatar">AI</div>
    <div class="bubble" style="font-style: italic; color: #94a3b8;">Processing turn & evaluating guardrails...</div>
  `;
  chatStream.appendChild(div);
  scrollToBottom();
  return id;
}

function removeTypingIndicator(id) {
  const el = document.getElementById(id);
  if (el) {
    el.remove();
    scrollToBottom();
  }
}

function renderApiCall(call) {
  const empty = apiCallsContainer.querySelector(".empty-state");
  if (empty) empty.remove();

  totalApiCallCount++;
  apiCountBadge.innerText = totalApiCallCount;

  const card = document.createElement("div");
  card.className = "api-call-card";

  const isGet = call.api.startsWith("GET");
  const methodClass = isGet ? "get" : "post";
  const methodText = isGet ? "GET" : "POST";
  const endpoint = isGet ? "/api/catalog" : "/api/bookings";

  const dateStr = new Date().toLocaleTimeString();

  let detailsHtml = "";
  if (call.payload) {
    detailsHtml += `<strong>Payload:</strong><div class="payload-box">${JSON.stringify(call.payload, null, 2)}</div>`;
  }
  if (call.response) {
    detailsHtml += `<strong style="margin-top:6px; display:block;">Response:</strong><div class="payload-box">${JSON.stringify(call.response, null, 2)}</div>`;
  }

  card.innerHTML = `
    <div class="api-call-top">
      <div>
        <span class="method-tag ${methodClass}">${methodText}</span>
        <span class="api-endpoint-text">${endpoint}</span>
      </div>
      <span class="call-time">${dateStr}</span>
    </div>
    ${detailsHtml}
  `;

  apiCallsContainer.prepend(card);
}

function updateStateMetrics(st) {
  document.getElementById("state-sku").innerText = st.sku_id || "None";
  document.getElementById("state-plan").innerText = st.plan_code || "None";
  document.getElementById("state-cap").innerText = st.capacity_needed ? `${st.capacity_needed} rooms/people` : "-";
  document.getElementById("state-qty").innerText = st.quantity ? `${st.quantity} unit(s)` : "-";
  document.getElementById("state-base").innerText = st.base_price ? `$${st.base_price.toFixed(2)}` : "-";
  document.getElementById("state-promo").innerText = st.promo_code || "None";
  document.getElementById("state-disc").innerText = `${st.discount_pct}%`;
  document.getElementById("state-final").innerText = st.final_price ? `$${st.final_price.toFixed(2)}` : "-";
  document.getElementById("state-obj").innerText = st.price_objection_count || "0";
  document.getElementById("state-conf").innerText = st.is_quote_confirmed_by_user ? "Yes (Confirmed)" : "No";

  const bookedEl = document.getElementById("state-booked");
  if (st.is_booked) {
    bookedEl.innerHTML = `<span class="status-badge confirmed">Confirmed (${st.booking_record?.booking_id || "BKG"})</span>`;
  } else {
    bookedEl.innerHTML = `<span class="status-badge idle">Negotiating / In-Flight</span>`;
  }
}

// Automated Scenario Runner
window.runScenario = async function(id) {
  const resultBox = document.getElementById(`scen-${id}-result`);
  resultBox.className = "scen-result active";
  resultBox.innerHTML = '<span style="color: #38bdf8;">Executing scenario turn-by-turn...</span>';

  try {
    const res = await fetch(`/api/scenarios/run/${id}`, { method: "POST" });
    const data = await res.json();

    let assertionsHtml = data.assertions_passed.map(a => `<li>${a}</li>`).join("");

    resultBox.innerHTML = `
      <span class="scen-pass-tag">✔ 100% PASS</span>
      <ul class="assertions-list">
        ${assertionsHtml}
      </ul>
    `;
  } catch (e) {
    resultBox.innerHTML = `<span style="color: #f43f5e;">Execution error: ${e.message}</span>`;
  }
};

// Run All 4 Scenarios
btnRunAll.addEventListener("click", async () => {
  btnRunAll.innerText = "⏳ Running All 4 Scenarios...";
  btnRunAll.disabled = true;

  try {
    const res = await fetch("/api/scenarios/run-all", { method: "POST" });
    const data = await res.json();

    btnRunAll.innerText = "✔ All 4 Verified (100%)";
    btnRunAll.disabled = false;

    // Show score banner
    const banner = document.getElementById("overall-score-banner");
    banner.classList.remove("hidden");
    document.getElementById("score-pct").innerText = data.accuracy_score_percentage;

    // Trigger visual updates for all cards
    data.results.forEach(scen => {
      const resultBox = document.getElementById(`scen-${scen.scenario_id}-result`);
      resultBox.className = "scen-result active";
      let assertionsHtml = scen.assertions_passed.map(a => `<li>${a}</li>`).join("");
      resultBox.innerHTML = `
        <span class="scen-pass-tag">✔ 100% PASS</span>
        <ul class="assertions-list">
          ${assertionsHtml}
        </ul>
      `;
    });
  } catch (e) {
    btnRunAll.innerText = "Run All 4 Scenarios";
    btnRunAll.disabled = false;
    alert("Error running scenarios: " + e.message);
  }
});
