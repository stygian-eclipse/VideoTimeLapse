const form = document.getElementById("timelapse-form");
const submitBtn = document.getElementById("submit-btn");
const statusBox = document.getElementById("status-box");
const downloadLink = document.getElementById("download-link");
const selectedFilesBox = document.getElementById("selected-files");
const filesInput = document.getElementById("files");
const overlayRowsContainer = document.getElementById("overlay-rows");
const addOverlayBtn = document.getElementById("add-overlay-btn");
const overlaysJsonInput = document.getElementById("overlays_json");

const ALLOWED_PLACEMENTS = new Set([
    "upper left",
    "upper center",
    "upper right",
    "center",
    "lower left",
    "lower center",
    "lower right",
]);

let pollTimer = null;
let heartbeatTimer = null;

async function sendHeartbeat() {
    try {
        await fetch("/api/heartbeat", {
            method: "POST",
            cache: "no-store",
        });
    } catch (_err) {
        // Best effort only: UI should continue to function even if heartbeat fails.
    }
}

function startHeartbeat() {
    void sendHeartbeat();
    heartbeatTimer = setInterval(() => {
        void sendHeartbeat();
    }, 3000);
}

function setStatus(text) {
    statusBox.textContent = text;
    statusBox.scrollTop = statusBox.scrollHeight;
}

function naturalSortFileNames(names) {
    const splitRegex = /(\d+)/;
    const hasNumberRegex = /\d/;
    return [...names].sort((a, b) => {
        const aName = a.toLowerCase();
        const bName = b.toLowerCase();

        const aHasNumber = hasNumberRegex.test(aName);
        const bHasNumber = hasNumberRegex.test(bName);
        if (aHasNumber && !bHasNumber) {
            return -1;
        }
        if (!aHasNumber && bHasNumber) {
            return 1;
        }
        if (!aHasNumber && !bHasNumber) {
            return aName.localeCompare(bName);
        }

        const aParts = aName.split(splitRegex);
        const bParts = bName.split(splitRegex);
        const limit = Math.max(aParts.length, bParts.length);
        for (let i = 0; i < limit; i += 1) {
            const aPart = aParts[i] ?? "";
            const bPart = bParts[i] ?? "";
            const aNumeric = /^\d+$/.test(aPart);
            const bNumeric = /^\d+$/.test(bPart);
            if (aNumeric && bNumeric) {
                const diff = Number(aPart) - Number(bPart);
                if (diff !== 0) {
                    return diff;
                }
                continue;
            }
            const cmp = aPart.localeCompare(bPart);
            if (cmp !== 0) {
                return cmp;
            }
        }
        return 0;
    });
}

function renderSelectedFiles() {
    if (!filesInput.files || filesInput.files.length === 0) {
        selectedFilesBox.classList.add("hidden");
        selectedFilesBox.replaceChildren();
        return;
    }

    const fileNames = Array.from(filesInput.files).map((file) => file.name);
    const sorted = naturalSortFileNames(fileNames);
    selectedFilesBox.replaceChildren();

    const title = document.createElement("strong");
    title.textContent = "Selected files (natural order):";
    const list = document.createElement("ul");
    for (const name of sorted) {
        const item = document.createElement("li");
        item.textContent = name;
        list.appendChild(item);
    }
    selectedFilesBox.appendChild(title);
    selectedFilesBox.appendChild(list);
    selectedFilesBox.classList.remove("hidden");
}

function setMessages(messages, state, errorText) {
    const lines = Array.isArray(messages) ? [...messages] : [];
    if (state) {
        lines.push(`State: ${state}`);
    }
    if (errorText) {
        lines.push(`Error: ${errorText}`);
    }
    setStatus(lines.join("\n"));
}

function buildOverlayRow() {
    const row = document.createElement("div");
    row.className = "overlay-row";
    row.innerHTML = `
        <div class="overlay-grid">
            <label>Text
                <input type="text" data-overlay="text" maxlength="120" placeholder="#BeforeForever">
            </label>
            <label>Start (s)
                <input type="number" data-overlay="start_time" min="0" step="0.1" value="0">
            </label>
            <label>End (s)
                <input type="number" data-overlay="end_time" min="0" step="0.1" value="5">
            </label>
            <label>Placement
                <select data-overlay="placement">
                    <option value="upper left">upper left</option>
                    <option value="upper center">upper center</option>
                    <option value="upper right">upper right</option>
                    <option value="center">center</option>
                    <option value="lower left">lower left</option>
                    <option value="lower center" selected>lower center</option>
                    <option value="lower right">lower right</option>
                </select>
            </label>
            <label>Font size
                <input type="number" data-overlay="font_size" min="12" max="120" step="1" value="36">
            </label>
            <button type="button" class="remove-overlay-btn">Remove</button>
        </div>
    `;

    row.querySelector(".remove-overlay-btn").addEventListener("click", () => {
        row.remove();
        if (overlayRowsContainer.children.length === 0) {
            overlayRowsContainer.appendChild(buildOverlayRow());
        }
    });
    return row;
}

