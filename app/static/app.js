
const $ = (id) => document.getElementById(id);

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function escapeHTML(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    '"': "&quot;", "'": "&#39;"
  })[char]);
}

function setStatus(id, message, ok) {
  $(id).textContent = message;
  $(id).style.color = ok ? "#076653" : "#B4533C";
}

function setDashboardGreeting(name = "") {
  const heading = $("dashboardGreeting");
  const mascot = document.createElement("span");
  mascot.textContent = "🌱";
  mascot.setAttribute("aria-hidden", "true");
  heading.replaceChildren(
    document.createTextNode(name ? `สวัสดี ${name}! วันนี้` : "สวัสดี! วันนี้"),
    document.createElement("br"),
    document.createTextNode("เรามาดูแลตัวเองกัน "),
    mascot
  );
}

function updateDashboardDateTime() {
  const formatter = new Intl.DateTimeFormat("th-TH", {
    timeZone: "Asia/Bangkok",
    dateStyle: "full",
    timeStyle: "short",
  });
  $("dashboardDateTime").textContent = formatter.format(new Date());
}

function setLoggedOutState(message = "ยังไม่ได้เข้าสู่ระบบ") {
  $("authStatus").textContent = message;
  $("loginNav").classList.remove("hidden");
  $("profileNav").classList.add("hidden");
  $("logoutButton").classList.add("hidden");
  setDashboardGreeting();
  renderDashboardMeals({ state: "unauthenticated" });
}

async function loadAuthenticationStatus() {
  try {
    const response = await fetch("/auth/me", { credentials: "same-origin" });
    const data = await response.json().catch(() => ({}));
    if (response.status === 401) {
      setLoggedOutState();
      return;
    }
    if (!response.ok || !data.user) {
      throw new Error("ตรวจสอบบัญชีไม่สำเร็จ");
    }

    const displayName = data.user.profile?.display_name || data.user.email || "บัญชีผู้ใช้";
    $("authStatus").textContent = `เข้าสู่ระบบ: ${displayName}`;
    setDashboardGreeting(displayName);
    $("loginNav").classList.add("hidden");
    $("profileNav").classList.remove("hidden");
    $("logoutButton").classList.remove("hidden");
  } catch (error) {
    setLoggedOutState("ตรวจสอบสถานะบัญชีไม่ได้");
  }
}

function formatDashboardMealDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!match) return "ไม่ระบุวันที่";
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12));
  return new Intl.DateTimeFormat("th-TH", { timeZone: "Asia/Bangkok", dateStyle: "medium" }).format(date);
}

function renderDashboardMeals(detail = {}) {
  const message = $("dashboardMealsMessage");
  const list = $("dashboardRecentMeals");
  const state = detail.state || "loading";
  list.replaceChildren();
  message.className = "dashboard-meals-message";
  message.setAttribute("aria-busy", state === "loading" ? "true" : "false");

  const messages = {
    loading: "กำลังโหลดมื้ออาหาร...",
    unauthenticated: "เข้าสู่ระบบเพื่อดูมื้ออาหารส่วนตัวของคุณ",
    empty: "ยังไม่มีมื้ออาหารที่บันทึกไว้ เริ่มบันทึกมื้อแรกของคุณได้เลย",
    error: "โหลดมื้ออาหารไม่สำเร็จ ลองอีกครั้งได้",
  };
  if (state !== "success") {
    message.textContent = messages[state] || messages.error;
    if (state === "unauthenticated") {
      const login = document.createElement("a");
      login.href = "/login";
      login.className = "welcome-secondary-action";
      login.textContent = "เข้าสู่ระบบ";
      list.appendChild(login);
    } else if (state === "empty") {
      const link = document.createElement("a");
      link.href = "#myMeals";
      link.className = "welcome-secondary-action";
      link.textContent = "บันทึกมื้ออาหาร";
      list.appendChild(link);
    } else if (state === "error") {
      message.classList.add("error");
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "secondary-button";
      retry.textContent = "ลองอีกครั้ง";
      retry.addEventListener("click", () => window.loadMealHistory?.());
      list.appendChild(retry);
    }
    return;
  }

  const items = Array.isArray(detail.items) ? detail.items.slice(0, 3) : [];
  if (!items.length) {
    renderDashboardMeals({ state: "empty" });
    return;
  }
  message.textContent = detail.dateFilter
    ? "มื้ออาหารในวันที่เลือก"
    : "มื้ออาหารล่าสุดจาก Food Diary";
  items.forEach((meal) => {
    const row = document.createElement("li");
    row.className = "dashboard-recent-meal";
    const title = document.createElement("strong");
    title.textContent = meal.title || ({ breakfast: "อาหารเช้า", lunch: "อาหารกลางวัน", dinner: "อาหารเย็น", snack: "ของว่าง", other: "อื่น ๆ" }[meal.meal_type] || meal.meal_type || "มื้ออาหาร");
    const date = document.createElement("small");
    date.textContent = formatDashboardMealDate(meal.meal_date);
    row.append(title, date);
    list.appendChild(row);
  });
}

window.addEventListener("nouriva:meal-history", (event) => {
  renderDashboardMeals(event.detail || {});
});

