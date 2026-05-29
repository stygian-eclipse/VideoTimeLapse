const form = document.getElementById("timelapse-form");
const submitBtn = document.getElementById("submit-btn");
const statusBox = document.getElementById("status-box");
const downloadLink = document.getElementById("download-link");

let pollTimer = null;

function setStatus(text) {
    statusBox.textContent = text;
    statusBox.scrollTop = statusBox.scrollHeight;
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

    const filesInput = document.getElementById("files");
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
        const payload = await response.json();
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
