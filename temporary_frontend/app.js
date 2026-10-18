const state = {
  courses: [],
  activeCourseId: localStorage.getItem("studymate.activeCourseId") || "",
  lastJobId: "",
  activeQuiz: null,
  framework: null,
  materials: [],
  plans: [],
  busyCount: 0,
};

const $ = (id) => document.getElementById(id);

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true;
  }, 3600);
}

function renderJson(id, data) {
  $(id).textContent = JSON.stringify(data, null, 2);
}

function setBusy(isBusy) {
  state.busyCount = Math.max(0, state.busyCount + (isBusy ? 1 : -1));
  document.body.classList.toggle("busy", state.busyCount > 0);
}

function setStep(id, active) {
  const element = $(id);
  if (element) element.classList.toggle("done", Boolean(active));
}

function updateWorkflow() {
  setStep("step-course", Boolean(state.activeCourseId));
  setStep("step-material", state.materials.some((material) => material.status === "ready"));
  setStep("step-knowledge", Boolean(state.framework));
  setStep("step-quiz", Boolean(state.activeQuiz));
  setStep("step-plan", Boolean(state.plans.length));
}

function activeCourseId() {
  const selected = $("course-select").value || state.activeCourseId;
  if (!selected) {
    throw new Error("Select or create a course first.");
  }
  return selected;
}

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: options.body instanceof FormData
      ? options.headers
      : { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (parseError) {
      const error = new Error(`Invalid JSON response: ${parseError.message}`);
      error.response = {
        error: {
          message: error.message,
          status: "client",
          response_status: response.status,
          response_text: text.slice(0, 1000),
        },
      };
      error.status = response.status || "client";
      throw error;
    }
  }
  if (!response.ok) {
    const message = data?.error?.message || `${response.status} ${response.statusText}`;
    const error = new Error(message);
    error.response = data;
    error.status = response.status;
    throw error;
  }
  return data;
}

async function run(outputId, action) {
  setBusy(true);
  try {
    const data = await action();
    if (outputId) renderJson(outputId, data);
    updateWorkflow();
    return data;
  } catch (error) {
    const payload = error.response || { error: { message: error.message, status: error.status || "client" } };
    if (outputId) renderJson(outputId, payload);
    showToast(error.message);
    throw error;
  } finally {
    setBusy(false);
  }
}

async function checkHealth() {
  const pill = $("health-pill");
  return run("settings-output", async () => {
    const health = await api("/health");
    pill.textContent = `${health.status} / ${health.environment}`;
    pill.className = "pill ok";
    setStep("step-api", true);
    return health;
  }).catch(() => {
    pill.textContent = "API unavailable";
    pill.className = "pill bad";
    setStep("step-api", false);
  });
}

async function loadSettings() {
  return run("settings-output", async () => {
    const settings = await api("/settings");
    $("setting-llm-base").value = settings.llm_base_url || "";
    $("setting-llm-model").value = settings.llm_model || "";
    return settings;
  });
}

async function saveMockSettings() {
  return run("settings-output", async () => {
    const payload = {
      llm_base_url: $("setting-llm-base").value || "mock://local",
      llm_model: $("setting-llm-model").value || "mock-stage8",
    };
    const settings = await api("/settings", { method: "PUT", body: JSON.stringify(payload) });
    $("setting-llm-base").value = settings.llm_base_url || "";
    $("setting-llm-model").value = settings.llm_model || "";
    return settings;
  });
}

async function refreshCourses() {
  return run("courses-output", async () => {
    state.courses = await api("/courses");
    const select = $("course-select");
    select.innerHTML = "";
    for (const course of state.courses) {
      const option = document.createElement("option");
      option.value = course.id;
      option.textContent = course.name;
      select.append(option);
    }
    if (state.courses.length) {
      const exists = state.courses.some((course) => course.id === state.activeCourseId);
      state.activeCourseId = exists ? state.activeCourseId : state.courses[0].id;
      select.value = state.activeCourseId;
      localStorage.setItem("studymate.activeCourseId", state.activeCourseId);
      await refreshMaterials(false);
    } else {
      state.activeCourseId = "";
      state.materials = [];
      $("materials-list").innerHTML = "";
      localStorage.removeItem("studymate.activeCourseId");
    }
    return state.courses;
  });
}