$("logoutButton").addEventListener("click", async () => {
  const button = $("logoutButton");
  button.disabled = true;
  button.textContent = "กำลังออกจากระบบ...";
  try {
    const response = await fetch("/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });
    if (!response.ok) throw new Error("ออกจากระบบไม่สำเร็จ");
    setLoggedOutState("ออกจากระบบแล้ว");
    if (typeof window.loadMealHistory === "function") {
      await window.loadMealHistory();
    }
    if (typeof window.refreshNutritionSummary === "function") {
      await window.refreshNutritionSummary();
    }
  } catch (error) {
    $("authStatus").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "ออกจากระบบ";
  }
});

updateDashboardDateTime();
setInterval(updateDashboardDateTime, 60 * 1000);
loadAuthenticationStatus();

function ruleStatusClass(status) {
  if (status === "active") return "good";
  if (["draft", "reviewed", "needs_review",
       "needs_expert_review", "needs_design"].includes(status)) {
    return "review";
  }
  return "neutral";
}

async function loadDashboard() {
  $("refreshBtn").disabled = true;
  $("refreshBtn").textContent = "…";

  setStatus("apiStatus", "กำลังตรวจสอบ", true);
  setStatus("dbStatus", "กำลังตรวจสอบ", true);

  const results = await Promise.allSettled([
    getJSON("/health/db"),
    getJSON("/rules"),
    getJSON("/foods?limit=100"),
    getJSON("/rules/NUT-001")
  ]);

  // หน้าเว็บโหลดจาก FastAPI อยู่ จึงเข้าถึง Backend ได้
  setStatus("apiStatus", "Online", true);

  const [dbResult, rulesResult, foodsResult, nutResult] = results;

  if (dbResult.status === "fulfilled" &&
      dbResult.value.database === "connected") {
    setStatus("dbStatus", "Connected", true);
  } else {
    setStatus("dbStatus", "Disconnected", false);
  }

  if (rulesResult.status === "fulfilled") {
    const data = rulesResult.value;
    const count = data.count ??
      data.items?.length ??
      data.rules?.length;

    $("ruleCount").textContent = count ?? "—";
  } else {
    $("ruleCount").textContent = "โหลดไม่ได้";
  }

  if (foodsResult.status === "fulfilled") {
    const data = foodsResult.value;
    $("foodCount").textContent = data.count ?? 0;
    renderFoods(data.items ?? []);
  } else {
    $("foodCount").textContent = "โหลดไม่ได้";
    $("foodMessage").textContent = "โหลดรายการอาหารไม่สำเร็จ";
  }

  if (nutResult.status === "fulfilled") {
    const data = nutResult.value;
    const rule = data.item ?? data.rule ?? data;
    const status = rule.lifecycle_status ?? "ไม่พบสถานะ";

    $("nutRuleStatus").textContent = status;
    $("nutRuleStatus").className =
      `pill ${ruleStatusClass(status)}`;
  } else {
    $("nutRuleStatus").textContent = "โหลดไม่ได้";
    $("nutRuleStatus").className = "pill neutral";
  }

  $("refreshBtn").disabled = false;
  $("refreshBtn").textContent = "↻";
}

function renderFoods(items) {
  const results = $("foodResults");
  results.innerHTML = "";

  if (!items.length) {
    $("foodMessage").textContent =
      "ไม่พบอาหาร ลองค้นหาด้วยชื่ออื่น";
    return;
  }

  $("foodMessage").textContent = `พบ ${items.length} รายการ`;

  items.forEach((food) => {
    const name = food.name_th || food.name_en || "ไม่ระบุชื่อ";
    const status = food.verification_status || "unverified";
    // Food-item verification statuses are constrained by the database to
    // reviewed/source_verified before they can be presented as trusted.
    const isVerified = ["reviewed", "source_verified"].includes(status);

    const row = document.createElement("article");
    row.className = "food-item";

    row.innerHTML = `
      <div class="food-info">
        <div class="food-thumb">🥑</div>
        <div>
          <strong>${escapeHTML(name)}</strong>
          <p>${escapeHTML(food.brand_name || food.item_type || "อาหาร")}</p>
          <span class="pill ${isVerified ? "good" : "review"}">
            ${escapeHTML(status)}
          </span>
        </div>
      </div>
      <button type="button">ดูสารอาหาร →</button>
    `;

    row.querySelector("button").addEventListener("click", () => {
      loadNutrition(food.food_id, name);
    });

    results.appendChild(row);
  });
}

async function searchFoods(search) {
  $("foodMessage").textContent = "กำลังค้นหา...";
  $("foodResults").innerHTML = "";
  $("nutritionPanel").classList.add("hidden");

  try {
    const params = new URLSearchParams({ limit: "100" });
    if (search.trim()) params.set("search", search.trim());

    const data = await getJSON(`/foods?${params}`);
    $("foodCount").textContent = data.count ?? 0;
    renderFoods(data.items ?? []);
  } catch (error) {
    $("foodMessage").textContent =
      `ค้นหาไม่สำเร็จ: ${error.message}`;
  }
}

async function calculateFoodNutrition(foodId, foodName) {
  const panel = $("nutritionPanel");
  const weightInput = $("eatenWeightInput");
  const message = $("calculationMessage");
  const button = $("calculateNutritionBtn");

  // ล้างผลคำนวณเก่าก่อนตรวจเงื่อนไข เพื่อไม่ให้ผลเดิมค้าง
  const oldResult = $("consumedNutritionResult");
  if (oldResult) oldResult.remove();

  // ป้องกันการเรียก API หากกฎหรือข้อมูลยังไม่ผ่านเงื่อนไข
  if (!button || button.dataset.canCalculate !== "true") {
    if (message) {
      message.textContent =
        "ยังคำนวณไม่ได้: กฎหรือข้อมูลโภชนาการยังไม่ผ่านเงื่อนไขการตรวจสอบ";
    }
    return;
  }

  const weight = Number(weightInput?.value);

  if (!Number.isFinite(weight) || weight <= 0) {
    message.textContent = "กรุณากรอกน้ำหนักที่มากกว่า 0 กรัม";
    return;
  }

  button.disabled = true;
  message.textContent = "กำลังตรวจสอบข้อมูลและคำนวณ...";

  try {
    const response = await fetch("/nutrition/calculate-from-food", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        food_id: foodId,
        eaten_weight_g: weight
      })
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }

    if (data.status === "rule_not_active") {
      message.textContent =
        `ยังคำนวณไม่ได้: กฎ ${data.rule_code || "NUT-001"} ` +
        `ยังมีสถานะ ${data.lifecycle_status || "ไม่เปิดใช้งาน"} ` +
        "จึงยังไม่แสดงผลสารอาหารที่ได้รับ";
      return;
    }

    if (data.status === "data_needs_review") {
      message.textContent =
        "ยังคำนวณไม่ได้: ข้อมูลอาหารหรือข้อมูลโภชนาการยังไม่ผ่านการตรวจสอบ";
      return;
    }

    if (data.status !== "calculated") {
      message.textContent = data.message || "ยังไม่สามารถคำนวณได้";
      return;
    }

    message.textContent = data.message || "คำนวณสารอาหารสำเร็จ";

    const nutrients = Array.isArray(data.nutrients) ? data.nutrients : [];

    if (!nutrients.length) {
      message.textContent = "ไม่พบรายการสารอาหารที่คำนวณได้";
      return;
    }

    const result = document.createElement("div");
    result.id = "consumedNutritionResult";

    const heading = document.createElement("h4");
    heading.textContent =
      `สารอาหารที่ได้รับจาก ${foodName} (${data.eaten_weight_g} กรัม)`;
    result.appendChild(heading);

    const wrapper = document.createElement("div");
    wrapper.style.overflowX = "auto";

    const table = document.createElement("table");
    table.className = "nutrition-table";

    const thead = document.createElement("thead");
    const headerRow = document.createElement("tr");

    ["สารอาหาร", "ปริมาณที่ได้รับ", "หน่วย"].forEach((label) => {
      const th = document.createElement("th");
      th.textContent = label;
      headerRow.appendChild(th);
    });

    thead.appendChild(headerRow);

    const tbody = document.createElement("tbody");

    nutrients.forEach((item) => {
      const row = document.createElement("tr");

      const nameCell = document.createElement("td");
      nameCell.textContent =
        item.name_th || item.name_en || item.nutrient_code || "ไม่ระบุ";

      const amountCell = document.createElement("td");
      amountCell.textContent = String(item.consumed);

      const unitCell = document.createElement("td");
      unitCell.textContent = item.unit || "";

      row.append(nameCell, amountCell, unitCell);
      tbody.appendChild(row);
    });

    table.append(thead, tbody);
    wrapper.appendChild(table);
    result.appendChild(wrapper);

    const ruleNote = document.createElement("p");
    ruleNote.className = "notice";
    ruleNote.textContent =
      `คำนวณตามกฎ ${data.rule?.rule_code || "ไม่ระบุ"} ` +
      `(${data.rule?.lifecycle_status || "ไม่ระบุ"}) ` +
      `โดยใช้ข้อมูลที่ระบบอนุญาตให้คำนวณ`;
    result.appendChild(ruleNote);

    message.insertAdjacentElement("afterend", result);
  } catch (error) {
    message.textContent = `คำนวณไม่สำเร็จ: ${error.message}`;
  } finally {
    // ไม่เปิดปุ่ม หากข้อมูลหรือกฎยังไม่ผ่านเงื่อนไข
    button.disabled = button.dataset.canCalculate !== "true";
  }
}

