"use strict";
(() => {
  const form = document.getElementById("copilot-form");
  if (!form) return;
  const button = document.getElementById("copilot-submit");
  const status = document.getElementById("copilot-status");
  const error = document.getElementById("copilot-error");
  const result = document.getElementById("copilot-result");
  const choices = document.querySelectorAll(".copilot-suggestion");
  choices.forEach(choice => choice.addEventListener("click", () => {
    form.elements.feature.value = choice.dataset.feature;
    if (form.elements.crm_task) form.elements.crm_task.value = choice.dataset.crmTask || "";
    form.elements.question.value = choice.dataset.question;
    form.elements.question.focus();
  }));
  form.elements.feature.addEventListener("change", () => { if (form.elements.crm_task) form.elements.crm_task.value = ""; });
  function list(id, values) {
    const target = document.getElementById(id);
    target.replaceChildren();
    values.forEach(value => { const li = document.createElement("li"); li.textContent = value; target.appendChild(li); });
  }
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (button.disabled) return;
    const question = form.elements.question.value;
    button.disabled = true;
    choices.forEach(choice => { choice.disabled = true; });
    form.setAttribute("aria-busy", "true");
    status.textContent = "Consultando los datos autorizados…";
    error.hidden = true;
    result.hidden = true;
    try {
      const response = await fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin", cache: "no-store" });
      const data = await response.json();
      if (!response.ok) {
        // Unknown server state keeps the same key; never automatically retry a provider call.
        if (response.status !== 503 && response.status !== 409) form.elements.request_key.value = crypto.randomUUID();
        throw new Error(data.error || "No se pudo completar la consulta.");
      }
      document.getElementById("copilot-answer").textContent = data.answer;
      list("copilot-recommendations", data.recommendations);
      list("copilot-limitations", data.limitations);
      list("copilot-sources", data.sources);
      const providerInfo = document.getElementById("copilot-provider");
      if (providerInfo && data.delivery) providerInfo.textContent = `Proveedor: ${data.delivery.provider} · Modelo: ${data.delivery.model}${data.delivery.fallback ? " · Respaldo local: el proveedor externo no completó una respuesta válida. No hubo reintento automático." : ""}`;
      const budgetInfo = document.getElementById("copilot-budget");
      if (budgetInfo && data.usage.budget?.configured) {
        const budget = data.usage.budget;
        budgetInfo.hidden = false;
        budgetInfo.textContent = `Presupuesto: ${budget.budget_usd} USD · Comprometido (incluye reservas): ${budget.committed_usd} USD · Disponible: ${budget.remaining_usd} USD${budget.alert ? ` · Alerta ${budget.alert}%` : ""}`;
      }
      document.getElementById("copilot-usage").textContent = `Consultas este mes: ${data.usage.calls} / ${data.usage.limit ?? "sin límite mensual"} · Plan ${data.usage.plan}`;
      form.elements.request_key.value = data.next_request_key;
      result.hidden = false;
      const history = document.getElementById("copilot-history");
      if (history) {
        const entry = document.createElement("details");
        const title = document.createElement("summary");
        title.textContent = question;
        const answer = document.createElement("p");
        answer.textContent = data.answer;
        const proposals = document.createElement("ul");
        data.recommendations.forEach(value => { const li = document.createElement("li"); li.textContent = value; proposals.appendChild(li); });
        entry.append(title, answer, proposals);
        history.prepend(entry);
        while (history.children.length > 5) history.lastElementChild.remove();
      }
      status.textContent = "Respuesta preparada. No se ha ejecutado ninguna acción comercial.";
    } catch (failure) {
      error.textContent = failure instanceof TypeError ? "Conexión interrumpida. No reenvíes una consulta de estado incierto; consulta el uso o recarga la página." : failure.message;
      error.hidden = false;
      status.textContent = "Consulta no completada.";
    } finally {
      button.disabled = false;
      choices.forEach(choice => { choice.disabled = false; });
      form.removeAttribute("aria-busy");
    }
  });
  window.addEventListener("pagehide", () => {
    document.getElementById("copilot-history")?.replaceChildren();
    result.hidden = true;
    for (const id of ["copilot-answer", "copilot-recommendations", "copilot-limitations", "copilot-sources"]) document.getElementById(id)?.replaceChildren();
    form.elements.question.value = "";
  });
})();