function collectValidatedOverlays() {
    const rows = Array.from(overlayRowsContainer.querySelectorAll(".overlay-row"));
    const overlays = [];
    for (let i = 0; i < rows.length; i += 1) {
        const row = rows[i];
        const index = i + 1;
        const text = row.querySelector('[data-overlay="text"]').value.trim();
        const startValue = row.querySelector('[data-overlay="start_time"]').value;
        const endValue = row.querySelector('[data-overlay="end_time"]').value;
        const placement = row.querySelector('[data-overlay="placement"]').value.trim().toLowerCase();
        const fontSizeValue = row.querySelector('[data-overlay="font_size"]').value;

        if (!text) {
            continue;
        }
        if (text.length > 120) {
            throw new Error(`Overlay row ${index}: text must be 120 characters or fewer.`);
        }

        const startTime = Number(startValue);
        const endTime = Number(endValue);
        const fontSize = Number(fontSizeValue);

        if (Number.isNaN(startTime) || startTime < 0) {
            throw new Error(`Overlay row ${index}: start time must be a number >= 0.`);
        }
        if (Number.isNaN(endTime) || endTime <= startTime) {
            throw new Error(`Overlay row ${index}: end time must be greater than start time.`);
        }
        if (!ALLOWED_PLACEMENTS.has(placement)) {
            throw new Error(`Overlay row ${index}: placement is invalid.`);
        }
        if (!Number.isInteger(fontSize) || fontSize < 12 || fontSize > 120) {
            throw new Error(`Overlay row ${index}: font size must be an integer between 12 and 120.`);
        }

        overlays.push({
            text,
            start_time: startTime,
            end_time: endTime,
            placement,
            font_size: fontSize,
        });
    }
    return overlays;
}

async function pollStatus(jobId) {
    try {
        const response = await fetch(`/api/status/${jobId}`);
        if (!response.ok) {
            throw new Error("Could not read job status.");
        }
        const data = await response.json();
        setMessages(data.messages, data.state, data.error || "");

        if (data.state === "completed") {
            clearInterval(pollTimer);
            submitBtn.disabled = false;
            submitBtn.textContent = "Generate Timelapse";
            if (data.download_url) {
                downloadLink.href = data.download_url;
                downloadLink.classList.remove("hidden");
            }
        } else if (data.state === "error") {
            clearInterval(pollTimer);
            submitBtn.disabled = false;
            submitBtn.textContent = "Generate Timelapse";
        }
    } catch (err) {
        clearInterval(pollTimer);
        submitBtn.disabled = false;
        submitBtn.textContent = "Generate Timelapse";
        setStatus(`Status polling failed: ${err.message}`);
    }
}

form.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!filesInput.files || filesInput.files.length < 2) {
        setStatus("Please select at least 2 MP4 files.");
        return;
    }

    let overlays = [];
    try {
        overlays = collectValidatedOverlays();
    } catch (err) {
        setStatus(`Error: ${err.message}`);
        return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Processing...";
    downloadLink.classList.add("hidden");
    downloadLink.href = "#";
    setStatus("Uploading files and starting processing...");

    overlaysJsonInput.value = JSON.stringify(overlays);
    const formData = new FormData(form);
    formData.set("overlays_json", overlaysJsonInput.value);
    if (!document.getElementById("use_crossfade").checked) {
        formData.set("use_crossfade", "false");
    } else {
        formData.set("use_crossfade", "true");
    }

    try {
        const response = await fetch("/api/process", {
            method: "POST",
            body: formData,
        });
        let payload = {};
        try {
            payload = await response.json();
        } catch (_err) {
            payload = {};
        }
        if (!response.ok) {
            throw new Error(payload.detail || "Processing could not start.");
        }

        const jobId = payload.job_id;
        if (!jobId) {
            throw new Error("Server returned no job id.");
        }
        setStatus("Processing started...");
        pollTimer = setInterval(() => pollStatus(jobId), 1500);
        await pollStatus(jobId);
    } catch (err) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Generate Timelapse";
        setStatus(`Error: ${err.message}`);
    }
});

filesInput.addEventListener("change", renderSelectedFiles);
addOverlayBtn.addEventListener("click", () => {
    overlayRowsContainer.appendChild(buildOverlayRow());
});
overlayRowsContainer.appendChild(buildOverlayRow());
startHeartbeat();

window.addEventListener("pagehide", () => {
    try {
        const blob = new Blob(["{}"], {type: "application/json"});
        navigator.sendBeacon("/api/heartbeat", blob);
    } catch (_err) {
        // Ignore beacon errors.
    }
});

window.addEventListener("beforeunload", () => {
    if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
    }
});