async function loadNutrition(foodId, foodName) {
  const panel = $("nutritionPanel");
  panel.classList.remove("hidden");
  panel.innerHTML = "<p>กำลังโหลดสารอาหาร...</p>";

  try {
    const data = await getJSON(
      `/foods/${encodeURIComponent(foodId)}/nutrition`
    );
    const rows = data.nutrition ?? [];

    const table = rows.length ? `
      <div style="overflow-x:auto">
        <table class="nutrition-table">
          <thead>
            <tr>
              <th>สารอาหาร</th>
              <th>ปริมาณ</th>
              <th>หน่วย</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((item) => `
              <tr>
                <td>${escapeHTML(
                  item.nutrient_name_th ||
                  item.nutrient_name_en ||
                  item.nutrient_code
                )}</td>
                <td>${escapeHTML(item.amount)}</td>
                <td>${escapeHTML(item.nutrient_unit)}</td>
              </tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    ` : "<p>ยังไม่มีข้อมูลสารอาหาร</p>";

    const basis = rows[0];
    const source = data.source || {};
    const sourceUrl = source.source_url || "";
    const safeSourceUrl = /^https:\/\//i.test(sourceUrl)
      ? sourceUrl
      : "";
    const sourceDetails = `
      <section class="notice" aria-label="แหล่งข้อมูลสารอาหาร">
        <h4>แหล่งข้อมูลและการตรวจสอบ</h4>
        <p>
          แหล่งข้อมูล:
          ${escapeHTML(source.source_name || source.source_code || "ไม่ระบุ")}
        </p>
        <p>
          รหัสระเบียน:
          ${escapeHTML(source.source_record_id || "ไม่ระบุ")}
        </p>
        <p>
          สถานะข้อมูลโภชนาการ:
          ${escapeHTML(source.verification_status || "ไม่ระบุ")}
        </p>
        ${
          safeSourceUrl
            ? `<p><a href="${escapeHTML(safeSourceUrl)}"
                 target="_blank" rel="noopener noreferrer">
                 เปิดเอกสารแหล่งข้อมูล
               </a></p>`
            : "<p>ยังไม่มี URL แหล่งข้อมูลสำหรับรายการนี้</p>"
        }
        ${
          source.license_or_attribution
            ? `<p>ข้อกำหนดการอ้างอิง: ${
                escapeHTML(source.license_or_attribution)
              }</p>`
            : ""
        }
        ${
          source.notes
            ? `<p>หมายเหตุ: ${escapeHTML(source.notes)}</p>`
            : ""
        }
      </section>
    `;

    const trustedStatuses = ["reviewed", "source_verified"];
    const basisStatus = basis?.verification_status || "ไม่ระบุ";
    const isTrustedBasis = trustedStatuses.includes(basisStatus);
    const foodStatus = data.food?.verification_status || "ไม่ระบุ";
    const trustedFood = trustedStatuses.includes(foodStatus);

    let nutritionRuleActive = false;
    let nutritionRuleStatus = "ตรวจสอบไม่ได้";

    try {
      const ruleData = await getJSON("/rules/NUT-001");
      nutritionRuleStatus = ruleData.lifecycle_status || "ไม่ระบุ";
      nutritionRuleActive = nutritionRuleStatus === "active";
    } catch (ruleError) {
      nutritionRuleActive = false;
    }

    const canCalculate =
      isTrustedBasis && trustedFood && nutritionRuleActive;

    const nutritionWarning = rows.length && (!isTrustedBasis || !trustedFood)
      ? `
        <div class="notice" role="alert">
          <strong>ข้อมูลอาหารหรือสารอาหารยังไม่ผ่านการตรวจสอบ</strong>
          <p>
            สถานะอาหาร: ${escapeHTML(foodStatus)}<br>
            สถานะฐานโภชนาการ: ${escapeHTML(basisStatus)}<br>
            ตัวเลขในตารางเป็นข้อมูลอ้างอิงจากฐานข้อมูล
            ไม่ใช่ผลคำนวณจากน้ำหนักอาหารที่รับประทาน
            โปรดตรวจสอบแหล่งอ้างอิงก่อนนำไปใช้งานจริง
          </p>
        </div>
      `
      : "";

    let portionItems = [];
    let portionLoadMessage = "กำลังโหลดหน่วยบริโภค...";

    try {
      const portionData = await getJSON(
        `/foods/${encodeURIComponent(foodId)}/portions`
      );
      portionItems = Array.isArray(portionData.items)
        ? portionData.items
        : [];
      portionLoadMessage = portionItems.length
        ? "เลือกหน่วยบริโภคเพื่อเติมน้ำหนักโดยประมาณ"
        : "ยังไม่มีหน่วยบริโภคที่ผ่านการตรวจสอบ คุณสามารถกรอกน้ำหนักเป็นกรัมได้";
    } catch (portionError) {
      portionLoadMessage =
        "โหลดหน่วยบริโภคไม่ได้ คุณยังสามารถกรอกน้ำหนักเป็นกรัมได้";
    }

    const portionOptions = portionItems.map((item) => {
      const label = [
        item.portion_name_th || item.portion_name_en || item.unit_name,
        `${item.weight_g} กรัม`
      ].filter(Boolean).join(" — ");

      return `
        <option value="${escapeHTML(item.weight_g)}">
          ${escapeHTML(label)}
        </option>
      `;
    }).join("");

    panel.innerHTML = `
      <h3>${escapeHTML(foodName)}</h3>
      ${nutritionWarning}
      <p class="subtext">
        ข้อมูลต่อ ${escapeHTML(basis?.basis_quantity ?? "—")}
        ${escapeHTML(basis?.basis_unit ?? "")}
      </p>
      ${table}
      ${sourceDetails}
      <div class="calculation-form">
        <label for="portionSelect">หน่วยบริโภคที่มีข้อมูลตรวจสอบแล้ว</label>
        <select id="portionSelect">
          <option value="">กรอกน้ำหนักเอง</option>
          ${portionOptions}
        </select>
        <p id="portionMessage" class="message" aria-live="polite">
          ${escapeHTML(portionLoadMessage)}
        </p>

        <label for="eatenWeightInput">น้ำหนักอาหารที่รับประทาน (กรัม)</label>
        <div class="barcode-input-row">
          <input
            id="eatenWeightInput"
            type="number"
            min="0.1"
            step="any"
            value="100"
            aria-label="น้ำหนักอาหารที่รับประทานเป็นกรัม"
          >
          <button
            id="calculateNutritionBtn"
            type="button"
            data-can-calculate="${String(canCalculate)}"
            ${canCalculate ? "" : "disabled"}
          >
            คำนวณสารอาหารที่ได้รับ
          </button>
        </div>
        <p id="calculationMessage" class="message" aria-live="polite">
          ${!nutritionRuleActive
            ? `ยังคำนวณไม่ได้: กฎ NUT-001 มีสถานะ ${escapeHTML(nutritionRuleStatus)}`
            : !trustedFood || !isTrustedBasis
              ? "ยังคำนวณไม่ได้: ข้อมูลอาหารหรือข้อมูลโภชนาการยังไม่ผ่านการตรวจสอบ"
              : "กรอกน้ำหนักแล้วกดคำนวณ"}
        </p>
      </div>
      <p class="notice">
        สถานะข้อมูล: ${escapeHTML(
          basis?.verification_status ?? "ไม่ระบุ"
        )} — โปรดตรวจสอบกับแหล่งข้อมูลก่อนใช้งานจริง
      </p>
    `;

    $("portionSelect").addEventListener("change", (event) => {
      const selectedWeight = Number(event.target.value);
      if (Number.isFinite(selectedWeight) && selectedWeight > 0) {
        $("eatenWeightInput").value = String(selectedWeight);
      }
    });

    $("calculateNutritionBtn").addEventListener("click", () => {
      calculateFoodNutrition(foodId, foodName);
    });

    $("eatenWeightInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        if (!canCalculate) {
          $("calculationMessage").textContent =
            "ยังคำนวณไม่ได้: โปรดตรวจสอบสถานะกฎและข้อมูลโภชนาการก่อน";
          return;
        }
        calculateFoodNutrition(foodId, foodName);
      }
    });

    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    panel.innerHTML =
      `<p>โหลดข้อมูลไม่สำเร็จ: ${escapeHTML(error.message)}</p>`;
  }
}

$("searchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  searchFoods($("searchInput").value);
});

$("refreshBtn").addEventListener("click", () => {
  loadDashboard();
  loadAuthenticationStatus();
  if (typeof window.loadMealHistory === "function") window.loadMealHistory();
});

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => {
    document.querySelectorAll(".nav-item")
      .forEach((nav) => {
        nav.classList.remove("active");
        nav.removeAttribute("aria-current");
      });
    item.classList.add("active");
    item.setAttribute("aria-current", "page");
  });
});



let barcodeLookupRequest = 0;

function appendExternalFoodDiaryAction(container, externalData, barcode) {
  const item = externalData.item || {};
  const source = externalData.source || {};
  const panel = document.createElement("section");
  panel.className = "barcode-diary-panel";
  const heading = document.createElement("h4");
  heading.textContent = "เพิ่มสินค้าลง Food Diary";
  const safety = document.createElement("p");
  safety.className = "notice";
  safety.textContent = "ข้อมูลจาก Open Food Facts ยังไม่ผ่านการตรวจสอบ จะบันทึกเป็นรายการ unverified และไม่ใช้คำนวณสารอาหาร";
  const openButton = document.createElement("button");
  openButton.type = "button";
  openButton.className = "primary-button";
  openButton.textContent = "เพิ่มลงมื้ออาหาร";
  const message = document.createElement("p");
  message.className = "message";
  message.setAttribute("role", "status");
  message.setAttribute("aria-live", "polite");
  const form = document.createElement("form");
  form.className = "barcode-diary-form hidden";
  // This form contains required fields inside a conditionally hidden "new meal"
  // section. Native validation blocks submit events for those hidden controls,
  // so validate explicitly in the submit handler and show an inline message.
  form.noValidate = true;
  const createMealPanel = document.createElement("div");
  createMealPanel.className = "barcode-new-meal hidden";
  const meals = new Map();
  let saving = false;
  let creatingMeal = false;
  let added = false;

  const appendField = (parent, labelText, input, id) => {
    const field = document.createElement("div");
    field.className = "meal-field";
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = labelText;
    input.id = id;
    field.append(label, input);
    parent.appendChild(field);
  };
  const makeSelect = (id, placeholder, options) => {
    const select = document.createElement("select");
    select.id = id;
    select.required = true;
    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = placeholder;
    empty.disabled = true;
    empty.selected = true;
    select.appendChild(empty);
    options.forEach(([value, text]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      select.appendChild(option);
    });
    return select;
  };
  const requestJSON = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(typeof body.detail === "string"
        ? body.detail
        : `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return body;
  };
  const mealLabel = (meal) => {
    const types = {
      breakfast: "อาหารเช้า", lunch: "อาหารกลางวัน", dinner: "อาหารเย็น",
      snack: "ของว่าง", other: "อื่น ๆ",
    };
    const title = meal.title || types[meal.meal_type] || meal.meal_type || "มื้ออาหาร";
    return `${title} · ${meal.meal_date || "ไม่ระบุวันที่"}`;
  };
  const mealsSelect = makeSelect("barcodeTargetMeal", "เลือกมื้ออาหาร", []);
  const mealOptions = document.createElement("div");
  mealOptions.className = "barcode-meal-options meal-form-grid";
  appendField(mealOptions, "มื้ออาหาร", mealsSelect, "barcodeTargetMeal");
  const newMealDate = document.createElement("input");
  newMealDate.type = "date";
  newMealDate.required = true;
  const nowParts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Bangkok", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const dateParts = Object.fromEntries(nowParts.map(({ type, value }) => [type, value]));
  newMealDate.value = `${dateParts.year}-${dateParts.month}-${dateParts.day}`;
  const newMealType = makeSelect("barcodeNewMealType", "เลือกประเภทมื้อ", [
    ["breakfast", "อาหารเช้า"], ["lunch", "อาหารกลางวัน"],
    ["dinner", "อาหารเย็น"], ["snack", "ของว่าง"], ["other", "อื่น ๆ"],
  ]);
  const newMealTime = document.createElement("input");
  newMealTime.type = "time";
  const newMealTitle = document.createElement("input");
  newMealTitle.type = "text";
  newMealTitle.maxLength = 200;
  appendField(createMealPanel, "วันที่ (เวลาไทย)", newMealDate, "barcodeNewMealDate");
  appendField(createMealPanel, "ประเภทมื้อ", newMealType, "barcodeNewMealType");
  appendField(createMealPanel, "เวลา (ถ้ามี)", newMealTime, "barcodeNewMealTime");
  appendField(createMealPanel, "ชื่อมื้อ (ถ้ามี)", newMealTitle, "barcodeNewMealTitle");
  const createMealButton = document.createElement("button");
  createMealButton.type = "button";
  createMealButton.className = "secondary-button";
  createMealButton.textContent = "สร้างมื้ออาหาร";
  createMealPanel.appendChild(createMealButton);

  const quantity = document.createElement("input");
  quantity.type = "number";
  quantity.min = "0.001";
  quantity.step = "0.001";
  quantity.inputMode = "decimal";
  quantity.required = true;
  const unit = makeSelect("barcodeQuantityUnit", "เลือกหน่วย", [
    ["g", "กรัม"], ["ml", "มิลลิลิตร"], ["piece", "ชิ้น"],
    ["serving", "หน่วยบริโภค"], ["package", "แพ็ก"],
  ]);
  const quantityFields = document.createElement("div");
  quantityFields.className = "meal-form-grid";
  appendField(quantityFields, "ปริมาณที่รับประทาน", quantity, "barcodeQuantity");
  appendField(quantityFields, "หน่วย", unit, "barcodeQuantityUnit");
  const notes = document.createElement("textarea");
  notes.maxLength = 2000;
  notes.rows = 2;
  appendField(quantityFields, "บันทึกเพิ่มเติม (ถ้ามี)", notes, "barcodeItemNotes");
  const review = document.createElement("div");
  review.className = "barcode-confirmation-summary";
  review.setAttribute("aria-live", "polite");
  const confirmationLabel = document.createElement("label");
  confirmationLabel.className = "barcode-confirmation-label";
  const confirmation = document.createElement("input");
  confirmation.type = "checkbox";
  confirmation.required = true;
  const confirmationText = document.createElement("span");
  confirmationText.textContent = "ตรวจสอบชื่อมื้อ ปริมาณ และหน่วยแล้ว ยืนยันเพิ่มรายการนี้";
  confirmationLabel.append(confirmation, confirmationText);
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "primary-button";
  submit.textContent = "ยืนยันและบันทึกลง Food Diary";
  submit.disabled = true;
  form.append(mealOptions, createMealPanel, quantityFields, review, confirmationLabel, submit);
  panel.append(heading, safety, openButton, message, form);
  container.appendChild(panel);

  const refreshSummary = () => {
    review.replaceChildren();
    const meal = meals.get(mealsSelect.value);
    const amount = Number(quantity.value);
    const unitText = unit.selectedOptions[0]?.textContent || "ยังไม่เลือกหน่วย";
    [
      `สินค้า: ${item.name || "ไม่ระบุชื่อ"}${item.brand_name ? ` · ${item.brand_name}` : ""}`,
      `Barcode: ${barcode}`,
      `มื้อ: ${meal ? mealLabel(meal) : "ยังไม่เลือกมื้ออาหาร"}`,
      `ปริมาณที่กิน: ${Number.isFinite(amount) && amount > 0 ? `${amount} ${unitText}` : "ยังไม่ระบุ"}`,
      "สถานะข้อมูล: external_unverified · รายการจะรอตรวจสอบ",
    ].forEach((text) => {
      const line = document.createElement("p");
      line.textContent = text;
      review.appendChild(line);
    });
    submit.disabled = added || saving;
  };

  openButton.addEventListener("click", async () => {
    if (saving || added || container.dataset.barcode !== barcode) return;
    openButton.disabled = true;
    message.textContent = "กำลังโหลดมื้ออาหารของคุณ...";
    try {
      const data = await requestJSON("/meals?limit=100&offset=0");
      if (container.dataset.barcode !== barcode) return;
      if (!Array.isArray(data.items)) throw new Error("รูปแบบรายการมื้ออาหารไม่ถูกต้อง");
      mealsSelect.replaceChildren();
      const blank = document.createElement("option");
      blank.value = "";
      blank.textContent = "เลือกมื้ออาหาร";
      blank.disabled = true;
      blank.selected = true;
      mealsSelect.appendChild(blank);
      data.items.forEach((meal) => {
        if (typeof meal.meal_log_id !== "string") return;
        meals.set(meal.meal_log_id, meal);
        const option = document.createElement("option");
        option.value = meal.meal_log_id;
        option.textContent = mealLabel(meal);
        mealsSelect.appendChild(option);
      });
      const newOption = document.createElement("option");
      newOption.value = "__new__";
      newOption.textContent = "สร้างมื้อใหม่…";
      mealsSelect.appendChild(newOption);
      form.classList.remove("hidden");
      message.textContent = data.items.length
        ? "เลือกมื้ออาหาร หรือสร้างมื้อใหม่ แล้วระบุปริมาณที่กินด้วยตนเอง"
        : "ยังไม่มีมื้ออาหาร เลือกสร้างมื้อใหม่เพื่อดำเนินการต่อ";
      openButton.textContent = "เลือกมื้ออาหาร";
      openButton.disabled = true;
    } catch (error) {
      if (container.dataset.barcode !== barcode) return;
      message.textContent = error.status === 401
        ? "กรุณาเข้าสู่ระบบก่อนเพิ่มอาหารลง Food Diary"
        : `โหลดมื้ออาหารไม่สำเร็จ: ${error.message}`;
      if (error.status === 401 && !panel.querySelector(".barcode-login-link")) {
        const login = document.createElement("a");
        login.href = "/login";
        login.className = "barcode-login-link";
        login.textContent = "เข้าสู่ระบบ";
        panel.appendChild(login);
      }
      openButton.disabled = false;
    }
  });

  mealsSelect.addEventListener("change", () => {
    createMealPanel.classList.toggle("hidden", mealsSelect.value !== "__new__");
    refreshSummary();
  });
  createMealButton.addEventListener("click", async () => {
    if (creatingMeal || mealsSelect.value !== "__new__") return;
    if (!newMealDate.value || !newMealType.value) {
      message.textContent = "กรุณาระบุวันที่และประเภทมื้ออาหาร";
      return;
    }
    creatingMeal = true;
    createMealButton.disabled = true;
    try {
      const date = newMealDate.value;
      const time = newMealTime.value;
      const data = await requestJSON("/meals", {
        method: "POST",
        body: JSON.stringify({
          meal_date: date,
          meal_type: newMealType.value,
          eaten_at: time ? `${date}T${time}:00+07:00` : null,
          title: newMealTitle.value.trim() || null,
        }),
      });
      if (!data.meal || typeof data.meal.meal_log_id !== "string") {
        throw new Error("ไม่พบข้อมูลมื้อที่สร้าง");
      }
      meals.set(data.meal.meal_log_id, data.meal);
      const option = document.createElement("option");
      option.value = data.meal.meal_log_id;
      option.textContent = mealLabel(data.meal);
      mealsSelect.insertBefore(option, mealsSelect.querySelector('option[value="__new__"]'));
      mealsSelect.value = data.meal.meal_log_id;
      createMealPanel.classList.add("hidden");
      message.textContent = "สร้างมื้อแล้ว ยังไม่มีการเพิ่มสินค้าจนกว่าจะยืนยันด้านล่าง";
      refreshSummary();
      window.loadMealHistory?.();
    } catch (error) {
      message.textContent = `สร้างมื้ออาหารไม่สำเร็จ: ${error.message}`;
    } finally {
      creatingMeal = false;
      createMealButton.disabled = false;
    }
  });

  [quantity, unit, confirmation, notes].forEach((control) => {
    control.addEventListener("input", refreshSummary);
    control.addEventListener("change", refreshSummary);
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving) {
      message.textContent = "กำลังบันทึกรายการอาหาร กรุณารอสักครู่";
      return;
    }
    if (added) {
      message.textContent = "รายการนี้บันทึกแล้ว ไม่สามารถบันทึกซ้ำจากฟอร์มนี้ได้";
      return;
    }
    if (!confirmation.checked) {
      message.textContent = "กรุณาติ๊กยืนยันว่าตรวจสอบมื้อ ปริมาณ และหน่วยแล้ว";
      confirmation.focus();
      return;
    }
    const meal = meals.get(mealsSelect.value);
    const amountText = quantity.value.trim();
    const amount = Number(amountText);
    if (!meal) {
      message.textContent = mealsSelect.value === "__new__"
        ? "กรุณาสร้างมื้ออาหารก่อนเพิ่มสินค้า"
        : "กรุณาเลือกมื้ออาหาร";
      mealsSelect.focus();
      return;
    }
    if (!amountText || !Number.isFinite(amount) || amount <= 0
        || !/^\d+(?:\.\d{1,3})?$/.test(amountText)) {
      message.textContent = "กรุณาระบุปริมาณมากกว่า 0 โดยใช้ตัวเลขไม่เกิน 3 ตำแหน่งทศนิยม";
      quantity.focus();
      return;
    }
    if (!unit.value) {
      message.textContent = "กรุณาเลือกหน่วยของปริมาณที่รับประทาน";
      unit.focus();
      return;
    }
    saving = true;
    submit.disabled = true;
    message.textContent = "กำลังบันทึกรายการอาหาร...";
    let saved;
    try {
      saved = await requestJSON(
        `/meals/${encodeURIComponent(meal.meal_log_id)}/external-items`,
        {
          method: "POST",
          body: JSON.stringify({
            barcode,
            quantity_value: amount,
            quantity_unit: unit.value,
            confirm_add: true,
            notes: notes.value.trim() || null,
          }),
        },
      );
      if (saved.status !== "success" || !saved.item) {
        throw new Error("ระบบตอบกลับโดยไม่มีข้อมูลยืนยันการบันทึก");
      }
      if (String(saved.item.meal_log_id) !== String(meal.meal_log_id)) {
        const mismatch = new Error("มื้ออาหารที่ API ตอบกลับไม่ตรงกับมื้อที่เลือก กรุณาตรวจสอบ Food Diary ก่อนลองใหม่");
        mismatch.responseMismatch = true;
        throw mismatch;
      }
      if (!saved.duplicate
          && (Number(saved.item.quantity_value) !== amount
            || saved.item.quantity_unit !== unit.value)) {
        const mismatch = new Error("ปริมาณหรือหน่วยที่ API ตอบกลับไม่ตรงกับฟอร์ม กรุณาตรวจสอบ Food Diary ก่อนลองใหม่");
        mismatch.responseMismatch = true;
        throw mismatch;
      }
    } catch (error) {
      message.textContent = error.responseMismatch
        ? `พบข้อมูลตอบกลับไม่ตรงกัน: ${error.message}`
        : `เพิ่มรายการไม่สำเร็จ: ${error.message}`;
      saving = false;
      if (error.responseMismatch) {
        submit.disabled = true;
        openButton.disabled = true;
        form.classList.add("hidden");
        await Promise.allSettled([
          Promise.resolve().then(() => window.loadMealHistory?.()),
          Promise.resolve().then(() => window.refreshNutritionSummary?.()),
          Promise.resolve().then(() => window.refreshMealDetails?.(meal.meal_log_id)),
        ]);
        return;
      }
      refreshSummary();
      return;
    }

    // Only report success after the server has confirmed the write.
    added = true;
    saving = false;
    message.textContent = saved.duplicate
      ? "สินค้านี้อยู่ในมื้อนี้แล้ว จึงไม่บันทึกซ้ำ"
      : "เพิ่มรายการแล้ว · external_unverified · รายการรอตรวจสอบ";
    openButton.disabled = true;
    form.classList.add("hidden");
    form.querySelectorAll("input, select, textarea, button").forEach((control) => {
      control.disabled = true;
    });
    const refreshes = [
      window.loadMealHistory,
      window.refreshNutritionSummary,
    ].filter((refresh) => typeof refresh === "function");
    if (typeof window.refreshMealDetails === "function") {
      refreshes.push(() => window.refreshMealDetails(meal.meal_log_id));
    }
    const refreshResults = await Promise.allSettled(
      refreshes.map((refresh) => Promise.resolve().then(() => refresh())),
    );
    if (refreshResults.some((result) => result.status === "rejected")) {
      message.textContent += " บันทึกแล้ว แต่รีเฟรชข้อมูลบางส่วนไม่สำเร็จ กรุณากดรีเฟรช";
    }
  });
}