async function createCourse(event) {
  event.preventDefault();
  await run("courses-output", async () => {
    const course = await api("/courses", {
      method: "POST",
      body: JSON.stringify({
        name: $("course-name").value,
        description: $("course-description").value || null,
      }),
    });
    state.activeCourseId = course.id;
    localStorage.setItem("studymate.activeCourseId", course.id);
    $("course-form").reset();
    await refreshCourses();
    return course;
  });
}

async function pollJob(jobId, outputId = "jobs-output") {
  if (!jobId) throw new Error("Missing job ID.");
  state.lastJobId = jobId;
  $("job-id").value = jobId;
  let job = null;
  for (let attempt = 0; attempt < 120; attempt += 1) {
    job = await api(`/jobs/${jobId}`);
    renderJson(outputId, job);
    if (["succeeded", "failed", "cancelled"].includes(job.status)) return job;
    await new Promise((resolve) => window.setTimeout(resolve, 750));
  }
  return job;
}

async function getJob(event) {
  event.preventDefault();
  return run("jobs-output", () => api(`/jobs/${$("job-id").value.trim()}`));
}

async function uploadMaterial(event) {
  event.preventDefault();
  await run("materials-output", async () => {
    const file = $("material-file").files[0];
    if (!file) throw new Error("Choose a PDF or PPTX file.");
    const form = new FormData();
    form.append("file", file);
    const uploaded = await api(`/courses/${activeCourseId()}/materials`, { method: "POST", body: form });
    if (uploaded.job_id) {
      const job = await pollJob(uploaded.job_id, "jobs-output");
      await refreshMaterials(false);
      return { uploaded, job };
    }
    await refreshMaterials(false);
    return uploaded;
  });
}

async function refreshMaterials(writeOutput = true) {
  const outputId = writeOutput ? "materials-output" : null;
  return run(outputId, async () => {
    const materials = await api(`/courses/${activeCourseId()}/materials`);
    state.materials = materials;
    const list = $("materials-list");
    list.innerHTML = "";
    for (const material of materials) {
      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `
        <div class="card-title">
          <h3>${escapeHtml(material.filename)}</h3>
          <span class="status ${statusClass(material.status)}">${escapeHtml(material.status)}</span>
        </div>
        ${material.error_code ? `<p class="danger">${escapeHtml(material.error_code)}</p>` : ""}
        <div class="meta">
          <span>${material.page_count} pages</span>
          <span>${material.chunk_count} chunks</span>
          <span>${Math.round(material.size_bytes / 1024)} KB</span>
          <span>${formatDate(material.updated_at)}</span>
        </div>
      `;
      const actions = document.createElement("div");
      actions.className = "mini-actions";
      const detailButton = document.createElement("button");
      detailButton.type = "button";
      detailButton.textContent = "Details";
      detailButton.addEventListener("click", () => loadMaterialDetail(material.id));
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "secondary danger-button";
      deleteButton.textContent = "Delete";
      deleteButton.addEventListener("click", () => deleteMaterial(material.id, material.filename));
      actions.append(detailButton, deleteButton);
      card.append(actions);
      list.append(card);
    }
    return materials;
  });
}

async function loadMaterialDetail(materialId) {
  return run("materials-output", async () => {
    const material = await api(`/materials/${materialId}`);
    renderMaterialPages(material);
    return material;
  });
}

async function deleteMaterial(materialId, filename) {
  if (!window.confirm(`Delete ${filename}?`)) return null;
  return run("materials-output", async () => {
    await api(`/materials/${materialId}`, { method: "DELETE" });
    await refreshMaterials(false);
    return { deleted: materialId };
  });
}

function renderMaterialPages(material) {
  const list = $("search-results");
  list.innerHTML = "";
  for (const page of material.pages || []) {
    const card = document.createElement("article");
    card.className = "card compact";
    card.innerHTML = `
      <div class="card-title">
        <h3>Page ${page.page_number}</h3>
        <span class="status ${statusClass(page.extraction_status)}">${escapeHtml(page.extraction_status)}</span>
      </div>
      ${page.error_code ? `<p class="danger">${escapeHtml(page.error_code)}</p>` : ""}
      <p>${escapeHtml(page.text_preview || "No text preview")}</p>
      <div class="meta"><span>${page.text_length} chars</span></div>
    `;
    list.append(card);
  }
}

