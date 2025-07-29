const PASSWORD = atob("cHJhbnRhc2RhdHdhbnRh");

function checkAccess() {
  const input = document.getElementById("access").value;
  if (input === PASSWORD) {
    document.getElementById("access-gate").classList.add("hidden");
    document.getElementById("app").classList.remove("hidden");
  } else {
    document.getElementById("access-error").innerText = "Access Denied";
  }
}

async function analyze() {
  const input = document.getElementById("analyze-input");
  const result = document.getElementById("analyze-result");
  const status = document.getElementById("analyze-status");

  result.textContent = "";
  status.textContent = "Analyzing...";

  const res = await fetch("/analyze", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-user-agreement": "true"
    },
    body: JSON.stringify({ scene: input.value })
  });

  const data = await res.json();
  result.textContent = data.analysis || JSON.stringify(data);
  status.textContent = "";
}

async function edit() {
  const input = document.getElementById("edit-input");
  const result = document.getElementById("edit-result");
  const status = document.getElementById("edit-status");

  result.textContent = "";
  status.textContent = "Editing...";

  const res = await fetch("/editor", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-user-agreement": "true"
    },
    body: JSON.stringify({ scene: input.value })
  });

  const data = await res.json();
  result.textContent = data.rewrites || JSON.stringify(data);
  status.textContent = "";
}