// Search the local catalog first, then use an attributed external reference.
async function lookupBarcode(rawCode) {
  const requestId = ++barcodeLookupRequest;
  const code = rawCode.trim();
  const result = $("barcodeResult");
  const message = $("scannerMessage");

  result.classList.add("hidden");
  result.textContent = "";
  result.dataset.barcode = code;

  if (!code) {
    message.textContent = "กรุณากรอกรหัส Barcode หรือ QR Code";
    return;
  }

  message.textContent = "กำลังค้นหารหัสในคลังอาหาร...";

  try {
    let response = await fetch(
      `/foods/barcode/${encodeURIComponent(code)}`
    );
    if (requestId !== barcodeLookupRequest) return;
    let data = await response.json().catch(() => ({}));
    if (response.status === 404) {
      message.textContent = "ไม่พบในคลังภายใน กำลังค้นหา Open Food Facts...";
      response = await fetch(
        `/foods/external/openfoodfacts/barcode/${encodeURIComponent(code)}`
      );
      if (requestId !== barcodeLookupRequest) return;
      data = await response.json().catch(() => ({}));
    }

    if (!response.ok) {
      message.textContent = response.status === 404
        ? "ไม่พบรหัสนี้ทั้งในคลังภายในและ Open Food Facts"
        : (data.detail || "ค้นหารหัสไม่สำเร็จ กรุณาลองอีกครั้ง");
      return;
    }

    const food = data.item || {};
    const isExternal = data.status === "external_unverified";
    const name = food.name_th || food.name_en || food.name || "ไม่ระบุชื่อ";
    result.replaceChildren();
    const heading = document.createElement("h3");
    heading.textContent = name;
    result.appendChild(heading);
    const appendText = (label, value) => {
      if (value === null || value === undefined || value === "") return;
      const line = document.createElement("p");
      line.textContent = `${label}: ${value}`;
      result.appendChild(line);
    };
    appendText("แบรนด์", food.brand_name || "ไม่ระบุ");
    appendText("Barcode", food.barcode || code);
    appendText("ปริมาณบรรจุ", food.package_quantity);
    appendText("สถานะข้อมูล", food.verification_status || "ไม่ระบุ");

    if (isExternal) {
      appendText("สถานะการตรวจสอบ", "ข้อมูลภายนอก ยังไม่ผ่านการตรวจสอบ");
      const disclaimer = document.createElement("p");
      disclaimer.className = "notice";
      disclaimer.textContent = data.message ||
        "ข้อมูลภายนอกใช้เป็นข้อมูลอ้างอิงเท่านั้น ยังไม่อนุญาตให้นำไปคำนวณ";
      result.appendChild(disclaimer);
      const nutrition = food.nutrition_reference_per_100g || {};
      const nutrientKeys = Object.keys(nutrition);
      if (nutrientKeys.length) {
        const title = document.createElement("h4");
        title.textContent = "ข้อมูลอ้างอิงจากแหล่งภายนอก (ต่อ 100 กรัมตามฟิลด์ต้นทาง)";
        result.appendChild(title);
        nutrientKeys.forEach((key) => appendText(key, nutrition[key]));
      }
      const source = data.source || {};
      appendText("แหล่งข้อมูล", source.source_name);
      appendText("ข้อกำหนดการอ้างอิง", source.license_or_attribution);
      const sourceUrl = source.source_url;
      if (typeof sourceUrl === "string") {
        try {
          const parsedUrl = new URL(sourceUrl);
          if (parsedUrl.protocol === "https:" &&
              parsedUrl.hostname === "world.openfoodfacts.org") {
            const link = document.createElement("a");
            link.href = parsedUrl.href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = "เปิดรายการต้นทาง Open Food Facts";
            result.appendChild(link);
          }
        } catch (error) {
          // Ignore a malformed source URL rather than rendering it.
        }
      }
      appendExternalFoodDiaryAction(result, data, code);
    } else {
      appendText("ประเภท", food.barcode_type || "ไม่ระบุ");
      const nutritionButton = document.createElement("button");
      nutritionButton.id = "barcodeNutritionBtn";
      nutritionButton.type = "button";
      nutritionButton.textContent = "ดูข้อมูลสารอาหาร";
      nutritionButton.addEventListener("click", () => {
        loadNutrition(food.food_id, name);
      });
      result.appendChild(nutritionButton);
    }
    result.classList.remove("hidden");
    message.textContent = isExternal
      ? "พบข้อมูลอ้างอิงภายนอก (ยังไม่ผ่านการตรวจสอบ)"
      : "พบอาหารในคลังข้อมูลแล้ว";
  } catch (error) {
    if (requestId !== barcodeLookupRequest) return;
    message.textContent =
      `เชื่อมต่อ API ไม่สำเร็จ: ${error.message}`;
  }
}

