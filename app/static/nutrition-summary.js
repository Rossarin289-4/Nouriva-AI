(() => {
  const $ = (id) => document.getElementById(id);
  const PAGE_SIZE = 100;
  const MAX_PAGES = 100;
  const trustedStatuses = new Set(["reviewed", "source_verified"]);
  const mealLabels = {
    breakfast: "อาหารเช้า",
    lunch: "อาหารกลางวัน",
    dinner: "อาหารเย็น",
    snack: "ของว่าง",
    other: "อื่น ๆ",
  };
  let requestId = 0;

  function bangkokDateValue(now = new Date()) {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Bangkok",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(now);
    const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
    return `${values.year}-${values.month}-${values.day}`;
  }

  function isDateValue(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const [year, month, day] = value.split("-").map(Number);
    const parsed = new Date(Date.UTC(year, month - 1, day));
    return parsed.getUTCFullYear() === year
      && parsed.getUTCMonth() === month - 1
      && parsed.getUTCDate() === day;
  }

  function formatDate(value) {
    if (!isDateValue(value)) return "ไม่ระบุวันที่";
    const [year, month, day] = value.split("-").map(Number);
    return new Intl.DateTimeFormat("th-TH", {
      timeZone: "Asia/Bangkok",
      dateStyle: "long",
    }).format(new Date(Date.UTC(year, month - 1, day, 12)));
  }

  function formatTime(value) {
    if (!value) return "";
    const source = String(value);
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(source);
    const parsed = new Date(hasZone ? source : `${source}+07:00`);
    if (Number.isNaN(parsed.getTime())) return "";
    return `${new Intl.DateTimeFormat("th-TH", {
      timeZone: "Asia/Bangkok",
      hour: "2-digit",
      minute: "2-digit",
    }).format(parsed)} น.`;
  }

  async function api(path) {
    const response = await fetch(path, { credentials: "same-origin" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = response.status === 401
        ? "กรุณาเข้าสู่ระบบเพื่อดูประวัติมื้ออาหาร"
        : (typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function setMessage(message, state = "") {
    const target = $("summaryMessage");
    target.textContent = message;
    target.className = `message ${state}`.trim();
  }

  function setReadiness(title, message, state = "pending") {
    const card = $("summaryReadiness");
    card.className = `summary-readiness ${state}`;
    $("summaryReadinessTitle").textContent = title;
    $("summaryReadinessMessage").textContent = message;
  }

  function appendLoginLink() {
    const link = document.createElement("a");
    link.href = "/login";
    link.className = "meal-login-link";
    link.textContent = "เข้าสู่ระบบ";
    $("summaryMeals").appendChild(link);
  }

  async function loadMeals() {
    const meals = [];
    const seen = new Set();
    for (let page = 0; page < MAX_PAGES; page += 1) {
      const offset = page * PAGE_SIZE;
      const data = await api(`/meals?limit=${PAGE_SIZE}&offset=${offset}`);
      if (!Array.isArray(data.items) || !Number.isInteger(data.count)
        || data.count !== data.items.length) {
        throw new Error("รูปแบบข้อมูลรายการมื้อไม่ถูกต้อง");
      }
      data.items.forEach((meal) => {
        if (!meal || typeof meal.meal_log_id !== "string"
          || !isDateValue(String(meal.meal_date || ""))) {
          throw new Error("พบข้อมูลมื้ออาหารที่ไม่ถูกต้อง");
        }
        if (!seen.has(meal.meal_log_id)) {
          seen.add(meal.meal_log_id);
          meals.push(meal);
        }
      });
      if (data.items.length < PAGE_SIZE) return meals;
    }
    throw new Error("มีประวัติมื้ออาหารมากเกินกว่าจะโหลดได้ในครั้งเดียว");
  }

  async function loadMealItems(meal) {
    const data = await api(`/meals/${encodeURIComponent(meal.meal_log_id)}/items`);
    if (!Array.isArray(data.items) || data.meal_log_id !== meal.meal_log_id
      || !Number.isInteger(data.count) || data.count !== data.items.length) {
      throw new Error("รูปแบบข้อมูลรายการอาหารไม่ถูกต้อง");
    }
    const seen = new Set();
    return data.items.filter((item) => {
      if (!item || typeof item.meal_item_id !== "string") {
        throw new Error("พบรายการอาหารที่ไม่มีรหัสอ้างอิง");
      }
      if (seen.has(item.meal_item_id)) return false;
      seen.add(item.meal_item_id);
      return true;
    });
  }

  async function loadFoodStatuses(items) {
    const foodIds = [...new Set(items
      .filter((item) => item.external_status !== "external_unverified")
      .map((item) => item.food_id)
      .filter((id) => typeof id === "string" && id.length > 0))];
    const entries = await Promise.all(foodIds.map(async (foodId) => {
      const data = await api(`/foods/${encodeURIComponent(foodId)}/nutrition`);
      if (!data.food || data.food.food_id !== foodId || !Array.isArray(data.nutrition)) {
        throw new Error("รูปแบบข้อมูลสถานะอาหารไม่ถูกต้อง");
      }
      return [foodId, data];
    }));
    return new Map(entries);
  }

  function getNutritionStatus(item, foodData) {
    if (item.external_status === "external_unverified") {
      const source = item.external_source_name || item.external_source_code || "แหล่งภายนอก";
      return {
        label: "ข้อมูลภายนอกยังไม่ผ่านการตรวจสอบ",
        ready: false,
        detail: `${source} · external_unverified · ไม่รวมในการคำนวณสารอาหาร`,
      };
    }
    if (!item.food_id || !foodData) {
      return { label: "ไม่มีข้อมูลอาหารในคลัง", ready: false, detail: "รายการนี้ไม่ได้เชื่อมกับอาหารในคลัง" };
    }
    const foodStatus = foodData.food.verification_status;
    const foodVerified = trustedStatuses.has(foodStatus);
    const basisGroups = new Map();
    foodData.nutrition.forEach((row) => {
      if (!row || typeof row.nutrition_basis_id !== "string") return;
      if (!basisGroups.has(row.nutrition_basis_id)) basisGroups.set(row.nutrition_basis_id, []);
      basisGroups.get(row.nutrition_basis_id).push(row);
    });
    let basisId = null;
    if (item.selected_nutrition_basis_id) {
      basisId = basisGroups.has(item.selected_nutrition_basis_id)
        ? item.selected_nutrition_basis_id
        : null;
    }
    const basisRows = basisId ? basisGroups.get(basisId) : [];
    const basis = basisRows?.[0] || null;
    const basisVerified = Boolean(basis && trustedStatuses.has(basis.verification_status));
    const source = foodData.source;
    const sourceVerified = Boolean(
      basis && basisGroups.size === 1 && source && source.source_is_active === true,
    );
    const nutrientsExist = Boolean(basis && basisRows.length > 0);
    const ready = foodVerified && basisVerified && sourceVerified && nutrientsExist;
    const sourceLabel = source
      ? `${source.source_name || source.source_code || "แหล่งข้อมูล"} (${source.source_code || "ไม่ระบุรหัส"}) — ${sourceVerified ? "เปิดใช้งาน" : "ไม่พบหรือไม่ได้เปิดใช้งาน"}`
      : "ไม่พบข้อมูลแหล่งที่มา";
    const parts = [
      `อาหาร: ${foodStatus || "ไม่ระบุสถานะ"}`,
      `ฐานโภชนาการ: ${basis?.verification_status || (basis ? "ไม่ระบุสถานะ" : "ไม่ได้เลือกหรือไม่พบฐาน")}`,
      `แหล่งข้อมูล: ${sourceLabel}`,
      `ระเบียนสารอาหาร: ${nutrientsExist ? "พบ" : "ไม่พบ"}`,
    ];
    return {
      label: ready ? "ข้อมูลอาหารผ่านการตรวจสอบ" : "ข้อมูลอาหารยังไม่พร้อม",
      ready,
      detail: parts.join(" · "),
    };
  }

  function appendText(parent, tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    element.textContent = text;
    parent.appendChild(element);
    return element;
  }

  function createItemCard(item, foodData) {
    const card = document.createElement("li");
    card.className = "summary-item";
    const name = item.food_name_snapshot || "ไม่ระบุชื่ออาหาร";
    appendText(card, "strong", "summary-item-name", name);
    const quantity = item.quantity_value === null || item.quantity_value === undefined
      ? "ไม่ระบุปริมาณ"
      : `${item.quantity_value} ${item.quantity_unit || "ไม่ระบุหน่วย"}`;
    appendText(card, "p", "summary-item-quantity", quantity);
    const status = getNutritionStatus(item, foodData);
    const tag = appendText(card, "span", `summary-badge ${status.ready ? "verified" : "review"}`, status.label);
    tag.setAttribute("aria-label", status.label);
    appendText(card, "p", "summary-item-detail", status.detail);
    const confirmation = item.confirmation_status === "needs_review"
      ? "รอตรวจสอบ"
      : (item.confirmation_status || "ไม่ระบุสถานะ");
    appendText(card, "p", "summary-item-confirmation", `สถานะบันทึก: ${confirmation}`);
    return card;
  }

  function renderMeals(mealsWithItems, foodStatuses) {
    const target = $("summaryMeals");
    target.replaceChildren();
    if (!mealsWithItems.length) {
      setMessage("ไม่พบมื้ออาหารในช่วงวันที่เลือก", "empty");
      return;
    }
    setMessage(`พบ ${mealsWithItems.length} มื้อในช่วงวันที่เลือก`, "success");
    mealsWithItems.forEach(({ meal, items }) => {
      const card = document.createElement("article");
      card.className = "summary-meal-card";
      const heading = document.createElement("div");
      heading.className = "summary-meal-heading";
      const title = meal.title || mealLabels[meal.meal_type] || meal.meal_type || "มื้ออาหาร";
      appendText(heading, "h3", "", title);
      const time = formatTime(meal.eaten_at);
      appendText(heading, "p", "", [formatDate(meal.meal_date), time].filter(Boolean).join(" · "));
      card.appendChild(heading);
      if (meal.notes) appendText(card, "p", "summary-meal-notes", meal.notes);
      if (!items.length) {
        appendText(card, "p", "summary-no-items", "มื้อนี้ยังไม่มีรายการอาหาร");
      } else {
        const list = document.createElement("ul");
        list.className = "summary-item-list";
        items.forEach((item) => list.appendChild(createItemCard(
          item,
          foodStatuses.get(item.food_id),
        )));
        card.appendChild(list);
      }
      $("summaryMeals").appendChild(card);
    });
  }

  async function loadSummary(fromDate, toDate) {
    const currentRequest = ++requestId;
    const button = $("loadNutritionSummary");
    button.disabled = true;
    $("summaryMeals").replaceChildren();
    $("summaryMeals").setAttribute("aria-busy", "true");
    setMessage("กำลังโหลดมื้ออาหารและตรวจสอบข้อมูล...", "loading");
    setReadiness("กำลังตรวจสอบความพร้อมของข้อมูล", "ยังไม่มีการคำนวณยอดสารอาหาร", "loading");
    try {
      const [allMeals, rule] = await Promise.all([
        loadMeals(),
        api("/rules/NUT-001"),
      ]);
      const filtered = allMeals.filter((meal) => (
        meal.meal_date >= fromDate && meal.meal_date <= toDate
      ));
      const mealItems = await Promise.all(filtered.map(async (meal) => ({
        meal,
        items: await loadMealItems(meal),
      })));
      const allItems = mealItems.flatMap(({ items }) => items);
      const foodStatuses = await loadFoodStatuses(allItems);
      if (currentRequest !== requestId) return;

      const inactiveRule = rule.lifecycle_status !== "active";
      const pendingItems = allItems.filter((item) => item.confirmation_status !== "confirmed").length;
      const reason = inactiveRule
        ? `กฎ ${rule.rule_code || "NUT-001"} สถานะ ${rule.lifecycle_status || "ไม่ระบุ"} ยังไม่ active`
        : "หน้านี้ยังไม่มียอดคำนวณรวมจาก backend ที่ตรวจสอบได้";
      const pendingReason = pendingItems
        ? ` พบรายการบันทึกที่ยังไม่ยืนยัน ${pendingItems} รายการ`
        : "";
      setReadiness(
        "ยังไม่แสดงยอดสารอาหาร",
        `${reason}.${pendingReason} หน้านี้แสดงเฉพาะสถานะจาก API และไม่คำนวณหรือประมาณค่า`,
        "pending",
      );
      renderMeals(mealItems, foodStatuses);
      if (!filtered.length) {
        setReadiness(
          "ไม่มีข้อมูลมื้ออาหารในช่วงนี้",
          `${reason}. เมื่อมีมื้ออาหาร ระบบจะแสดงสถานะข้อมูลโดยไม่สร้างยอดสารอาหาร`,
          "empty",
        );
      }
    } catch (error) {
      if (currentRequest !== requestId) return;
      $("summaryMeals").replaceChildren();
      if (error.status === 401) {
        setMessage(error.message, "unauthenticated");
        appendLoginLink();
        setReadiness("ต้องเข้าสู่ระบบ", "รายการมื้ออาหารต้องใช้บัญชีของเจ้าของข้อมูล", "error");
      } else {
        setMessage(`โหลดสรุปไม่สำเร็จ: ${error.message}`, "error");
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "secondary-button";
        retry.textContent = "ลองอีกครั้ง";
        retry.addEventListener("click", () => loadSummary(fromDate, toDate));
        $("summaryMeals").appendChild(retry);
        setReadiness("ตรวจสอบข้อมูลไม่สำเร็จ", "ยังไม่แสดงผลสรุป จนกว่าจะโหลดข้อมูลและสถานะกฎได้ครบ", "error");
      }
    } finally {
      if (currentRequest === requestId) {
        button.disabled = false;
        $("summaryMeals").setAttribute("aria-busy", "false");
      }
    }
  }

  const today = bangkokDateValue();
  $("summaryFromDate").value = today;
  $("summaryToDate").value = today;
  window.refreshNutritionSummary = () => loadSummary(
    $("summaryFromDate").value,
    $("summaryToDate").value,
  );
  $("nutritionSummaryFilter").addEventListener("submit", (event) => {
    event.preventDefault();
    const fromDate = $("summaryFromDate").value;
    const toDate = $("summaryToDate").value;
    if (!isDateValue(fromDate) || !isDateValue(toDate)) {
      $("summaryMeals").replaceChildren();
      setMessage("กรุณาเลือกวันที่ให้ถูกต้อง", "error");
      setReadiness("ช่วงวันที่ไม่ถูกต้อง", "กรุณาเลือกวันที่เริ่มต้นและสิ้นสุดให้ถูกต้อง", "error");
      return;
    }
    if (fromDate > toDate) {
      $("summaryMeals").replaceChildren();
      setMessage("วันที่เริ่มต้นต้องไม่อยู่หลังวันที่สิ้นสุด", "error");
      setReadiness("ช่วงวันที่ไม่ถูกต้อง", "เลือกวันที่เริ่มต้นให้ไม่อยู่หลังวันที่สิ้นสุด", "error");
      return;
    }
    loadSummary(fromDate, toDate);
  });

  loadSummary(today, today);
})();
