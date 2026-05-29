const form = document.getElementById("timelapse-form");
const submitBtn = document.getElementById("submit-btn");
const statusBox = document.getElementById("status-box");
const downloadLink = document.getElementById("download-link");
const selectedFilesBox = document.getElementById("selected-files");
const filesInput = document.getElementById("files");

let pollTimer = null;

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

    submitBtn.disabled = true;
    submitBtn.textContent = "Processing...";
    downloadLink.classList.add("hidden");
    downloadLink.href = "#";
    setStatus("Uploading files and starting processing...");

    const formData = new FormData(form);
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