$("barcodeForm").addEventListener("submit", (event) => {
  event.preventDefault();
  lookupBarcode($("barcodeInput").value);
});

let barcodeStream = null;
let barcodeAnimation = null;
let barcodeDetector = null;

function stopBarcodeScanner() {
  if (barcodeAnimation !== null) {
    cancelAnimationFrame(barcodeAnimation);
    barcodeAnimation = null;
  }

  if (barcodeStream) {
    barcodeStream.getTracks().forEach((track) => track.stop());
    barcodeStream = null;
  }

  const video = $("scannerVideo");
  video.pause();
  video.srcObject = null;
  video.classList.add("hidden");
  $("stopScannerBtn").disabled = true;
  $("startScannerBtn").disabled = false;
}

async function scanVideoFrame() {
  if (!barcodeStream || !barcodeDetector) return;

  const video = $("scannerVideo");
  if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
    try {
      const detected = await barcodeDetector.detect(video);
      if (detected.length && detected[0].rawValue) {
        const code = detected[0].rawValue;
        $("barcodeInput").value = code;
        stopBarcodeScanner();
        await lookupBarcode(code);
        return;
      }
    } catch (error) {
      $("scannerMessage").textContent =
        "อ่านภาพจากกล้องไม่สำเร็จ ลองจัดตำแหน่งรหัสใหม่";
    }
  }

  if (barcodeStream) {
    barcodeAnimation = requestAnimationFrame(scanVideoFrame);
  }
}

