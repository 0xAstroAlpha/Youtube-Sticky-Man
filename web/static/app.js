const dropArea = document.getElementById('drop-area');
const fileInput = document.getElementById('script-file');
const fileMessage = document.querySelector('.file-message');
// Custom Auth Logic
let appPwd = localStorage.getItem('app_pwd');
if (!appPwd) {
    appPwd = prompt("Enter App Password:");
    if (appPwd) {
        localStorage.setItem('app_pwd', appPwd);
    }
}

const originalFetch = window.fetch;
window.fetch = async function() {
    let [resource, config] = arguments;
    if (!config) config = {};
    if (!config.headers) config.headers = {};
    config.headers['X-App-Password'] = appPwd || '';
    
    let res = await originalFetch(resource, config);
    if (res.status === 401) {
        localStorage.removeItem('app_pwd');
        alert("Invalid Password. Please refresh to try again.");
    }
    return res;
};

const form = document.getElementById('upload-form');
const generateBtn = document.getElementById('generate-btn');
const btnText = document.querySelector('.btn-text');
const spinner = document.getElementById('spinner');
const terminalContainer = document.getElementById('terminal-container');
const terminal = document.getElementById('terminal');

// Tab Logic
function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(t => t.classList.add('hidden'));
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    
    document.getElementById(tabId).classList.remove('hidden');
    event.currentTarget.classList.add('active');
}

// Drag and drop effects
['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
    dropArea.addEventListener(eventName, preventDefaults, false);
});

function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
}

['dragenter', 'dragover'].forEach(eventName => {
    dropArea.addEventListener(eventName, () => dropArea.classList.add('dragover'), false);
});

['dragleave', 'drop'].forEach(eventName => {
    dropArea.addEventListener(eventName, () => dropArea.classList.remove('dragover'), false);
});

dropArea.addEventListener('drop', handleDrop, false);

function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;
    fileInput.files = files;
    updateFileMessage();
}

fileInput.addEventListener('change', updateFileMessage);

function updateFileMessage() {
    if (fileInput.files.length > 0) {
        fileMessage.textContent = fileInput.files[0].name;
        fileMessage.style.color = '#00f2fe';
    } else {
        fileMessage.textContent = 'Drag & drop your script here or click to browse';
        fileMessage.style.color = 'var(--text-muted)';
    }
}

function appendLog(element, text) {
    const p = document.createElement('p');
    p.textContent = text;
    if (text.includes('[INFO]') || text.includes('>>>')) p.classList.add('info');
    if (text.includes('[ERROR]') || text.includes('[WARNING]')) p.classList.add('error');
    if (text.includes('[SUCCESS]')) p.classList.add('success');
    element.appendChild(p);
    element.scrollTop = element.scrollHeight;
}

// CREATE TAB SUBMISSION
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    if (fileInput.files.length === 0) {
        alert('Please select a file first!');
        return;
    }

    btnText.classList.add('hidden');
    spinner.classList.remove('hidden');
    generateBtn.disabled = true;
    terminalContainer.classList.remove('hidden');
    terminal.innerHTML = '';
    
    appendLog(terminal, '[SYSTEM] Initializing secure connection to Auto-Sticky-Man core...');

    const formData = new FormData(form);
    
    try {
        const response = await fetch('/api/process', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            appendLog(terminal, `[SYSTEM] Script uploaded successfully. Initializing workspace: ${data.project_name}`);

            const streamUrl = `/api/stream?project_name=${encodeURIComponent(data.project_name)}&file_path=${encodeURIComponent(data.file_path)}&voice_id=${encodeURIComponent(data.voice_id)}&model_id=${encodeURIComponent(data.model_id)}&pwd=${encodeURIComponent(appPwd || '')}`;
            const eventSource = new EventSource(streamUrl);
            
            eventSource.onmessage = function(event) {
                if (event.data === '[DONE]') {
                    eventSource.close();
                    appendLog(terminal, '[SYSTEM] Execution Terminated Safely.');
                    btnText.classList.remove('hidden');
                    spinner.classList.add('hidden');
                    generateBtn.disabled = false;
                    btnText.textContent = "Pipeline Completed!";
                    setTimeout(() => { btnText.textContent = "Generate Video Assets"; }, 3000);
                } else {
                    appendLog(terminal, event.data);
                }
            };
            
            eventSource.onerror = function(err) {
                eventSource.close();
                appendLog(terminal, '[ERROR] Connection to streaming server lost. Ensure backend is running.');
                btnText.classList.remove('hidden');
                spinner.classList.add('hidden');
                generateBtn.disabled = false;
            };
            
        } else {
            appendLog(terminal, '[ERROR] Upload failed.');
            btnText.classList.remove('hidden');
            spinner.classList.add('hidden');
            generateBtn.disabled = false;
        }
    } catch (err) {
        appendLog(terminal, `[ERROR] ${err.message}`);
        btnText.classList.remove('hidden');
        spinner.classList.add('hidden');
        generateBtn.disabled = false;
    }
});

