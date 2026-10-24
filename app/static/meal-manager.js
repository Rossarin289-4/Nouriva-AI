(() => {
  const $ = (id) => document.getElementById(id);
  const typeLabels = {
    breakfast: "อาหารเช้า",
    lunch: "อาหารกลางวัน",
    dinner: "อาหารเย็น",
    snack: "ของว่าง",
    other: "อื่น ๆ",
  };
  let selectedMeal = null;
  let selectedFood = null;
  let selectedPortions = [];
  let historyRequest = 0;
  let historyOffset = 0;
  let searchRequest = 0;
  let busy = false;

  function bangkokDateValue(date = new Date()) {
    const parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Bangkok",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
    return `${values.year}-${values.month}-${values.day}`;
  }

  function formatMealDate(value) {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
    if (!match) return value || "ไม่ระบุวันที่";
    const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]), 12));
    return new Intl.DateTimeFormat("th-TH", {
      timeZone: "Asia/Bangkok",
      dateStyle: "long",
    }).format(date);
  }

  function formatMealTime(value) {
    if (!value) return "";
    const source = String(value);
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(source);
    const parsed = new Date(hasZone ? source : `${source}+07:00`);
    if (Number.isNaN(parsed.getTime())) return source;
    return new Intl.DateTimeFormat("th-TH", {
      timeZone: "Asia/Bangkok",
      hour: "2-digit",
      minute: "2-digit",
    }).format(parsed) + " น.";
  }

  function formatTimeInput(value) {
    if (!value) return "";
    const source = String(value);
    const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(source);
    const parsed = new Date(hasZone ? source : `${source}+07:00`);
    if (Number.isNaN(parsed.getTime())) return "";
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Bangkok",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(parsed);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });
    const data = response.status === 204
      ? {}
      : await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = response.status === 401
        ? "กรุณาเข้าสู่ระบบก่อนใช้งานข้อมูลมื้ออาหาร"
        : (typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`);
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function setMealMessage(message, state = "") {
    const target = $("mealsMessage");
    target.textContent = message;
    target.className = `message ${state}`.trim();
  }

  function notifyDashboard(state, detail = {}) {
    window.dispatchEvent(new CustomEvent("nouriva:meal-history", {
      detail: { state, ...detail },
    }));
  }

  function appendLoginLink(parent) {
    const link = document.createElement("a");
    link.href = "/login";
    link.className = "meal-login-link";
    link.textContent = "เข้าสู่ระบบ";
    parent.appendChild(link);
  }

  function displayMealState(message, state) {
    const results = $("mealResults");
    results.replaceChildren();
    results.setAttribute("aria-busy", state === "loading" ? "true" : "false");
    setMealMessage(message, state);
    if (state === "unauthenticated") appendLoginLink(results);
    if (state === "error") {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "secondary-button";
      retry.textContent = "ลองโหลดอีกครั้ง";
      retry.addEventListener("click", () => loadMealHistory());
      results.appendChild(retry);
    }
  }

  function mealHeading(meal) {
    return meal.title || typeLabels[meal.meal_type] || meal.meal_type || "มื้ออาหาร";
  }

  function createMealCard(meal) {
    const card = document.createElement("article");
    card.className = "meal-card";
    const heading = document.createElement("h3");
    heading.textContent = mealHeading(meal);
    const meta = document.createElement("p");
    meta.className = "meal-meta";
    const mealTime = formatMealTime(meal.eaten_at);
    meta.textContent = [formatMealDate(meal.meal_date), mealTime].filter(Boolean).join(" · ");
    const actions = document.createElement("div");
    actions.className = "meal-card-actions";
    const detail = document.createElement("button");
    detail.type = "button";
    detail.className = "secondary-button";
    detail.textContent = "ดูรายละเอียด";
    detail.addEventListener("click", () => openMeal(meal));
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "secondary-button";
    edit.textContent = "แก้ไขมื้อ";
    edit.addEventListener("click", () => showEditMealForm(meal, card));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger-button";
    remove.textContent = "ลบมื้อ";
    remove.addEventListener("click", () => deleteMeal(meal));
    actions.append(detail, edit, remove);
    card.append(heading, meta);
    if (meal.notes) {
      const notes = document.createElement("p");
      notes.className = "meal-notes";
      notes.textContent = meal.notes;
      card.appendChild(notes);
    }
    card.appendChild(actions);
    return card;
  }

  function createMealField(labelText, control, id, wide = false) {
    control.id = id;
    const field = document.createElement("div");
    field.className = `meal-field${wide ? " meal-form-wide" : ""}`;
    const label = document.createElement("label");
    label.htmlFor = id;
    label.textContent = labelText;
    field.append(label, control);
    return field;
  }

  function showEditMealForm(meal, card) {
    const form = document.createElement("form");
    form.className = "meal-edit-form meal-log-edit-form";
    const idSuffix = String(meal.meal_log_id || "").replace(/[^a-zA-Z0-9_-]/g, "");
    const date = document.createElement("input");
    date.type = "date";
    date.required = true;
    date.value = meal.meal_date || "";
    const type = document.createElement("select");
    Object.entries(typeLabels).forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      type.appendChild(option);
    });
    type.value = meal.meal_type;
    const time = document.createElement("input");
    time.type = "time";
    time.value = formatTimeInput(meal.eaten_at);
    const title = document.createElement("input");
    title.maxLength = 200;
    title.value = meal.title || "";
    const notes = document.createElement("textarea");
    notes.maxLength = 2000;
    notes.rows = 2;
    notes.value = meal.notes || "";
    const dateField = createMealField("วันที่", date, `editMealDate-${idSuffix}`);
    const typeField = createMealField("ประเภทมื้อ", type, `editMealType-${idSuffix}`);
    const timeField = createMealField("เวลา (เวลาไทย)", time, `editMealTime-${idSuffix}`);
    const titleField = createMealField("ชื่อมื้อ", title, `editMealTitle-${idSuffix}`);
    const notesField = createMealField("บันทึก", notes, `editMealNotes-${idSuffix}`, true);
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "primary-button";
    save.textContent = "บันทึกการแก้ไข";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "secondary-button";
    cancel.textContent = "ยกเลิก";
    cancel.addEventListener("click", () => loadMealHistory());
    const actions = document.createElement("div");
    actions.className = "meal-form-actions meal-edit-actions";
    actions.append(save, cancel);
    form.append(dateField, typeField, timeField, titleField, notesField, actions);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      const body = {
        meal_date: date.value,
        meal_type: type.value,
        eaten_at: time.value ? `${date.value}T${time.value}:00+07:00` : null,
        title: title.value.trim() || null,
        notes: notes.value.trim() || null,
      };
      try {
        const result = await api(`/meals/${encodeURIComponent(meal.meal_log_id)}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        await loadMealHistory();
        if (selectedMeal?.meal_log_id === meal.meal_log_id) {
          await openMeal(result.meal);
        }
      } catch (error) {
        const message = document.createElement("p");
        message.className = "message error";
        message.textContent = `แก้ไขมื้ออาหารไม่สำเร็จ: ${error.message}`;
        form.prepend(message);
        save.disabled = false;
      }
    });
    card.replaceChildren(form);
  }

  async function deleteMeal(meal) {
    const label = mealHeading(meal);
    if (!window.confirm(`ลบมื้อ “${label}” และรายการอาหารทั้งหมดในมื้อนี้หรือไม่? การลบนี้ไม่สามารถย้อนกลับได้`)) return;
    try {
      await api(`/meals/${encodeURIComponent(meal.meal_log_id)}`, { method: "DELETE" });
      if (selectedMeal?.meal_log_id === meal.meal_log_id) {
        selectedMeal = null;
        $("mealDetailPanel").classList.add("hidden");
        resetItemForm();
      }
      await loadMealHistory();
    } catch (error) {
      setMealMessage(`ลบมื้ออาหารไม่สำเร็จ: ${error.message}`, "error");
    }
  }

  async function loadMealHistory(append = false) {
    const requestId = ++historyRequest;
    const offset = append ? historyOffset : 0;
    if (!append) {
      historyOffset = 0;
      displayMealState("กำลังโหลดรายการมื้ออาหาร...", "loading");
      notifyDashboard("loading");
    } else {
      $("mealResults").querySelector(".meal-load-more")?.remove();
      setMealMessage("กำลังโหลดรายการเพิ่มเติม...", "loading");
    }
    const date = $("mealHistoryDate").value;
    const params = new URLSearchParams({ limit: "100", offset: String(offset) });
    if (date) params.set("meal_date", date);
    try {
      const data = await api(`/meals?${params}`);
      if (requestId !== historyRequest) return;
      if (!Array.isArray(data.items)) throw new Error("รูปแบบรายการมื้ออาหารไม่ถูกต้อง");
      const results = $("mealResults");
      if (!append) results.replaceChildren();
      results.setAttribute("aria-busy", "false");
      if (!data.items.length) {
        if (!append) notifyDashboard("empty", { dateFilter: date || null });
        setMealMessage(append
          ? "ไม่มีรายการย้อนหลังเพิ่มเติมแล้ว"
          : (date
            ? `ไม่พบมื้ออาหารในวันที่ ${formatMealDate(date)}`
            : "ยังไม่มีรายการมื้ออาหารที่บันทึกไว้"), "empty");
        return;
      }
      historyOffset = offset + data.items.length;
      setMealMessage(`${append ? "โหลดเพิ่มแล้ว · " : ""}แสดง ${historyOffset} มื้อ${date ? ` ในวันที่ ${formatMealDate(date)}` : ""}`, "success");
      if (!append) notifyDashboard("success", {
        items: data.items.slice(0, 3),
        dateFilter: date || null,
      });
      data.items.forEach((meal) => results.appendChild(createMealCard(meal)));
      if (data.items.length === data.limit) {
        const more = document.createElement("button");
        more.type = "button";
        more.className = "secondary-button meal-load-more";
        more.textContent = "โหลดมื้อย้อนหลังเพิ่มเติม";
        more.addEventListener("click", () => loadMealHistory(true));
        results.appendChild(more);
      }
    } catch (error) {
      if (requestId !== historyRequest) return;
      displayMealState(error.status === 401
        ? "กรุณาเข้าสู่ระบบเพื่อดูประวัติมื้ออาหาร"
        : `โหลดประวัติมื้ออาหารไม่สำเร็จ: ${error.message}`,
      error.status === 401 ? "unauthenticated" : "error");
      notifyDashboard(error.status === 401 ? "unauthenticated" : "error");
    }
  }

  function resetItemForm() {
    selectedFood = null;
    selectedPortions = [];
    $("mealItemForm").reset();
    $("mealItemForm").classList.add("hidden");
    $("mealFoodResults").replaceChildren();
    $("selectedMealFood").replaceChildren();
    $("selectedMealFood").classList.add("hidden");
    $("mealItemEntryFields").classList.add("hidden");
    $("mealPortionField").classList.add("hidden");
    $("mealNutritionReference").replaceChildren();
    $("saveMealItemButton").disabled = true;
    $("showAddMealItem").classList.remove("hidden");
  }

  function setMealItemsMessage(message, state = "") {
    const target = $("mealItemsMessage");
    target.textContent = message;
    target.className = `message ${state}`.trim();
  }

  function createItemCard(item) {
    const card = document.createElement("article");
    card.className = "meal-item-card";
    const title = document.createElement("h5");
    title.textContent = item.food_name_snapshot || "อาหารที่บันทึก";
    const quantity = document.createElement("p");
    quantity.className = "meal-meta";
    const units = { g: "กรัม", ml: "มล.", piece: "ชิ้น", serving: "หน่วยบริโภค", package: "แพ็ก", portion: "portion" };
    quantity.textContent = `${item.quantity_value} ${units[item.quantity_unit] || item.quantity_unit}`;
    const status = document.createElement("span");
    status.className = "pill review";
    status.textContent = item.confirmation_status || "ไม่ระบุสถานะ";
    card.append(title, quantity, status);
    if (item.external_status === "external_unverified") {
      const provenance = document.createElement("p");
      provenance.className = "meal-meta";
      provenance.textContent = `${item.external_source_name || "แหล่งภายนอก"} · external_unverified`;
      card.appendChild(provenance);
      if (typeof item.external_source_url === "string") {
        try {
          const sourceUrl = new URL(item.external_source_url);
          if (sourceUrl.protocol === "https:" && sourceUrl.hostname === "world.openfoodfacts.org") {
            const sourceLink = document.createElement("a");
            sourceLink.href = sourceUrl.href;
            sourceLink.target = "_blank";
            sourceLink.rel = "noopener noreferrer";
            sourceLink.textContent = "ดูแหล่งข้อมูล Open Food Facts";
            card.appendChild(sourceLink);
          }
        } catch (error) {
          // Do not render an invalid source URL.
        }
      }
    }
    if (item.preparation_state_snapshot) {
      const prep = document.createElement("p");
      prep.className = "meal-meta";
      prep.textContent = item.preparation_state_snapshot;
      card.appendChild(prep);
    }
    if (item.notes) {
      const notes = document.createElement("p");
      notes.className = "meal-notes";
      notes.textContent = item.notes;
      card.appendChild(notes);
    }
    const actions = document.createElement("div");
    actions.className = "meal-card-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "secondary-button";
    edit.textContent = "แก้ไข";
    edit.addEventListener("click", () => showEditForm(item, card));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger-button";
    remove.textContent = "ลบ";
    remove.addEventListener("click", () => deleteMealItem(item));
    actions.append(edit, remove);
    card.appendChild(actions);
    return card;
  }

  function showEditForm(item, card) {
    const form = document.createElement("form");
    form.className = "meal-edit-form";
    const idSuffix = String(item.meal_item_id || "").replace(/[^a-zA-Z0-9_-]/g, "");
    const quantity = document.createElement("input");
    quantity.type = "number";
    quantity.min = "0.001";
    quantity.step = "any";
    quantity.value = item.quantity_value;
    quantity.required = true;
    const unit = document.createElement("select");
    const unitOptions = [["g", "กรัม"], ["ml", "มล."], ["piece", "ชิ้น"], ["serving", "หน่วยบริโภค"], ["package", "แพ็ก"]];
    if (item.portion_id) unitOptions.push(["portion", "หน่วย portion"]);
    unitOptions.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      unit.appendChild(option);
    });
    unit.value = item.quantity_unit;
    const notes = document.createElement("textarea");
    notes.maxLength = 2000;
    notes.value = item.notes || "";
    const quantityField = createMealField("ปริมาณ", quantity, `editMealItemQuantity-${idSuffix}`);
    const unitField = createMealField("หน่วย", unit, `editMealItemUnit-${idSuffix}`);
    const notesField = createMealField("บันทึก", notes, `editMealItemNotes-${idSuffix}`, true);
    if (item.quantity_unit === "portion") {
      quantity.disabled = true;
      unit.disabled = true;
      const hint = document.createElement("p");
      hint.className = "meal-meta";
      hint.textContent = "API ปัจจุบันไม่ปรับน้ำหนักเมื่อแก้จำนวน portion จึงแก้ได้เฉพาะบันทึก";
      form.appendChild(hint);
    }
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "primary-button";
    save.textContent = "บันทึกการแก้ไข";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "secondary-button";
    cancel.textContent = "ยกเลิก";
    cancel.addEventListener("click", loadMealItems);
    const actions = document.createElement("div");
    actions.className = "meal-form-actions meal-edit-actions";
    actions.append(save, cancel);
    form.append(quantityField, unitField, notesField, actions);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      const body = { notes: notes.value.trim() || null };
      if (item.quantity_unit !== "portion") {
        const amount = Number(quantity.value);
        if (!Number.isFinite(amount) || amount <= 0) {
          save.disabled = false;
          setMealItemsMessage("กรุณากรอกปริมาณมากกว่า 0", "error");
          return;
        }
        body.quantity_value = amount;
        body.quantity_unit = unit.value;
        body.weight_g = unit.value === "g" ? amount : null;
        body.volume_ml = unit.value === "ml" ? amount : null;
      }
      try {
    await api(`/meals/${encodeURIComponent(selectedMeal.meal_log_id)}/items/${encodeURIComponent(item.meal_item_id)}`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        await loadMealItems();
      } catch (error) {
        setMealItemsMessage(`แก้ไขรายการไม่สำเร็จ: ${error.message}`, "error");
        save.disabled = false;
      }
    });
    card.replaceChildren(form);
  }

  async function deleteMealItem(item) {
    if (!window.confirm(`ต้องการลบ “${item.food_name_snapshot || "รายการอาหาร"}” หรือไม่?`)) return;
    try {
      await api(`/meals/${encodeURIComponent(selectedMeal.meal_log_id)}/items/${encodeURIComponent(item.meal_item_id)}`, { method: "DELETE" });
      await loadMealItems();
    } catch (error) {
      setMealItemsMessage(`ลบรายการไม่สำเร็จ: ${error.message}`, "error");
    }
  }

  async function loadMealItems() {
    if (!selectedMeal) return;
    const meal = selectedMeal;
    const list = $("mealItemsList");
    list.replaceChildren();
    setMealItemsMessage("กำลังโหลดรายการอาหาร...", "loading");
    try {
      const data = await api(`/meals/${encodeURIComponent(meal.meal_log_id)}/items`);
      if (selectedMeal?.meal_log_id !== meal.meal_log_id) return;
      if (!Array.isArray(data.items) || data.meal_log_id !== meal.meal_log_id) {
        throw new Error("รูปแบบรายการอาหารในมื้อไม่ถูกต้อง");
      }
      list.replaceChildren();
      if (!data.items.length) {
        setMealItemsMessage("มื้อนี้ยังไม่มีรายการอาหาร", "empty");
        return;
      }
      setMealItemsMessage(`มี ${data.count} รายการ · สถานะการยืนยันแสดงตาม API`, "success");
      data.items.forEach((item) => list.appendChild(createItemCard(item)));
    } catch (error) {
      if (selectedMeal?.meal_log_id !== meal.meal_log_id) return;
      setMealItemsMessage(`โหลดรายการอาหารไม่สำเร็จ: ${error.message}`, "error");
    }
  }

  async function openMeal(meal) {
    selectedMeal = meal;
    $("mealDetailPanel").classList.remove("hidden");
    $("mealDetailTitle").textContent = mealHeading(meal);
    const time = formatMealTime(meal.eaten_at);
    $("mealDetailMeta").textContent = [formatMealDate(meal.meal_date), time].filter(Boolean).join(" · ");
    $("mealDetailNotes").textContent = meal.notes || "";
    resetItemForm();
    await loadMealItems();
    $("mealDetailPanel").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function searchFoods() {
    const query = $("mealFoodSearch").value.trim();
    const results = $("mealFoodResults");
    const requestId = ++searchRequest;
    results.replaceChildren();
    if (!query) {
      $("mealFoodMessage").textContent = "กรุณาพิมพ์ชื่ออาหารก่อนค้นหา";
      return;
    }
    $("mealFoodMessage").textContent = "กำลังค้นหาอาหารในคลัง...";
    try {
      const params = new URLSearchParams({ search: query, limit: "20" });
      const data = await api(`/foods?${params}`);
      if (requestId !== searchRequest) return;
      const foods = Array.isArray(data.items) ? data.items : [];
      if (!foods.length) {
        $("mealFoodMessage").textContent = "ไม่พบอาหารในคลัง";
        return;
      }
      $("mealFoodMessage").textContent = `พบ ${foods.length} รายการ เลือกอาหารที่ตรงกับรายการของคุณ`;
      foods.forEach((food) => {
        const row = document.createElement("article");
        row.className = "meal-food-option";
        const detail = document.createElement("div");
        const name = document.createElement("strong");
        name.textContent = food.name_th || food.name_en || "ไม่ระบุชื่อ";
        const secondary = document.createElement("p");
        secondary.textContent = [food.brand_name, food.preparation_state, `สถานะ: ${food.verification_status || "ไม่ระบุ"}`].filter(Boolean).join(" · ");
        detail.append(name, secondary);
        const choose = document.createElement("button");
        choose.type = "button";
        choose.className = "secondary-button";
        choose.textContent = "เลือก";
        choose.addEventListener("click", () => selectFood(food));
        row.append(detail, choose);
        results.appendChild(row);
      });
    } catch (error) {
      $("mealFoodMessage").textContent = `ค้นหาอาหารไม่สำเร็จ: ${error.message}`;
    }
  }

  async function loadFoodReference(food) {
    const panel = $("mealNutritionReference");
    panel.replaceChildren();
    const loading = document.createElement("p");
    loading.textContent = "กำลังโหลดข้อมูล Portion และโภชนาการ...";
    panel.appendChild(loading);
    const [portionResult, nutritionResult] = await Promise.allSettled([
      api(`/foods/${encodeURIComponent(food.food_id)}/portions`),
      api(`/foods/${encodeURIComponent(food.food_id)}/nutrition`),
    ]);
    if (selectedFood?.food_id !== food.food_id) return;
    panel.replaceChildren();

    const portionsLabel = document.createElement("p");
    portionsLabel.className = "meal-meta";
    if (portionResult.status === "fulfilled") {
      selectedPortions = Array.isArray(portionResult.value.items)
        ? portionResult.value.items : [];
      const select = $("mealPortionSelect");
      select.replaceChildren();
      selectedPortions.forEach((portion) => {
        const option = document.createElement("option");
        option.value = portion.portion_id;
        const name = portion.portion_name_th || portion.portion_name_en || portion.unit_name || "หน่วยบริโภค";
        option.textContent = `${name} · ${portion.weight_g} กรัม · ${portion.verification_status}`;
        select.appendChild(option);
      });
      const portionOption = $("mealItemUnit").querySelector('option[value="portion"]');
      portionOption.disabled = selectedPortions.length === 0;
      portionsLabel.textContent = selectedPortions.length
        ? `มีหน่วยบริโภคที่ผ่านการตรวจสอบ ${selectedPortions.length} รายการ`
        : "ไม่มีหน่วยบริโภคที่ผ่านการตรวจสอบ ใช้ปริมาณเป็นกรัมได้";
    } else {
      selectedPortions = [];
      $("mealItemUnit").querySelector('option[value="portion"]').disabled = true;
      portionsLabel.textContent = `โหลด Portion ไม่สำเร็จ: ${portionResult.reason.message}`;
    }
    panel.appendChild(portionsLabel);

    if (nutritionResult.status !== "fulfilled") {
      const warning = document.createElement("p");
      warning.textContent = `ไม่มีข้อมูลโภชนาการให้อ้างอิง: ${nutritionResult.reason.message}`;
      panel.appendChild(warning);
      return;
    }

    const data = nutritionResult.value;
    const foodStatus = data.food?.verification_status || "ไม่ระบุ";
    const basisStatuses = [...new Set((data.nutrition || []).map((row) => row.verification_status || "ไม่ระบุ"))];
    const heading = document.createElement("strong");
    heading.textContent = "ข้อมูลโภชนาการอ้างอิงจากคลัง (ไม่ใช่ปริมาณที่ได้รับ)";
    const source = document.createElement("p");
    source.className = "meal-meta";
    const sourceInfo = data.source || {};
    source.textContent = `อาหาร: ${foodStatus} · ฐานโภชนาการ: ${basisStatuses.join(", ") || "ไม่พบข้อมูล"} · แหล่งข้อมูล: ${sourceInfo.source_name || sourceInfo.source_code || "ไม่ระบุ"} (${sourceInfo.verification_status || "ไม่ระบุ"})`;
    panel.append(heading, source);
    const rows = Array.isArray(data.nutrition) ? data.nutrition : [];
    if (!rows.length) {
      const missing = document.createElement("p");
      missing.textContent = "ยังไม่มีข้อมูลสารอาหารในคลัง";
      panel.appendChild(missing);
      return;
    }
    const table = document.createElement("table");
    table.className = "nutrition-table";
    const body = document.createElement("tbody");
    rows.forEach((item) => {
      const row = document.createElement("tr");
      const name = document.createElement("td");
      name.textContent = item.nutrient_name_th || item.nutrient_name_en || item.nutrient_code || "ไม่ระบุ";
      const amount = document.createElement("td");
      amount.textContent = `${item.amount ?? "ไม่ระบุ"} ${item.nutrient_unit || ""}`;
      const basis = document.createElement("td");
      basis.textContent = `${item.basis_type || "ฐานไม่ระบุ"}: ${item.basis_quantity ?? "ไม่ระบุ"} ${item.basis_unit || ""} · ${item.verification_status || "ไม่ระบุ"}`;
      row.append(name, amount, basis);
      body.appendChild(row);
    });
    table.appendChild(body);
    panel.appendChild(table);
    if (foodStatus !== "reviewed" && foodStatus !== "source_verified" ||
        basisStatuses.some((status) => status !== "reviewed" && status !== "source_verified") ||
        sourceInfo.source_is_active !== true) {
      const warning = document.createElement("p");
      warning.className = "notice";
      warning.textContent = "ข้อมูลบางส่วนยังไม่ผ่านการตรวจสอบครบถ้วน ใช้เป็นข้อมูลอ้างอิงเท่านั้น และระบบจะไม่คำนวณสารอาหารที่ได้รับจากข้อมูลชุดนี้";
      panel.appendChild(warning);
    }
  }

  async function selectFood(food) {
    selectedFood = food;
    $("mealFoodResults").replaceChildren();
    $("selectedMealFood").replaceChildren();
    $("selectedMealFood").classList.remove("hidden");
    const selectedName = document.createElement("strong");
    selectedName.textContent = food.name_th || food.name_en || "ไม่ระบุชื่อ";
    const status = document.createElement("p");
    status.textContent = `สถานะอาหาร: ${food.verification_status || "ไม่ระบุ"} · รายการใหม่จะบันทึกเป็น needs_review`;
    $("selectedMealFood").append(selectedName, status);
    $("mealItemEntryFields").classList.remove("hidden");
    $("saveMealItemButton").disabled = false;
    $("mealItemQuantity").value = "100";
    $("mealItemUnit").value = "g";
    $("mealPortionField").classList.add("hidden");
    await loadFoodReference(food);
  }

  async function createMeal(event) {
    event.preventDefault();
    if (busy) return;
    const button = $("createMealButton");
    busy = true;
    button.disabled = true;
    const date = $("newMealDate").value;
    const time = $("newMealTime").value;
    const body = {
      meal_date: date,
      meal_type: $("newMealType").value,
      eaten_at: time ? `${date}T${time}:00+07:00` : null,
      title: $("newMealTitle").value.trim() || null,
      notes: $("newMealNotes").value.trim() || null,
    };
    try {
      await api("/meals", { method: "POST", body: JSON.stringify(body) });
      $("newMealTitle").value = "";
      $("newMealNotes").value = "";
      $("mealHistoryDate").value = date;
      await loadMealHistory();
      setMealMessage("บันทึกมื้ออาหารแล้ว", "success");
    } catch (error) {
      setMealMessage(`บันทึกมื้ออาหารไม่สำเร็จ: ${error.message}`, "error");
    } finally {
      busy = false;
      button.disabled = false;
    }
  }

  async function addMealItem(event) {
    event.preventDefault();
    if (!selectedMeal || !selectedFood || busy) return;
    const button = $("saveMealItemButton");
    const quantity = Number($("mealItemQuantity").value);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      $("mealFoodMessage").textContent = "กรุณากรอกปริมาณมากกว่า 0";
      return;
    }
    const unit = $("mealItemUnit").value;
    const body = {
      food_id: selectedFood.food_id,
      quantity_value: quantity,
      quantity_unit: unit,
      entry_source: "search",
      notes: $("mealItemNotes").value.trim() || null,
    };
    if (unit === "g") body.weight_g = quantity;
    if (unit === "portion") {
      const portionId = $("mealPortionSelect").value;
      if (!portionId || !selectedPortions.some((portion) => portion.portion_id === portionId)) {
        $("mealFoodMessage").textContent = "กรุณาเลือกหน่วยบริโภคที่ตรวจสอบแล้ว";
        return;
      }
      body.portion_id = portionId;
    }
    busy = true;
    button.disabled = true;
    try {
      const data = await api(`/meals/${encodeURIComponent(selectedMeal.meal_log_id)}/items`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      resetItemForm();
      setMealItemsMessage(`เพิ่มรายการแล้ว · สถานะ ${data.item?.confirmation_status || "needs_review"}`, "success");
      await loadMealItems();
    } catch (error) {
      $("mealFoodMessage").textContent = `เพิ่มรายการไม่สำเร็จ: ${error.message}`;
    } finally {
      busy = false;
      if (selectedFood) button.disabled = false;
    }
  }

  $("newMealDate").value = bangkokDateValue();
  $("mealCreateForm").addEventListener("submit", createMeal);
  $("mealHistoryDate").addEventListener("change", () => loadMealHistory());
  $("clearMealDate").addEventListener("click", () => {
    $("mealHistoryDate").value = "";
    loadMealHistory();
  });
  $("closeMealDetail").addEventListener("click", () => {
    selectedMeal = null;
    $("mealDetailPanel").classList.add("hidden");
    resetItemForm();
  });
  $("showAddMealItem").addEventListener("click", () => {
    $("mealItemForm").classList.remove("hidden");
    $("showAddMealItem").classList.add("hidden");
    $("mealFoodSearch").focus();
  });
  $("cancelMealItem").addEventListener("click", resetItemForm);
  $("mealFoodSearchButton").addEventListener("click", searchFoods);
  $("mealFoodSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      searchFoods();
    }
  });
  $("mealItemUnit").addEventListener("change", () => {
    const isPortion = $("mealItemUnit").value === "portion";
    $("mealPortionField").classList.toggle("hidden", !isPortion);
    if (isPortion) $("mealItemQuantity").value = "1";
  });
  $("mealItemForm").addEventListener("submit", addMealItem);
  $("mealNutritionReference").addEventListener("click", (event) => {
    if (event.target.closest("a")) {
      const href = event.target.closest("a").getAttribute("href");
      if (!/^https:\/\//i.test(href || "")) event.preventDefault();
    }
  });

  window.loadMealHistory = loadMealHistory;
  window.refreshMealDetails = async (mealLogId) => {
    if (selectedMeal?.meal_log_id !== mealLogId) return;
    await loadMealItems();
  };
  loadMealHistory();
})();