$("startScannerBtn").addEventListener("click", async () => {
  const message = $("scannerMessage");

  if (!("BarcodeDetector" in window)) {
    message.textContent =
      "เบราว์เซอร์นี้ยังไม่รองรับตัวสแกนในตัว ลองกรอกรหัสเองก่อน";
    return;
  }

  if (!navigator.mediaDevices?.getUserMedia) {
    message.textContent =
      "ไม่สามารถเปิดกล้องได้ กรุณาใช้ localhost หรือ HTTPS บนอุปกรณ์ที่รองรับ";
    return;
  }

  try {
    const supported = await BarcodeDetector.getSupportedFormats();
    const wanted = [
      "qr_code", "ean_13", "ean_8", "upc_a", "upc_e",
      "code_128", "code_39", "itf", "data_matrix", "pdf417"
    ];
    const formats = wanted.filter((format) => supported.includes(format));

    if (!formats.length) {
      message.textContent =
        "เบราว์เซอร์ไม่รองรับรูปแบบ Barcode/QR ที่ต้องการ";
      return;
    }

    barcodeDetector = new BarcodeDetector({ formats });
    barcodeStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false
    });

    const video = $("scannerVideo");
    video.srcObject = barcodeStream;
    video.classList.remove("hidden");
    await video.play();

    $("startScannerBtn").disabled = true;
    $("stopScannerBtn").disabled = false;
    message.textContent =
      "เปิดกล้องแล้ว วาง Barcode หรือ QR Code ให้ชัดในภาพ";

    scanVideoFrame();
  } catch (error) {
    stopBarcodeScanner();
    message.textContent =
      `เปิดกล้องไม่ได้: ${error.message}. ตรวจสิทธิ์กล้องของเบราว์เซอร์`;
  }
});

$("stopScannerBtn").addEventListener("click", () => {
  stopBarcodeScanner();
  $("scannerMessage").textContent = "ปิดกล้องแล้ว";
});

let foodImageObjectUrl = null;
let currentFoodImageAnalysis = null;
let selectedPhotoFood = null;
let foodImageAnalysisRequestId = 0;

function clearFoodPhotoPreview(message = "ยังไม่ได้เลือกภาพ") {
  foodImageAnalysisRequestId += 1;
  if (foodImageObjectUrl) URL.revokeObjectURL(foodImageObjectUrl);
  foodImageObjectUrl = null;
  currentFoodImageAnalysis = null;
  selectedPhotoFood = null;
  $("foodImageInput").value = "";
  $("foodImagePreview").classList.add("hidden");
  $("foodImagePreview").removeAttribute("src");
  $("foodImageAnalysisOutput").replaceChildren();
  $("foodImageAnalysisOutput").classList.add("hidden");
  $("foodImageConsent").checked = false;
  $("foodImageConsent").disabled = false;
  $("analyzeFoodImageBtn").disabled = true;
  $("removeFoodImageBtn").disabled = true;
  $("imageMessage").textContent = message;
}

$("foodImageInput").addEventListener("change", () => {
  foodImageAnalysisRequestId += 1;
  const file = $("foodImageInput").files?.[0];
  const preview = $("foodImagePreview");
  const message = $("imageMessage");
  currentFoodImageAnalysis = null;
  selectedPhotoFood = null;
  $("foodImageAnalysisOutput").replaceChildren();
  $("foodImageAnalysisOutput").classList.add("hidden");
  $("foodImageConsent").checked = false;
  if (foodImageObjectUrl) URL.revokeObjectURL(foodImageObjectUrl);
  foodImageObjectUrl = null;

  if (!file) {
    preview.classList.add("hidden");
    preview.removeAttribute("src");
    $("analyzeFoodImageBtn").disabled = true;
    $("removeFoodImageBtn").disabled = true;
    message.textContent = "ยังไม่ได้เลือกภาพ";
    return;
  }
  if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    clearFoodPhotoPreview("ชนิดไฟล์ไม่รองรับ กรุณาเลือก JPEG, PNG หรือ WebP");
    return;
  }
  if (file.size === 0 || file.size > 10 * 1024 * 1024) {
    clearFoodPhotoPreview(file.size === 0
      ? "ไฟล์ภาพว่างเปล่า กรุณาเลือกภาพใหม่"
      : "ภาพใหญ่เกินไป กรุณาเลือกภาพขนาดไม่เกิน 10 MB");
    return;
  }
  foodImageObjectUrl = URL.createObjectURL(file);
  preview.src = foodImageObjectUrl;
  preview.classList.remove("hidden");
  $("analyzeFoodImageBtn").disabled = false;
  $("removeFoodImageBtn").disabled = false;
  message.textContent = "ตรวจชนิดและขนาดไฟล์แล้ว ภาพจะถูกส่งเมื่อคุณยินยอมและกดวิเคราะห์";
});