async function searchMaterials(event) {
  event.preventDefault();
  return run("materials-output", async () => {
    const query = $("search-query").value.trim();
    if (!query) throw new Error("Enter a search query.");
    const results = await api(`/courses/${activeCourseId()}/search?q=${encodeURIComponent(query)}`);
    renderSearchResults(results);
    return results;
  });
}

function renderSearchResults(results) {
  const list = $("search-results");
  list.innerHTML = "";
  for (const result of results) {
    const card = document.createElement("article");
    card.className = "card compact";
    card.innerHTML = `
      <h3>${escapeHtml(result.filename)}</h3>
      <p>${escapeHtml(result.text)}</p>
      <div class="meta"><span>Pages ${result.page_start}-${result.page_end}</span><span>${escapeHtml(result.chunk_id)}</span></div>
    `;
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Open Chunk";
    button.addEventListener("click", () => run("materials-output", () => api(`/chunks/${result.chunk_id}`)));
    card.append(button);
    list.append(card);
  }
}

async function buildKnowledge() {
  await run("knowledge-output", async () => {
    const outline = $("reference-outline").value.trim();
    const started = await api(`/courses/${activeCourseId()}/knowledge/build`, {
      method: "POST",
      body: JSON.stringify(outline ? { reference_outline: outline } : {}),
    });
    const job = await pollJob(started.job_id, "jobs-output");
    if (job.status === "succeeded") {
      await loadKnowledge();
    }
    return { started, job };
  });
}

async function loadKnowledge() {
  return run("knowledge-output", async () => {
    state.framework = await api(`/courses/${activeCourseId()}/knowledge`);
    renderKnowledgeSummary(state.framework);
    renderKnowledgeTree(state.framework.tree || []);
    return state.framework;
  });
}

async function loadVersions() {
  return run("knowledge-output", () => api(`/courses/${activeCourseId()}/knowledge/versions`));
}

function renderKnowledgeTree(nodes) {
  const root = $("knowledge-tree");
  root.innerHTML = "";
  const renderNode = (node, depth = 0) => {
    const item = document.createElement("div");
    item.className = "tree-item";
    item.style.marginLeft = `${depth * 16}px`;
    item.innerHTML = `
      <strong>${escapeHtml(node.title)}</strong>
      <small>${node.level} / ${node.is_leaf ? "leaf" : "branch"} / ${node.sources?.length || 0} sources</small>
      ${node.description ? `<p>${escapeHtml(node.description)}</p>` : ""}
    `;
    item.addEventListener("click", () => run("knowledge-output", () => api(`/knowledge/${node.knowledge_node_id}`)));
    root.append(item);
    for (const child of node.children || []) renderNode(child, depth + 1);
  };
  nodes.forEach((node) => renderNode(node));
}

function renderKnowledgeSummary(framework) {
  const summary = $("knowledge-summary");
  const leaves = (framework.nodes || []).filter((node) => node.is_leaf).length;
  summary.innerHTML = `
    <span>Version ${framework.version_number}</span>
    <span>${escapeHtml(framework.status)}</span>
    <span>${framework.nodes?.length || 0} nodes</span>
    <span>${leaves} leaves</span>
  `;
}

function selectedQuestionTypes() {
  return Array.from(document.querySelectorAll("input[name='question-type']:checked")).map((input) => input.value);
}

async function generateQuiz() {
  await run("quiz-output", async () => {
    const generated = await api(`/courses/${activeCourseId()}/quiz/generate`, {
      method: "POST",
      body: JSON.stringify({
        question_count: Number($("question-count").value),
        question_types: selectedQuestionTypes(),
        difficulty: $("quiz-difficulty").value || "low",
      }),
    });
    const job = await pollJob(generated.job_id, "jobs-output");
    $("quiz-id").value = generated.quiz_id;
    if (job.status === "succeeded") {
      await loadQuiz();
    }
    return { generated, job };
  });
}

