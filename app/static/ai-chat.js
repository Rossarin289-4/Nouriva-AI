(() => {
  const $ = (id) => document.getElementById(id);
  const POLICY_VERSION = "1.0";
  const CONSENT_TYPE = "external_ai_processing";
  let consentId = null;
  let sending = false;
  let statusData = null;

  async function api(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body ? {"Content-Type": "application/json"} : {}),
        ...(options.headers || {}),
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof data.detail === "string"
        ? data.detail
        : data.detail?.message
          || `คำขอไม่สำเร็จ (${response.status})`;
      const error = new Error(detail);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function notice(message) {
    $("aiChatNotice").textContent = message;
    $("aiChatNotice").classList.remove("hidden");
  }

  function addMessage(role, text, model = "") {
    const item = document.createElement("article");
    item.className = `ai-chat-message ${role}`;
    const label = document.createElement("small");
    label.textContent = role === "user" ? "คุณ" : `AI${model ? ` · ${model}` : ""}`;
    const body = document.createElement("div");
    body.textContent = text;
    item.append(label, body);
    $("aiChatMessages").appendChild(item);
    $("aiChatMessages").scrollTop = $("aiChatMessages").scrollHeight;
    return item;
  }

  function showConsent() {
    $("aiChatConsentPanel").classList.remove("hidden");
    $("aiChatWorkspace").classList.add("hidden");
    $("aiChatConsentCheck").checked = false;
    $("aiChatConsentButton").disabled = true;
  }

  function showWorkspace() {
    $("aiChatConsentPanel").classList.add("hidden");
    $("aiChatWorkspace").classList.remove("hidden");
  }

  function providerLabel(provider) {
    return provider === "gemini" ? "Google Gemini" : "OpenAI";
  }

  function renderQuota() {
    const provider = $("aiChatProvider").value;
    const item = statusData?.providers?.[provider];
    if (!item) {
      $("aiChatQuota").textContent = "ยังโหลดสถานะโควตาไม่ได้";
      $("aiChatSend").disabled = true;
      return;
    }

    if (item.configured === false) {
      $("aiChatQuota").textContent =
        providerLabel(provider) + " ยังไม่ได้ตั้งค่า API key หรือ model ในเซิร์ฟเวอร์";
      $("aiChatSend").disabled = true;
      return;
    }

    if (item.quota_enforced === false) {
      $("aiChatQuota").textContent = "ไม่มีโควตาที่แอปกำหนดรายวัน ทั้งนี้ยังขึ้นกับข้อจำกัดของผู้ให้บริการ";
      $("aiChatSend").disabled = sending;
      return;
    }

    if (item.daily_limit == null) {
      $("aiChatQuota").textContent = "ยังไม่เปิดใช้โควตาสำหรับแผนนี้";
      $("aiChatSend").disabled = true;
      return;
    }

    const remaining = item.remaining ?? 0;
    $("aiChatQuota").textContent =
      `ใช้แล้ว ${item.used ?? 0}/${item.daily_limit} ข้อความ · เหลือ ${remaining} ข้อความ · รีเซ็ตเวลา 00:00 น. (เวลาไทย)`;
    $("aiChatSend").disabled = sending || remaining <= 0;
  }

  async function loadStatus() {
    const data = await api("/ai-chat/status");
    statusData = data;
    $("aiChatPlan").textContent = data.plan === "premium" ? "Premium" : "Free";
    renderQuota();
    showWorkspace();
    notice("ตรวจสอบสถานะ AI Chat แล้ว โปรดดูความพร้อมของผู้ให้บริการก่อนส่งข้อความ");
  }

  async function findConsent() {
    const data = await api("/consents");
    const consents = data.consents || [];
    const match = consents.find((item) =>
      item.consent_type === CONSENT_TYPE &&
      item.policy_version === POLICY_VERSION &&
      !item.withdrawn_at &&
      item.consent_metadata?.purpose === "ai_chat"
    );

    if (!match) return false;
    consentId = match.consent_id;
    return true;
  }

  async function initialise() {
    try {
      const auth = await api("/auth/me");
      if (!auth.user) throw new Error("กรุณาเข้าสู่ระบบก่อนใช้ AI Chat");
      if (await findConsent()) {
        await loadStatus();
      } else {
        showConsent();
        notice("อ่านรายละเอียดและกดยินยอมก่อนเริ่มใช้ AI Chat");
      }
    } catch (error) {
      showConsent();
      $("aiChatConsentButton").disabled = true;
      notice(error.status === 401
        ? "กรุณาเข้าสู่ระบบก่อนให้ความยินยอมและใช้ AI Chat"
        : `ยังเปิด AI Chat ไม่ได้: ${error.message}`);
    }
  }

  $("aiChatConsentCheck").addEventListener("change", (event) => {
    $("aiChatConsentButton").disabled = !event.target.checked;
  });

  $("aiChatConsentButton").addEventListener("click", async () => {
    if (!$("aiChatConsentCheck").checked) return;
    const button = $("aiChatConsentButton");
    button.disabled = true;
    try {
      const result = await api("/consents", {
        method: "POST",
        body: JSON.stringify({
          consent_type: CONSENT_TYPE,
          policy_version: POLICY_VERSION,
          consent_metadata: {
            purpose: "ai_chat",
            disclosure: "Only the user-typed message is sent to the selected AI provider.",
            providers: ["gemini", "openai"]
          }
        })
      });
      consentId = result.consent.consent_id;
      await loadStatus();
    } catch (error) {
      notice(`บันทึกความยินยอมไม่สำเร็จ: ${error.message}`);
      button.disabled = !$("aiChatConsentCheck").checked;
    }
  });

  $("aiChatProvider").addEventListener("change", renderQuota);

  $("aiChatForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (sending || !consentId) return;
    const message = $("aiChatInput").value.trim();
    if (!message) return;

    const provider = $("aiChatProvider").value;
    sending = true;
    $("aiChatSend").disabled = true;
    addMessage("user", message);
    $("aiChatInput").value = "";
    const pending = addMessage("assistant", "กำลังรอคำตอบ...");
    try {
      const result = await api("/ai-chat", {
        method: "POST",
        body: JSON.stringify({provider, message})
      });
      pending.remove();
      addMessage("assistant", result.message, result.model || "");
      let successNotice = result.usage?.status_recorded === false
        ? "ได้รับคำตอบแล้ว แต่บันทึกสถานะโควตาไม่สำเร็จ โปรดตรวจสอบก่อนส่งข้อความเพิ่ม"
        : "ได้รับคำตอบแล้ว";

      try {
        await loadStatus();
        notice(successNotice);
      } catch (_) {
        notice(`${successNotice} แต่โหลดสถานะโควตาล่าสุดไม่สำเร็จ`);
      }
    } catch (error) {
      pending.remove();
      addMessage("assistant", `ส่งไม่สำเร็จ: ${error.message}`);
      if (error.status === 403) {
        consentId = null;
        statusData = null;
        showConsent();
        notice(`ต้องยืนยันความยินยอมอีกครั้ง: ${error.message}`);
      } else {
        notice(`ไม่สามารถส่งข้อความได้: ${error.message}`);
        try {
          await loadStatus();
        } catch (_) {
          // Keep the original send error visible if status refresh also fails.
        }
      }
    } finally {
      sending = false;
      renderQuota();
    }
  });

  $("aiChatWithdraw").addEventListener("click", async () => {
    if (!consentId) return;
    if (!window.confirm("ต้องการถอนความยินยอมและปิด AI Chat ใช่หรือไม่?")) return;
    const button = $("aiChatWithdraw");
    button.disabled = true;
    try {
      await api(`/consents/${encodeURIComponent(consentId)}/withdraw`, {method: "POST"});
      consentId = null;
      statusData = null;
      $("aiChatMessages").replaceChildren();
      showConsent();
      notice("ถอนความยินยอมแล้ว ระบบจะไม่ส่งข้อความใหม่จนกว่าคุณจะยินยอมอีกครั้ง");
    } catch (error) {
      notice(`ถอนความยินยอมไม่สำเร็จ: ${error.message}`);
    } finally {
      button.disabled = false;
    }
  });

  initialise();
})();