$("removeFoodImageBtn").addEventListener("click", () => clearFoodPhotoPreview());

$("analyzeFoodImageBtn").addEventListener("click", async () => {
  const file = $("foodImageInput").files?.[0];
  const button = $("analyzeFoodImageBtn");
  const message = $("imageMessage");
  if (!file || button.disabled) return;
  if (!$("foodImageConsent").checked) {
    message.textContent = "กรุณายินยอมก่อนส่งภาพไปยังผู้ให้บริการ AI ภายนอก";
    $("foodImageConsent").focus();
    return;
  }
  button.disabled = true;
  const requestId = ++foodImageAnalysisRequestId;
  selectedPhotoFood = null;
  $("removeFoodImageBtn").disabled = true;
  message.textContent = "กำลังวิเคราะห์ภาพ…";
  $("foodImageAnalysisOutput").classList.add("hidden");
  $("foodImageAnalysisContent").replaceChildren();
  try {
    const response = await fetch("/foods/image-analysis", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": file.type, "X-Food-Image-Consent": "true" },
      body: file,
    });
    if (requestId !== foodImageAnalysisRequestId) return;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
      error.status = response.status;
      throw error;
    }
    if (data.status !== "proposed" || !data.food_identification) {
      throw new Error("รูปแบบผลวิเคราะห์ไม่ถูกต้อง");
    }
    currentFoodImageAnalysis = data;
    renderFoodImageAnalysis(data);
    message.textContent = "วิเคราะห์เสร็จแล้ว โปรดตรวจสอบและยืนยันข้อมูลก่อนบันทึก";
  } catch (error) {
    if (requestId !== foodImageAnalysisRequestId) return;
    message.textContent = error.status === 401
      ? "กรุณาเข้าสู่ระบบก่อนวิเคราะห์ภาพ"
      : `วิเคราะห์ภาพไม่สำเร็จ: ${error.message}`;
  } finally {
    if (requestId === foodImageAnalysisRequestId) {
      button.disabled = false;
      $("removeFoodImageBtn").disabled = false;
    }
  }
});

function appendPhotoText(parent, tag, className, value) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = value;
  parent.appendChild(element);
  return element;
}

function renderFoodImageAnalysis(data) {
  const output = $("foodImageAnalysisOutput");
  const content = $("foodImageAnalysisContent");
  content.replaceChildren();
  const identification = data.food_identification || {};
  appendPhotoText(content, "h5", "", identification.name || "ยังระบุชื่ออาหารไม่ได้");
  appendPhotoText(content, "p", "food-image-confidence",
    `ความมั่นใจในการระบุภาพ: ${identification.confidence || "ไม่ระบุ"} · ต้องให้ผู้ใช้ยืนยัน`);
  if (Array.isArray(identification.components) && identification.components.length) {
    appendPhotoText(content, "h6", "", "ส่วนประกอบที่มองเห็น (ข้อเสนอจาก AI)");
    const list = document.createElement("ul");
    identification.components.forEach((component) => appendPhotoText(list, "li", "", component));
    content.appendChild(list);
  }
  const portion = data.portion_estimate;
  appendPhotoText(content, "p", "food-image-portion", portion
    ? `ปริมาณโดยประมาณ: ${portion.value} ${portion.unit} · ความมั่นใจ ${portion.confidence || "ไม่ระบุ"} (ตรวจและแก้ก่อนบันทึก)`
    : "ยังประเมินปริมาณจากภาพไม่ได้ กรุณาระบุเองก่อนบันทึก");
  appendPhotoText(content, "p", "food-image-nutrition-state",
    "สารอาหาร: ยังไม่คำนวณ — ผลภาพไม่ใช่ข้อมูลโภชนาการที่ผ่านการตรวจสอบ");
  appendPhotoText(content, "p", "food-image-provenance",
    `ผู้ให้บริการวิเคราะห์ภาพ: ${data.provider || "ไม่ระบุ"} · รุ่น: ${data.model || "ไม่ระบุ"}`);
  (data.limitations || []).forEach((limitation) => appendPhotoText(content, "p", "subtext", limitation));
  const searchButton = document.createElement("button");
  searchButton.type = "button";
  searchButton.className = "secondary-button";
  searchButton.textContent = "ค้นหาอาหารที่ตรงกันในคลัง";
  searchButton.addEventListener("click", () => {
    $("imageFoodSearch").value = identification.name || "";
    searchFoodsFromImage();
  });
  content.appendChild(searchButton);
  buildFoodImageSaveForm(content, data);
  output.classList.remove("hidden");
}