async function loadQuiz() {
  return run("quiz-output", async () => {
    const quizId = $("quiz-id").value.trim();
    if (!quizId) throw new Error("Enter or generate a quiz ID.");
    state.activeQuiz = await api(`/quizzes/${quizId}`);
    $("quiz-result").innerHTML = "";
    renderQuiz(state.activeQuiz);
    return state.activeQuiz;
  });
}

function renderQuiz(quiz) {
  const form = $("quiz-form");
  form.innerHTML = "";
  for (const question of quiz.questions) {
    const field = document.createElement("section");
    field.className = "quiz-question";
    field.dataset.questionId = question.question_id;
    field.dataset.questionType = question.question_type;
    field.innerHTML = `<h3>${question.ordinal}. ${escapeHtml(question.stem)}</h3>`;
    if (question.question_type === "short_answer") {
      const textarea = document.createElement("textarea");
      textarea.rows = 3;
      textarea.name = question.question_id;
      textarea.placeholder = "Short answer";
      field.append(textarea);
    } else {
      for (const option of question.options) {
        const label = document.createElement("label");
        label.className = "quiz-option";
        const input = document.createElement("input");
        input.type = question.question_type === "single_choice" ? "radio" : "checkbox";
        input.name = question.question_id;
        input.value = option.id;
        label.append(input, document.createTextNode(`${option.id}. ${option.text}`));
        field.append(label);
      }
    }
    form.append(field);
  }
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Submit Answers";
  form.append(submit);
}

async function submitQuiz(event) {
  event.preventDefault();
  if (!state.activeQuiz) throw new Error("Load a quiz first.");
  await run("quiz-output", async () => {
    const answers = state.activeQuiz.questions.map((question) => {
      if (question.question_type === "short_answer") {
        const text = document.querySelector(`textarea[name="${question.question_id}"]`).value;
        return { question_id: question.question_id, text };
      }
      const selected = Array.from(document.querySelectorAll(`input[name="${question.question_id}"]:checked`)).map((input) => input.value);
      return { question_id: question.question_id, selected_option_ids: selected };
    });
    const result = await api(`/quizzes/${state.activeQuiz.quiz_id}/submit`, {
      method: "POST",
      body: JSON.stringify({
        idempotency_key: `ui-${state.activeQuiz.quiz_id}-${Date.now()}`,
        answers,
      }),
    });
    renderQuizResult(result);
    await loadMastery();
    return result;
  });
}

function renderQuizResult(result) {
  const list = $("quiz-result");
  list.innerHTML = "";
  const summary = document.createElement("article");
  summary.className = "card result-card";
  summary.innerHTML = `
    <div class="card-title">
      <h3>Submission ${escapeHtml(result.status)}</h3>
      <span class="score">${formatScore(result.total_score)} / ${formatScore(result.max_score)}</span>
    </div>
    <div class="meter"><span style="width: ${scorePercent(result.total_score, result.max_score)}%"></span></div>
  `;
  list.append(summary);
  for (const item of result.question_results || []) {
    const card = document.createElement("article");
    card.className = "card compact";
    card.innerHTML = `
      <div class="card-title">
        <h3>${escapeHtml(item.grading_method)}</h3>
        <span class="status ${item.correct === false ? "bad" : "ok"}">${formatScore(item.score)} / ${formatScore(item.max_score)}</span>
      </div>
      ${item.feedback_text ? `<p>${escapeHtml(item.feedback_text)}</p>` : ""}
      <div class="meta"><span>${escapeHtml(item.question_id)}</span></div>
    `;
    list.append(card);
  }
}

async function loadMastery() {
  return run("mastery-output", async () => {
    const mastery = await api(`/courses/${activeCourseId()}/mastery`);
    renderMastery(mastery);
    return mastery;
  });
}

async function loadWrongbook() {
  return run("mastery-output", async () => {
    const gaps = await api(`/courses/${activeCourseId()}/wrongbook`);
    renderGaps(gaps);
    return gaps;
  });
}

async function selectReviewTargets() {
  return run("mastery-output", async () => {
    const response = await api(`/courses/${activeCourseId()}/review-targets`, {
      method: "POST",
      body: JSON.stringify({ limit: 5, exploration_ratio: 0.3 }),
    });
    renderReviewTargets(response);
    return response;
  });
}