// MANAGE PROJECTS TAB
async function fetchProjects() {
    const selector = document.getElementById('project-list');
    selector.innerHTML = '<option value="">Loading...</option>';
    
    try {
        const res = await fetch('/api/projects');
        const data = await res.json();
        
        selector.innerHTML = '<option value="">-- Select a project --</option>';
        data.projects.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p;
            opt.textContent = p.toUpperCase();
            selector.appendChild(opt);
        });
        document.getElementById('project-details').classList.add('hidden');
    } catch (e) {
        selector.innerHTML = '<option value="">Error loading projects</option>';
    }
}

async function loadProjectDetails() {
    const projName = document.getElementById('project-list').value;
    const grid = document.getElementById('chunks-grid');
    const stitchBtn = document.getElementById('stitch-btn');
    const detailsDiv = document.getElementById('project-details');
    
    if (!projName) {
        detailsDiv.classList.add('hidden');
        return;
    }
    
    grid.innerHTML = '<div style="color: white">Scanning image folders and auditing pacing...</div>';
    detailsDiv.classList.remove('hidden');
    
    try {
        const res = await fetch(`/api/projects/${projName}`);
        const data = await res.json();
        
        grid.innerHTML = '';
        
        // Add Download Video button at the top if video is ready
        if (data.video_ready) {
            const vidCard = document.createElement('div');
            vidCard.className = 'chunk-card ready';
            vidCard.style.gridColumn = '1 / -1';
            vidCard.style.textAlign = 'center';
            vidCard.innerHTML = `
                <h3>🎉 Video Ready!</h3>
                <a href="/api/projects/${projName}/download/video?pwd=${encodeURIComponent(appPwd || '')}" class="action-btn" style="display:inline-block; margin-top:10px; background:#00f2fe; color:#000; text-decoration:none;">⬇️ Download Final Video</a>
            `;
            grid.appendChild(vidCard);
        }
        
        data.chunks.forEach(c => {
            const card = document.createElement('div');
            card.className = `chunk-card ${c.ready ? 'ready' : 'waiting'}`;
            
            const auditClass = c.audit_pass ? 'audit-pass' : 'audit-fail';
            const auditText = c.audit_pass ? `✅ Max pause: ${c.max_duration}s` : `⚠️ Long pause: ${c.max_duration}s`;
            
            card.innerHTML = `
                <h3>Chunk ${c.chunk}</h3>
                <div class="stats">
                    <p>Prompts: <span>${c.prompts}</span></p>
                    <p>Images Found: <span>${c.images}/${c.prompts}</span></p>
                </div>
                <div class="audit-badge ${auditClass}">${auditText}</div>
                <div class="status-badge">${c.ready ? '🟢 Ready to Stitch' : '🟡 Missing Images'}</div>
                
                <div style="margin: 10px 0; display:flex; gap:5px; flex-wrap:wrap;">
                    <a href="/api/projects/${projName}/download/prompts?pwd=${encodeURIComponent(appPwd || '')}" class="action-btn" style="flex:1; text-align:center; font-size:0.8rem; text-decoration:none;">⬇️ Prompts</a>
                    <a href="/api/projects/${projName}/download/audio?pwd=${encodeURIComponent(appPwd || '')}" class="action-btn" style="flex:1; text-align:center; font-size:0.8rem; text-decoration:none;">⬇️ Audio</a>
                </div>

                ${!c.ready ? `
                <div style="margin-bottom: 10px; padding:10px; border:1px dashed rgba(255,255,255,0.3); border-radius:5px; text-align:center;">
                    <label style="font-size:0.8rem; color:#aaa;">Upload Images (001.png, ...)</label>
                    <input type="file" multiple accept="image/*" onchange="uploadImages(event, '${projName}', '${c.chunk}')" style="display:block; width:100%; margin-top:5px; font-size:0.8rem;">
                </div>
                ` : ''}

                <div class="chunk-actions">
                    <button class="action-btn reprompt-btn" onclick="repromptChunk('${projName}', '${c.chunk}')">🔄 Regenerate</button>
                    ${!c.audit_pass ? `<button class="action-btn reprompt-btn" style="background: rgba(255, 60, 60, 0.2);" onclick="surgeryChunk('${projName}', '${c.chunk}')">✂️ Fix >8s Scenes</button>` : ''}
                    <button class="action-btn stitch-chunk-btn" onclick="stitchSingleChunk('${projName}', '${c.chunk}')" ${c.ready ? '' : 'disabled'}>🎬 Stitch Chunk</button>
                </div>
            `;
            grid.appendChild(card);
        });
        
        if (data.total_ready) {
            stitchBtn.disabled = false;
            stitchBtn.classList.remove('disabled-btn');
        } else {
            stitchBtn.disabled = true;
            stitchBtn.classList.add('disabled-btn');
        }
    } catch (e) {
        grid.innerHTML = '<div style="color: red">Error loading details.</div>';
    }
}