function buildFoodImageSaveForm(parent, analysis) {
  const form = document.createElement("form");
  form.className = "food-image-save-form";
  form.noValidate = true;
  appendPhotoText(form, "h5", "", "ตรวจสอบก่อนเพิ่มลง Food Diary");
  const fields = document.createElement("div");
  fields.className = "food-image-save-grid";
  const makeField = (labelText, control, id) => {
    const wrapper = document.createElement("div");
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = labelText;
    control.id = id;
    wrapper.append(label, control);
    fields.appendChild(wrapper);
  };
  const foodName = document.createElement("input");
  foodName.type = "text";
  foodName.maxLength = 300;
  foodName.required = true;
  foodName.value = analysis.food_identification?.name || "";
  makeField("ชื่ออาหาร (แก้ไขได้)", foodName, "foodImageConfirmedName");
  const mealSelect = document.createElement("select");
  mealSelect.required = true;
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "กำลังโหลดมื้ออาหาร…";
  mealSelect.appendChild(placeholder);
  makeField("มื้ออาหาร", mealSelect, "foodImageTargetMeal");
  const quantity = document.createElement("input");
  quantity.type = "number";
  quantity.min = "0.001";
  quantity.step = "0.001";
  quantity.inputMode = "decimal";
  const portion = analysis.portion_estimate;
  if (portion && ["g", "ml", "piece"].includes(portion.unit)) quantity.value = String(portion.value);
  makeField("ปริมาณที่รับประทาน", quantity, "foodImageQuantity");
  const unit = document.createElement("select");
  unit.required = true;
  [["", "เลือกหน่วย"], ["g", "กรัม"], ["ml", "มิลลิลิตร"], ["piece", "ชิ้น"], ["serving", "หน่วยบริโภค"], ["package", "แพ็ก"]].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    unit.appendChild(option);
  });
  if (portion && ["g", "ml", "piece"].includes(portion.unit)) unit.value = portion.unit;
  makeField("หน่วย (ไม่มีการแปลงอัตโนมัติ)", unit, "foodImageQuantityUnit");
  form.appendChild(fields);
  const mealMessage = appendPhotoText(form, "p", "message", "กำลังโหลดมื้ออาหารของคุณ…");
  const confirmLabel = document.createElement("label");
  confirmLabel.className = "food-image-confirmation";
  const confirm = document.createElement("input");
  confirm.type = "checkbox";
  const confirmText = document.createElement("span");
  confirmText.textContent = "ฉันตรวจสอบและยืนยันชื่ออาหาร มื้อ ปริมาณ และหน่วยแล้ว";
  confirmLabel.append(confirm, confirmText);
  form.appendChild(confirmLabel);
  const save = document.createElement("button");
  save.type = "submit";
  save.className = "primary-button";
  save.textContent = "ยืนยันและบันทึกลง Food Diary";
  save.disabled = true;
  form.appendChild(save);
  parent.appendChild(form);

  let saving = false;
  let saved = false;
  fetch("/meals?limit=100&offset=0", { credentials: "same-origin" })
    .then(async (response) => {
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(result.detail || `HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      return result;
    })
    .then((result) => {
      mealSelect.replaceChildren();
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = result.items?.length ? "เลือกมื้ออาหาร" : "ยังไม่มีมื้ออาหาร";
      mealSelect.appendChild(empty);
      (result.items || []).forEach((meal) => {
        if (typeof meal.meal_log_id !== "string") return;
        const option = document.createElement("option");
        option.value = meal.meal_log_id;
        option.textContent = `${meal.title || meal.meal_type} · ${meal.meal_date}`;
        mealSelect.appendChild(option);
      });
      mealMessage.textContent = result.items?.length
        ? "เลือกมื้อ ปรับปริมาณตามจริง และยืนยันก่อนบันทึก"
        : "ยังไม่มีมื้ออาหาร กรุณาสร้างมื้อใน Food Diary ก่อนบันทึก";
      if (!result.items?.length) {
        const link = document.createElement("a");
        link.href = "#myMeals";
        link.textContent = "ไปที่ Food Diary";
        mealMessage.append(" ", link);
      }
      save.disabled = !result.items?.length;
    })
    .catch((error) => {
      mealMessage.textContent = error.status === 401
        ? "กรุณาเข้าสู่ระบบเพื่อโหลดมื้ออาหาร"
        : `โหลดมื้ออาหารไม่สำเร็จ: ${error.message}`;
    });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (saving || saved) return;
    const amountText = quantity.value.trim();
    const amount = Number(amountText);
    if (!confirm.checked) {
      mealMessage.textContent = "กรุณายืนยันข้อมูลก่อนบันทึก";
      confirm.focus();
      return;
    }
    if (!mealSelect.value) {
      mealMessage.textContent = "กรุณาเลือกมื้ออาหาร";
      mealSelect.focus();
      return;
    }
    if (!foodName.value.trim()) {
      mealMessage.textContent = "กรุณาระบุชื่ออาหารที่ยืนยันแล้ว";
      foodName.focus();
      return;
    }
    if (!amountText || !Number.isFinite(amount) || amount <= 0 || !unit.value
        || !/^\d+(?:\.\d{1,3})?$/.test(amountText)) {
      mealMessage.textContent = "กรุณาระบุปริมาณมากกว่า 0 และเลือกหน่วยให้ถูกต้อง";
      quantity.focus();
      return;
    }
    const selectedMealId = mealSelect.value;
    const selectedFoodId = selectedPhotoFood?.food_id || null;
    const selectedUnit = unit.value;
    saving = true;
    save.disabled = true;
    [foodName, mealSelect, quantity, unit, confirm].forEach((control) => { control.disabled = true; });
    mealMessage.textContent = "กำลังบันทึก…";
    const requestBody = {
      food_name: foodName.value.trim(),
      quantity_value: amount,
      quantity_unit: unit.value,
      weight_g: unit.value === "g" ? amount : null,
      volume_ml: unit.value === "ml" ? amount : null,
      entry_source: "food_image",
      notes: `AI image analysis proposal; provider=${analysis.provider || "unknown"}; model=${analysis.model || "unknown"}; identification_confidence=${analysis.food_identification?.confidence || "unknown"}; portion_estimate=${analysis.portion_estimate ? `${analysis.portion_estimate.value} ${analysis.portion_estimate.unit}` : "not_available"}; user confirmed.`,
    };
    if (selectedFoodId) requestBody.food_id = selectedFoodId;
    try {
      const response = await fetch(`/meals/${encodeURIComponent(selectedMealId)}/items`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || `HTTP ${response.status}`);
      if (result.status !== "success" || !result.item
          || result.item.meal_log_id !== selectedMealId
          || Number(result.item.quantity_value) !== amount
          || result.item.quantity_unit !== selectedUnit
          || result.item.entry_source !== "food_image"
          || result.item.confirmation_status !== "needs_review"
          || (selectedFoodId && result.item.food_id !== selectedFoodId)) {
        throw new Error("ข้อมูลตอบกลับไม่ตรงกับรายการที่ยืนยัน กรุณาตรวจสอบ Food Diary");
      }
      saved = true;
      mealMessage.textContent = "บันทึกแล้ว · รายการอยู่ในสถานะ needs_review และยังไม่ใช้คำนวณสารอาหาร";
      form.querySelectorAll("input, select, button").forEach((control) => { control.disabled = true; });
      await Promise.allSettled([
        Promise.resolve().then(() => window.loadMealHistory?.()),
        Promise.resolve().then(() => window.refreshNutritionSummary?.()),
        Promise.resolve().then(() => window.refreshMealDetails?.(selectedMealId)),
      ]);
    } catch (error) {
      mealMessage.textContent = `บันทึกไม่สำเร็จ: ${error.message}`;
      [foodName, mealSelect, quantity, unit, confirm].forEach((control) => { control.disabled = false; });
      save.disabled = false;
    } finally {
      saving = false;
    }
  });
  foodName.addEventListener("input", () => { selectedPhotoFood = null; });
}


// Search foods by a name typed by the user in the photo section.
// This does not perform AI image recognition.
async function searchFoodsFromImage() {
  const input = $("imageFoodSearch");
  const message = $("imageFoodMessage");
  const results = $("imageFoodResults");

  if (!input || !message || !results) {
    console.error("ไม่พบองค์ประกอบค้นหาอาหารจากภาพใน index.html");
    return;
  }

  const query = input.value.trim();
  results.innerHTML = "";

  if (!query) {
    message.textContent = "กรุณาพิมพ์ชื่ออาหารก่อนค้นหา";
    return;
  }

  message.textContent = "กำลังค้นหาอาหารในคลัง...";
  results.innerHTML = "";

  try {
    const params = new URLSearchParams({
      search: query,
      limit: "100"
    });
    const data = await getJSON(`/foods?${params}`);
    const items = data.items ?? [];

    if (!items.length) {
      message.textContent =
        "ไม่พบอาหารชื่อนี้ในคลัง ลองใช้ชื่ออื่น";
      return;
    }

    message.textContent =
      `พบ ${items.length} รายการ — เลือกรายการที่ตรงกับอาหารของคุณ`;

    items.forEach((food) => {
      const name = food.name_th || food.name_en || "ไม่ระบุชื่อ";
      const status = food.verification_status || "unverified";

      const row = document.createElement("article");
      row.className = "food-item";

      const info = document.createElement("div");
      info.className = "food-info";

      const details = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = name;

      const description = document.createElement("p");
      description.textContent =
        food.brand_name || food.item_type || "อาหาร";

      const statusText = document.createElement("p");
      statusText.textContent = `สถานะข้อมูล: ${status}`;

      details.append(title, description, statusText);
      info.appendChild(details);

      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "เลือกอาหารและดูสารอาหาร";

      button.addEventListener("click", async () => {
        message.textContent =
          `กำลังโหลดข้อมูลของ ${name}...`;

        await loadNutrition(food.food_id, name);
        message.textContent =
          `เลือก ${name} แล้ว โปรดตรวจสอบสถานะข้อมูลก่อนนำไปใช้`;
      });

      row.append(info, button);
      if (currentFoodImageAnalysis) {
        const matchButton = document.createElement("button");
        matchButton.type = "button";
        matchButton.className = "secondary-button";
        matchButton.textContent = "ใช้ชื่อนี้ในรายการภาพ";
        matchButton.addEventListener("click", () => {
          selectedPhotoFood = food;
          const confirmedName = $("foodImageConfirmedName");
          if (confirmedName) confirmedName.value = name;
          message.textContent = `เลือก ${name} เป็นรายการจากคลังแล้ว · สถานะข้อมูล ${status}`;
        });
        row.appendChild(matchButton);
      }
      results.appendChild(row);
    });
  } catch (error) {
    message.textContent =
      `ค้นหาไม่สำเร็จ: ${error.message}`;
  }
}

const imageFoodSearchButton = $("imageFoodSearchBtn");
const imageFoodSearchInput = $("imageFoodSearch");

if (imageFoodSearchButton && imageFoodSearchInput) {
  imageFoodSearchButton.addEventListener(
    "click",
    searchFoodsFromImage
  );

  imageFoodSearchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchFoodsFromImage();
    }
  });
}

window.addEventListener("beforeunload", stopBarcodeScanner);

loadDashboard();