function renderMastery(mastery) {
  const list = $("mastery-list");
  list.innerHTML = "";
  for (const item of mastery) {
    const card = document.createElement("article");
    card.className = "card compact";
    card.innerHTML = `
      <div class="card-title">
        <h3>${escapeHtml(item.title || item.knowledge_node_id)}</h3>
        <span class="score">${Math.round(item.mastery_estimate * 100)}%</span>
      </div>
      <div class="meter"><span style="width: ${scorePercent(item.mastery_estimate, 1)}%"></span></div>
      <div class="meta"><span>${item.evidence_count} evidence</span><span>${formatDate(item.updated_at)}</span></div>
    `;
    list.append(card);
  }
}

function renderGaps(gaps) {
  const list = $("mastery-list");
  list.innerHTML = "";
  for (const gap of gaps) {
    const card = document.createElement("article");
    card.className = "card compact";
    card.innerHTML = `
      <div class="card-title">
        <h3>${escapeHtml(gap.title)}</h3>
        <span class="status warn">${escapeHtml(gap.gap_type)}</span>
      </div>
      <p>${escapeHtml(gap.status)} / confidence ${Math.round(gap.confidence * 100)}%</p>
      <div class="meta"><span>${gap.evidence_count} evidence</span><span>${formatDate(gap.updated_at)}</span></div>
    `;
    list.append(card);
  }
}

function renderReviewTargets(response) {
  const list = $("mastery-list");
  list.innerHTML = "";
  for (const target of response.targets || []) {
    const card = document.createElement("article");
    card.className = "card compact";
    card.innerHTML = `
      <div class="card-title">
        <h3>${escapeHtml(target.title)}</h3>
        <span class="score">${formatScore(target.priority)}</span>
      </div>
      <p>${escapeHtml(target.reason)}</p>
      <div class="meta">
        <span>${target.mastery_estimate == null ? "no mastery" : `${Math.round(target.mastery_estimate * 100)}% mastery`}</span>
        <span>${target.evidence_count} evidence</span>
      </div>
    `;
    list.append(card);
  }
}

function defaultExamDate() {
  const date = new Date();
  date.setDate(date.getDate() + 7);
  return date.toISOString().slice(0, 10);
}

async function generatePlan() {
  return run("plans-output", async () => {
    const plan = await api(`/courses/${activeCourseId()}/plan`, {
      method: "POST",
      body: JSON.stringify({
        exam_date: $("exam-date").value,
        daily_minutes: Number($("daily-minutes").value),
        target_score: Number($("target-score").value),
      }),
    });
    renderPlanDetail(plan);
    await loadPlans(false);
    return plan;
  });
}

async function loadPlans(writeOutput = true) {
  const outputId = writeOutput ? "plans-output" : null;
  return run(outputId, async () => {
    const plans = await api(`/courses/${activeCourseId()}/plans`);
    state.plans = plans;
    const list = $("plan-list");
    list.innerHTML = "";
    for (const plan of plans) {
      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `
        <div class="card-title">
          <h3>Plan v${plan.version_number}</h3>
          <span class="status ${statusClass(plan.status)}">${escapeHtml(plan.status)}</span>
        </div>
        <p>${plan.exam_date} / ${plan.daily_minutes} min/day / target ${plan.target_score}</p>
        <div class="meta"><span>${plan.task_count} tasks</span><span>${formatDate(plan.created_at)}</span></div>
      `;
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = "Open";
      button.addEventListener("click", () => openPlan(plan.id));
      card.append(button);
      list.append(card);
    }
    return plans;
  });
}

async function openPlan(planId) {
  return run("plans-output", async () => {
    const plan = await api(`/plans/${planId}`);
    renderPlanDetail(plan);
    return plan;
  });
}