async function uploadImages(event, projName, chunkId) {
    const files = event.target.files;
    if (files.length === 0) return;
    
    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
        formData.append("files", files[i]);
    }
    
    const originalText = event.target.previousElementSibling.textContent;
    event.target.previousElementSibling.textContent = "Uploading...";
    event.target.disabled = true;
    
    const term = document.getElementById('stitch-terminal');
    appendLog(term, `[INFO] Uploading ${files.length} images for Chunk ${chunkId}...`);
    
    try {
        const res = await fetch(`/api/projects/${projName}/upload/${chunkId}`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (data.status === 'success') {
            appendLog(term, `[SUCCESS] ${data.message}`);
            loadProjectDetails(); // refresh
        } else {
            const errorMsg = data.message || (data.detail ? JSON.stringify(data.detail) : 'Unknown backend error');
            appendLog(term, `[ERROR] Upload failed: ${errorMsg}`);
            alert('Upload failed: ' + errorMsg);
            event.target.previousElementSibling.textContent = originalText;
            event.target.disabled = false;
        }
    } catch (e) {
        appendLog(term, `[ERROR] Upload network error: ${e.message}`);
        alert('Upload error');
        event.target.previousElementSibling.textContent = originalText;
        event.target.disabled = false;
    }
}

async function surgeryChunk(projName, chunkId) {
    const termContainer = document.getElementById('stitch-terminal-container');
    const term = document.getElementById('stitch-terminal');
    
    termContainer.classList.remove('hidden');
    term.innerHTML = '';
    
    const streamUrl = `/api/projects/${projName}/surgery/${chunkId}?pwd=${encodeURIComponent(appPwd || '')}`;
    const eventSource = new EventSource(streamUrl);
    
    eventSource.onmessage = function(event) {
        if (event.data === '[DONE]') {
            eventSource.close();
            appendLog(term, '[SYSTEM] Surgery Completed! Refreshing Dashboard...');
            loadProjectDetails();
        } else {
            appendLog(term, event.data);
        }
    };
    
    eventSource.onerror = function(err) {
        eventSource.close();
        appendLog(term, '[ERROR] Connection lost during surgery.');
    };
}

async function repromptChunk(projName, chunkId) {
    const termContainer = document.getElementById('stitch-terminal-container');
    const term = document.getElementById('stitch-terminal');
    
    termContainer.classList.remove('hidden');
    term.innerHTML = '';
    
    const streamUrl = `/api/projects/${projName}/re-prompt/${chunkId}?pwd=${encodeURIComponent(appPwd || '')}`;
    const eventSource = new EventSource(streamUrl);
    
    eventSource.onmessage = function(event) {
        if (event.data === '[DONE]') {
            eventSource.close();
            appendLog(term, '[SYSTEM] Regeneration Completed! Refreshing Dashboard...');
            loadProjectDetails();
        } else {
            appendLog(term, event.data);
        }
    };
    
    eventSource.onerror = function(err) {
        eventSource.close();
        appendLog(term, '[ERROR] Connection lost during regeneration.');
    };
}

async function stitchSingleChunk(projName, chunkId) {
    const termContainer = document.getElementById('stitch-terminal-container');
    const term = document.getElementById('stitch-terminal');
    
    termContainer.classList.remove('hidden');
    term.innerHTML = '';
    
    const streamUrl = `/api/projects/${projName}/stitch/${chunkId}?pwd=${encodeURIComponent(appPwd || '')}`;
    const eventSource = new EventSource(streamUrl);
    
    eventSource.onmessage = function(event) {
        if (event.data === '[DONE]') {
            eventSource.close();
            appendLog(term, '[SYSTEM] Single Chunk Stitching Completed!');
        } else {
            appendLog(term, event.data);
        }
    };
    
    eventSource.onerror = function(err) {
        eventSource.close();
        appendLog(term, '[ERROR] Connection lost during stitching.');
    };
}

async function stitchVideo() {
    const projName = document.getElementById('project-list').value;
    if (!projName) return;
    
    const termContainer = document.getElementById('stitch-terminal-container');
    const term = document.getElementById('stitch-terminal');
    const btn = document.getElementById('stitch-btn');
    const sText = document.querySelector('.stitch-btn-text');
    const sSpin = document.getElementById('stitch-spinner');
    
    termContainer.classList.remove('hidden');
    term.innerHTML = '';
    
    btn.disabled = true;
    sText.classList.add('hidden');
    sSpin.classList.remove('hidden');
    
    const streamUrl = `/api/projects/${projName}/stitch?pwd=${encodeURIComponent(appPwd || '')}`;
    const eventSource = new EventSource(streamUrl);
    
    eventSource.onmessage = function(event) {
        if (event.data === '[DONE]') {
            eventSource.close();
            appendLog(term, '[SYSTEM] Full Stitching Completed Successfully!');
            sText.classList.remove('hidden');
            sSpin.classList.add('hidden');
            btn.disabled = false;
            sText.textContent = "Final Video Rendered!";
        } else {
            appendLog(term, event.data);
        }
    };
    
    eventSource.onerror = function(err) {
        eventSource.close();
        appendLog(term, '[ERROR] Connection lost during render.');
        sText.classList.remove('hidden');
        sSpin.classList.add('hidden');
        btn.disabled = false;
    };
}