function renderPlanDetail(plan) {
  const detail = $("plan-detail");
  detail.innerHTML = "";
  const header = document.createElement("div");
  header.className = "summary-strip";
  header.innerHTML = `
    <span>Plan v${plan.version_number}</span>
    <span>${plan.exam_date}</span>
    <span>${plan.daily_minutes} min/day</span>
    <span>${plan.tasks?.length || 0} tasks</span>
  `;
  detail.append(header);

  for (const task of plan.tasks || []) {
    const row = document.createElement("article");
    row.className = "task";
    row.innerHTML = `
      <div>
        <div class="card-title">
          <h3>${escapeHtml(task.title)}</h3>
          <span class="status ${statusClass(task.status)}">${escapeHtml(task.status)}</span>
        </div>
        <p>${task.scheduled_date} / ${task.estimated_minutes} min / priority ${task.priority}</p>
        <div class="meta">${(task.targets || []).map((target) => `<span>${escapeHtml(target.title || target.knowledge_node_id)} · ${escapeHtml(target.target_role)}</span>`).join("")}</div>
      </div>
    `;
    const select = document.createElement("select");
    select.className = "task-status";
    for (const status of ["pending", "in_progress", "completed", "skipped"]) {
      const option = document.createElement("option");
      option.value = status;
      option.textContent = status.replace("_", " ");
      option.selected = status === task.status;
      select.append(option);
    }
    select.addEventListener("change", () => updateTaskStatus(task.id, select.value));
    row.append(select);
    detail.append(row);
  }
}

async function updateTaskStatus(taskId, status) {
  return run("plans-output", () => api(`/tasks/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  }));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function formatScore(value) {
  return Number(value || 0).toLocaleString([], { maximumFractionDigits: 2 });
}

function scorePercent(score, maxScore) {
  const max = Number(maxScore || 0);
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, Math.round((Number(score || 0) / max) * 100)));
}

function statusClass(status) {
  if (["ok", "ready", "succeeded", "active", "completed", "submitted", "open"].includes(status)) return "ok";
  if (["failed", "cancelled", "error"].includes(status)) return "bad";
  if (["pending", "running", "retry_wait", "building", "in_progress"].includes(status)) return "warn";
  return "";
}

function bindEvents() {
  $("health-check").addEventListener("click", checkHealth);
  $("load-settings").addEventListener("click", loadSettings);
  $("save-mock-settings").addEventListener("click", saveMockSettings);
  $("refresh-courses").addEventListener("click", refreshCourses);
  $("course-form").addEventListener("submit", createCourse);
  $("course-select").addEventListener("change", () => {
    state.activeCourseId = $("course-select").value;
    state.framework = null;
    state.activeQuiz = null;
    state.plans = [];
    localStorage.setItem("studymate.activeCourseId", state.activeCourseId);
    refreshMaterials(false).catch(() => undefined);
    $("knowledge-tree").innerHTML = "";
    $("knowledge-summary").innerHTML = "";
    $("quiz-form").innerHTML = "";
    $("quiz-result").innerHTML = "";
    $("mastery-list").innerHTML = "";
    $("plan-list").innerHTML = "";
    $("plan-detail").innerHTML = "";
    updateWorkflow();
  });
  $("upload-form").addEventListener("submit", uploadMaterial);
  $("refresh-materials").addEventListener("click", () => refreshMaterials(true));
  $("search-form").addEventListener("submit", searchMaterials);
  $("job-form").addEventListener("submit", getJob);
  $("poll-last-job").addEventListener("click", () => run("jobs-output", () => pollJob($("job-id").value || state.lastJobId)));
  $("build-knowledge").addEventListener("click", buildKnowledge);
  $("load-knowledge").addEventListener("click", loadKnowledge);
  $("load-versions").addEventListener("click", loadVersions);
  $("generate-quiz").addEventListener("click", generateQuiz);
  $("load-quiz").addEventListener("click", loadQuiz);
  $("quiz-form").addEventListener("submit", submitQuiz);
  $("load-mastery").addEventListener("click", loadMastery);
  $("load-wrongbook").addEventListener("click", loadWrongbook);
  $("select-review").addEventListener("click", selectReviewTargets);
  $("generate-plan").addEventListener("click", generatePlan);
  $("load-plans").addEventListener("click", () => loadPlans(true));
}

async function boot() {
  bindEvents();
  $("exam-date").value = defaultExamDate();
  await checkHealth();
  await loadSettings().catch(() => undefined);
  await refreshCourses().catch(() => undefined);
}

boot();
