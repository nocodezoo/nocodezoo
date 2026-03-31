<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <title>Create Video — Vybord v1.033</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,700&family=Playfair+Display:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
    <style>
        :root { --accent: #8309EE; --accent2: #146EF5; --green: #00ff88; }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'DM Sans', sans-serif; background: #0a0a0a; color: #fff; min-height: 100vh; }
        #bg-canvas { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 0; pointer-events: none; }
        .content { position: relative; z-index: 1; }
        .gradient-text { background: linear-gradient(135deg, var(--accent), var(--accent2)); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .section-card { background: #14141e; border: 1px solid #1e1e2e; border-radius: 1.25rem; padding: 1.5rem; margin-bottom: 1.25rem; }
        .step-badge { width: 32px; height: 32px; background: linear-gradient(135deg, var(--accent), var(--accent2)); border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.85rem; flex-shrink: 0; }
        .step-title { font-size: 1.1rem; font-weight: 700; color: #fff; }
        .form-input { background: #0d0d14; border: 1px solid #252535; border-radius: 0.75rem; padding: 0.8rem 1rem; color: #fff; width: 100%; font-size: 0.9rem; transition: border-color 0.2s; font-family: 'DM Sans', sans-serif; }
        .form-input:focus { border-color: var(--accent); outline: none; }
        .form-input::placeholder { color: #555; }
        .opt-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.5rem; }
        .opt-btn { padding: 0.6rem 0.5rem; border: 1px solid #252535; border-radius: 0.6rem; text-align: center; cursor: pointer; transition: all 0.2s; font-size: 0.8rem; color: #aaa; background: #0d0d14; }
        .opt-btn:hover { border-color: var(--accent); color: #fff; }
        .opt-btn.sel { border-color: var(--accent); background: rgba(131,9,238,0.15); color: #fff; }
        .color-row { display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center; }
        .swatch { width: 34px; height: 34px; border-radius: 50%; cursor: pointer; border: 2px solid transparent; transition: border-color 0.2s; flex-shrink: 0; }
        .swatch:hover { border-color: #555; }
        .swatch.sel { border-color: #fff; }
        .range-val { font-size: 0.8rem; color: #888; min-width: 2rem; text-align: right; }
        input[type=range] { -webkit-appearance: none; height: 6px; background: #1e1e2e; border-radius: 3px; width: 100%; }
        input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; background: linear-gradient(135deg, var(--accent), var(--accent2)); border-radius: 50%; cursor: pointer; }
        select.form-input { cursor: pointer; appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23888' d='M6 8L1 3h10z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 0.8rem center; padding-right: 2.2rem; }
        .btn-fetch { white-space: nowrap; padding: 0.5rem 1rem; border-radius: 0.6rem; border: 1px solid #8309EE; background: rgba(131,9,238,0.15); color: #8309EE; cursor: pointer; font-size: 0.85rem; }
    .btn-generate { width: 100%; padding: 1rem; background: linear-gradient(135deg, var(--accent), var(--accent2)); color: #fff; font-size: 1.1rem; font-weight: 700; border: none; border-radius: 1rem; cursor: pointer; transition: opacity 0.2s; font-family: 'DM Sans', sans-serif; }
        .btn-fetch { white-space: nowrap; padding: 0.5rem 1rem; border-radius: 0.6rem; border: 1px solid #8309EE; background: rgba(131,9,238,0.15); color: #8309EE; cursor: pointer; font-size: 0.85rem; }
    .btn-generate:hover { opacity: 0.85; }
        .btn-fetch { white-space: nowrap; padding: 0.5rem 1rem; border-radius: 0.6rem; border: 1px solid #8309EE; background: rgba(131,9,238,0.15); color: #8309EE; cursor: pointer; font-size: 0.85rem; }
    .btn-generate:disabled { opacity: 0.4; cursor: not-allowed; }
        .status-box { margin-top: 1rem; padding: 1rem; border-radius: 0.75rem; font-size: 0.88rem; display: none; background: #0d0d14; border: 1px solid #252535; }
        .status-box.ok { border-color: #00ff88; color: #00ff88; }
        .status-box.err { border-color: #ff4444; color: #ff6666; }
        .status-box.info { border-color: var(--accent2); color: var(--accent2); }
        .voice-btn { display: flex; align-items: center; gap: 0.5rem; padding: 0.6rem 0.8rem; border: 1px solid #252535; border-radius: 0.6rem; cursor: pointer; transition: all 0.2s; font-size: 0.82rem; color: #aaa; background: #0d0d14; }
        .voice-btn:hover { border-color: var(--accent); color: #fff; }
        .voice-btn.sel { border-color: var(--accent); background: rgba(131,9,238,0.15); color: #fff; }
        .section-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.1em; color: #555; margin-bottom: 0.75rem; font-weight: 600; }
        .divider { border-top: 1px solid #1e1e2e; margin: 1rem 0; }
        .logo { display: flex; align-items: center; gap: 0.5rem; text-decoration: none; }
        .logo-icon { width: 32px; height: 32px; background: linear-gradient(135deg, var(--accent), var(--accent2)); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 0.9rem; }
        .logo-text { font-weight: 700; font-size: 1.1rem; }
        .floating-shape { position: fixed; border: 1px solid rgba(131,9,238,0.08); border-radius: 50%; pointer-events: none; z-index: 0; animation: float 20s ease-in-out infinite; }
        @keyframes float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-30px)} }
        .accent-bar { width: 40px; height: 3px; background: linear-gradient(90deg, var(--accent), var(--accent2)); border-radius: 2px; margin-bottom: 0.75rem; }
    </style>
</head>
<body>
    <!-- Animated background canvas -->
    <canvas id="bg-canvas"></canvas>

    <!-- Decorative floating shapes -->
    <div class="floating-shape" style="width:300px;height:300px;top:10%;left:-5%;animation-delay:0s;opacity:0.3"></div>
    <div class="floating-shape" style="width:200px;height:200px;top:60%;right:-3%;animation-delay:-7s;opacity:0.2"></div>
    <div class="floating-shape" style="width:150px;height:150px;bottom:20%;left:10%;animation-delay:-14s;opacity:0.15"></div>

    <div class="content">
        <!-- Header -->
        <header class="sticky top-0 z-50 bg-[#0a0a0a]/90 backdrop-blur-md border-b border-[#1e1e2e]">
            <div class="max-w-lg mx-auto px-4 py-3 flex items-center justify-between">
                <a href="/" class="logo">
                    <div class="logo-icon">V</div>
                    <span class="logo-text gradient-text">Vybord</span>
                </a>
                <a href="/" class="text-sm text-[#666] hover:text-white transition-colors">← Back</a>
                <span style="background:#1e1e2e;border:1px solid #333;color:#555;border-radius:6px;padding:0.15rem 0.6rem;font-size:0.72rem;font-weight:600;letter-spacing:0.05em">v1.033</span>
            </div>
        </header>

        <main class="max-w-lg mx-auto px-4 py-6">
            <!-- Page header -->
            <div class="mb-6">
                <div class="accent-bar"></div>
                <h1 style="font-family:'Playfair Display',serif;font-size:clamp(1.6rem,5vw,2.2rem);font-weight:600;line-height:1.2;margin-bottom:0.4rem;">
                    Create Your Video
                </h1>
                <p class="text-[#666] text-sm">Configure every detail. We'll handle the rest.</p>
            </div>

            <form id="video-form" novalidate>

                <!-- Step 1: Property -->
                <div class="section-card">
                    <div class="flex items-center gap-3 mb-4">
                        <div class="step-badge">1</div>
                        <div class="step-title">Property</div>
                    </div>
                    <div class="space-y-3">
                        <div>
                            <label class="section-label">Listing URL</label>
                            <div style="display:flex;gap:0.5rem;align-items:center">
                                <input type="text" id="listing-url" class="form-input" placeholder="https://www.corcoran.com/... (listing URL)" style="flex:1">
                                <button type="button" id="lookup-btn" onclick="fetchPropertyDetails()" style="background:linear-gradient(135deg,#8309EE,#146EF5);color:#fff;border:none;border-radius:0.75rem;padding:0.7rem 1.1rem;font-size:0.85rem;font-weight:600;cursor:pointer;white-space:nowrap;font-family:'DM Sans',sans-serif">&#128269; Lookup</button>
                            </div>
                            <div id="address-display" style="color:#8309EE;font-size:0.9rem;margin-top:4px;font-weight:600"></div>
                            <div id="price-display" style="color:#00ff88;font-size:0.85rem;margin-top:2px"></div>
                            <div id="lookup-status" style="font-size:0.82rem;margin-top:4px;display:none"></div>
                            <input type="hidden" id="m-beds" value="">
                            <input type="hidden" id="m-baths" value="">
                            <input type="hidden" id="m-sqft" value="">
                            <input type="hidden" id="m-script" value="">
                            <div style="margin-top:0.75rem">
                                <button type="button" class="btn-fetch" onclick="openScanModal()" style="width:100%">&#128247; Scan / Paste Images &amp; Details</button>
                            </div>
                        </div>
                        <div>
                            <label class="section-label">Or Upload Images</label>
                            <input type="file" id="image-files" class="form-input" accept="image/*" multiple onchange="handleImgUpload(this.files)">
                                <div id="img-count" class="section-label" style="color:#888;font-size:0.8rem;margin-top:4px"></div>
                        </div>
                        <div>
                            <label class="section-label">Your Email (for delivery)</label>
                            <input type="email" id="user-email" class="form-input" placeholder="you@email.com">
                        </div>
                    </div>
                </div>

                <!-- Step 2: Voice -->
                <div class="section-card">
                    <div class="flex items-center gap-3 mb-4">
                        <div class="step-badge">2</div>
                        <div class="step-title">AI Voice</div>
                    </div>
                    <div class="grid grid-cols-2 gap-2" id="voice-grid">
                        <button type="button" class="voice-btn sel" onclick="selectVoice('CwhRBWXzGAHq8TQ4Fs17',this)">🎤 Roger</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('EXAVITQu4vr4xnSDxMaL',this)">🎤 Sarah</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('FGY2WhTYpPnrIDTdsKH5',this)">🎤 Laura</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('SOYHLrjzK2X1ezoPC6cr',this)">🎤 Harry</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('cgSgspJ2msm6clMCkdW9',this)">🎤 Jessica</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('IKne3meq5aSn9XLyUdCD',this)">🎤 Charlie</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('JBFqnCBsd6RMkjVDRZzb',this)">🎤 George</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('hpp4J3VqNfWAUOO0d1Us',this)">🎤 Bella</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('TX3LPaxmHKxFdv7VOQHJ',this)">🎤 Liam</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('bIHbv24MWmeRgasZH58o',this)">🎤 Will</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('onwK4e9ZLuTAKqWW03F9',this)">🎤 Daniel</button>
                        <button type="button" class="voice-btn" onclick="selectVoice('pNInz6obpgDQGcFmaJgB',this)">🎤 Adam</button>
                    </div>
                </div>

                <!-- Step 3: Captions -->
                <div class="section-card">
                    <div class="flex items-center gap-3 mb-4">
                        <div class="step-badge">3</div>
                        <div class="step-title">Captions (PyCaps)</div>
                    </div>
                    <div class="space-y-4">
                        <div>
                            <label class="section-label">Template</label>
                            <div class="opt-grid">
                                <button type="button" class="opt-btn sel" onclick="sel(this,'template','word-focus')">Word Focus</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'template','explosive')">Explosive</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'template','classic')">Classic</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'template','minimalist')">Minimal</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'template','hype')">Hype</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'template','retro-gaming')">Retro</button>
                            </div>
                        </div>
                        <div>
                            <label class="section-label">Font Size — <span id="fs-val">55</span>px</label>
                            <div class="flex items-center gap-3">
                                <span class="text-xs text-[#555]">20</span>
                                <input type="range" id="font-size" min="20" max="80" value="55" oninput="updateFs(this.value)">
                                <span class="text-xs text-[#555]">80</span>
                            </div>
                        </div>
                        <div>
                            <label class="section-label">Text Color</label>
                            <div class="color-row">
                                <div class="swatch sel" style="background:#FF69B4" onclick="selColor(this,'#FF69B4','textColor')"></div>
                                <div class="swatch" style="background:#FFFFFF" onclick="selColor(this,'#FFFFFF','textColor')"></div>
                                <div class="swatch" style="background:#FFFF00" onclick="selColor(this,'#FFFF00','textColor')"></div>
                                <div class="swatch" style="background:#00FF88" onclick="selColor(this,'#00FF88','textColor')"></div>
                                <div class="swatch" style="background:#FF4444" onclick="selColor(this,'#FF4444','textColor')"></div>
                                <div class="swatch" style="background:#00CCFF" onclick="selColor(this,'#00CCFF','textColor')"></div>
                                <div class="swatch" style="background:#FF9500" onclick="selColor(this,'#FF9500','textColor')"></div>
                                <div class="swatch" style="background:#ffffff22;border:1px dashed #555" onclick="selColor(this,'transparent','textColor')"></div>
                            </div>
                        </div>
                        <div>
                            <label class="section-label">Background</label>
                            <div class="color-row">
                                <div class="swatch sel" style="background:#000000" onclick="selColor(this,'#000000','bgColor')"></div>
                                <div class="swatch" style="background:#1a1a2e" onclick="selColor(this,'#1a1a2e','bgColor')"></div>
                                <div class="swatch" style="background:#2d1b4e" onclick="selColor(this,'#2d1b4e','bgColor')"></div>
                                <div class="swatch" style="background:#0a1628" onclick="selColor(this,'#0a1628','bgColor')"></div>
                                <div class="swatch" style="background:#1a0a0a" onclick="selColor(this,'#1a0a0a','bgColor')"></div>
                                <div class="swatch" style="background:#ffffff22;border:1px dashed #555" onclick="selColor(this,'transparent','bgColor')"></div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Step 4: Video Settings -->
                <div class="section-card">
                    <div class="flex items-center gap-3 mb-4">
                        <div class="step-badge">4</div>
                        <div class="step-title">Video Settings</div>
                    </div>
                    <div class="space-y-3">
                        <div>
                            <label class="section-label">Format / Ratio</label>
                            <select id="ratio" class="form-input" onchange="s.ratio=this.value">
                                <option value="16:9">16:9 — YouTube / Web</option>
                                <option value="9:16">9:16 — TikTok / Reels</option>
                            </select>
                        </div>
                        <div>
                            <label class="section-label">Duration</label>
                            <select id="duration" class="form-input" onchange="s.duration=this.value">
                                <option value="15">15 seconds</option>
                                <option value="30" selected>30 seconds</option>
                                <option value="40">40 seconds</option>
                                <option value="60">60 seconds</option>
                            </select>
                        </div>
                        <div>
                            <label class="section-label">Image Effect</label>
                            <div class="opt-grid">
                                <button type="button" class="opt-btn sel" onclick="sel(this,'effect','random')">🔀 Random</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'effect','zoom')">🔍 Zoom</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'effect','slow')">🐢 Slow</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'effect','vintage')">📺 Vintage</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'effect','glow')">✨ Glow</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'effect','contrast')">◐ Contrast</button>
                            </div>
                        </div>
                        <div>
                            <label class="section-label">Transition</label>
                            <div class="opt-grid">
                                <button type="button" class="opt-btn sel" onclick="sel(this,'transition','fade')">Fade</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'transition','slide')">Slide</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'transition','zoom')">Zoom</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'transition','none')">Cut</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'transition','blur')">Blur</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'transition','slideup')">Slide Up</button>
                            </div>
                        </div>
                        <div>
                            <label class="section-label">Images Per Slide</label>
                            <select id="imagesPerSlide" class="form-input" onchange="s.imagesPerSlide=parseInt(this.value)">
                                <option value="1" selected>1 image per slide</option>
                                <option value="2">2 images per slide</option>
                                <option value="3">3 images per slide</option>
                            </select>
                        </div>
                    </div>
                </div>

                <!-- Step 5: Music -->
                <div class="section-card">
                    <div class="flex items-center gap-3 mb-4">
                        <div class="step-badge">5</div>
                        <div class="step-title">Background Music</div>
                    </div>
                    <div class="space-y-3">
                        <div>
                            <label class="section-label">Music Preset</label>
                            <div class="opt-grid">
                                <button type="button" class="opt-btn sel" onclick="sel(this,'music','none')">🔇 None</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'music','upbeat')">🎵 Upbeat</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'music','chill')">🎵 Chill</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'music','cinematic')">🎵 Cinematic</button>
                                <button type="button" class="opt-btn" onclick="sel(this,'music','positive')">🎵 Positive</button>
                            </div>
                        </div>
                        <div>
                            <label class="section-label">Or Music URL</label>
                            <input type="text" id="music-url" class="form-input" placeholder="https://...mp3">
                        </div>
                        <div>
                            <label class="section-label">Or Upload MP3</label>
                            <input type="file" id="music-file" class="form-input" accept="audio/mp3,audio/*">
                        </div>
                    </div>
                </div>

                <!-- Step 6: CTA -->
                <div class="section-card">
                    <div class="flex items-center gap-3 mb-4">
                        <div class="step-badge">6</div>
                        <div class="step-title">Call to Action</div>
                    </div>
                    <div class="space-y-3">
                        <div>
                            <label class="section-label">CTA Button Text</label>
                            <input type="text" id="cta-text" class="form-input" placeholder="Schedule a Tour" value="Call today to schedule your private showing">
                        </div>
                        <div>
                            <label class="section-label">CTA URL (optional)</label>
                            <input type="text" id="cta-url" class="form-input" placeholder="https://...">
                        </div>
                    </div>
                </div>

                <!-- Generate -->
                <button type="button" class="btn-generate" id="gen-btn">
                    🚀 Generate Video
                </button>

                <div id="status" class="status-box"></div>

                <div class="mt-6 text-center text-xs text-[#444]">
                    By generating, you agree our AI may process this content.
                </div>
            </form>
        </main>

        <footer class="text-center py-8 text-xs text-[#333] mt-8">
            © 2026 Vybord · Built with OpenClaw
        </footer>
    </div>

    <script>

// Compress image: max 800px wide, 70% JPEG — keeps each image ~20KB base64
async function compressForUpload(dataUrl) {
    return new Promise(resolve => {
        const img = new Image();
        img.onload = () => {
            const canvas = document.createElement('canvas');
            const maxW = 800;
            let w = img.width, h = img.height;
            if (w > maxW) { h = Math.round(h * maxW / w); w = maxW; }
            else if (h > maxW) { w = Math.round(w * maxW / h); h = maxW; }
            canvas.width = w; canvas.height = h;
            canvas.getContext('2d').drawImage(img, 0, 0, w, h);
            resolve(canvas.toDataURL('image/jpeg', 0.70));
        };
        img.src = dataUrl;
    });
}

    // ── State
    // Wire up generate button after DOM is ready
    var genBtn = document.getElementById("gen-btn");
    if (genBtn) genBtn.addEventListener("click", function(e) { console.log("Button clicked"); handleSubmit(e); });

    var s = {
        voice: 'CwhRBWXzGAHq8TQ4Fs17',
        template: 'word-focus',
        fontSize: 55,
        textColor: '#FF69B4',
        effect: 'random',
        music: 'none',
        musicUrl: '',
        transition: 'fade',
        ratio: '16:9',
        duration: '30',
        cta: "Call today to schedule your private showing"
    };
    var selectedImages = [];
    var MAX_IMAGES = 15;
    var _modalSel = {};
    var _serverJobId = null;
    var _uploadedFiles = [];
    var CONCURRENT = 3;

    // ── sel() — scoped to .opt-group
    function sel(btn, key, val) {
        s[key] = val;
        // Remove .sel from all siblings with the same tag name
        var sib = btn.previousElementSibling;
        while (sib) {
            if (sib.classList && sib.classList.contains('opt-btn')) sib.classList.remove('sel');
            sib = sib.previousElementSibling;
        }
        var sib2 = btn.nextElementSibling;
        while (sib2) {
            if (sib2.classList && sib2.classList.contains('opt-btn')) sib2.classList.remove('sel');
            sib2 = sib2.nextElementSibling;
        }
        btn.classList.add('sel');
    }

    // ── Voice picker
    function selectVoice(id, btn) {
        var grid = btn.closest('#voice-grid');
        if (!grid) return;
        grid.querySelectorAll('.voice-btn').forEach(function(b) { b.classList.remove('sel'); });
        btn.classList.add('sel');
        s.voice = id;
    }

    // ── Color swatch
    function selColor(el, color, key) {
        s[key] = color;
        var sib = el.previousElementSibling;
        while (sib) {
            if (sib.classList && sib.classList.contains('swatch')) sib.classList.remove('sel');
            sib = sib.previousElementSibling;
        }
        var sib2 = el.nextElementSibling;
        while (sib2) {
            if (sib2.classList && sib2.classList.contains('swatch')) sib2.classList.remove('sel');
            sib2 = sib2.nextElementSibling;
        }
        el.classList.add('sel');
    }

    // ── Font size
    function updateFs(val) {
        s.fontSize = parseInt(val);
        document.getElementById('fs-val').textContent = val;
    }

    // ── Status display
    function setStatus(msg, type) {
        var el = document.getElementById('status');
        if (!el) { console.error('STATUS ELEMENT NOT FOUND'); return; }
        el.style.display = 'block';
        el.style.visibility = 'visible';
        el.innerHTML = msg;
        el.className = 'status-box ' + (type || 'info');
        console.log('Status set:', msg.substring(0, 100));
        
    }

    // ── Simple file upload (existing behavior)
    function handleImgUpload(files) {
        if (!files || files.length === 0) return;
        _uploadedFiles = [];
        Array.from(files).forEach(function(file) {
            var reader = new FileReader();
            reader.onload = function(e) {
                var ext = file.name.split('.').pop().replace('jpeg', 'jpg');
                _uploadedFiles.push({ name: file.name, data: e.target.result.split(',')[1] });
                if (_uploadedFiles.length === 1) {
                    document.getElementById('img-count').textContent = _uploadedFiles.length + ' image(s) selected';
                }
            };
            reader.readAsDataURL(file);
        });
    }

    // ── Auto-generate voiceover
    function generateAutoScript() {
        var urlInput = document.getElementById('listing-url');
        if (!urlInput || !urlInput.value.trim()) {
            setStatus('⚠️ Enter a listing URL first to auto-generate the voiceover.', 'err');
            return;
        }
        setStatus('⏳ Fetching listing details...', 'info');
        var scriptTag = document.getElementById('auto-script');
        if (scriptTag) scriptTag.textContent = '';
        var address = document.getElementById('address-display');
        if (address) address.textContent = '';
        var price = document.getElementById('price-display');
        if (price) price.textContent = '';

        fetchListing().then(function(data) {
            if (!data) {
                setStatus('⚠️ Could not fetch listing details. Try pasting HTML manually.', 'err');
                return;
            }
            var address2 = data.address || '';
            var price2 = data.price || '';
            var beds = data.beds || '';
            var sqft = data.sqft || '';
            var script = [];
            if (address2) script.push('Beautiful home at ' + address2);
            if (price2) script.push('Priced at ' + price2);
            if (beds || sqft) {
                var details = [];
                if (beds) details.push(beds);
                if (sqft) details.push(sqft);
                script.push('Featuring ' + details.join(' with '));
            }
            script.push("Don't miss this incredible opportunity. Call today to schedule your private showing.");
            var scriptText = script.join('. ');
            var scriptEl = document.getElementById('voice-script');
            if (scriptEl) scriptEl.value = scriptText;
            if (address) address.textContent = address2;
            if (price) price.textContent = price2;
            setStatus('✅ Voiceover script generated! Edit if needed, then record.', 'info');
        }).catch(function(e) {
            setStatus('⚠️ Error: ' + e.message, 'err');
        });
    }

    // ── Fetch listing (URL scan)
    function fetchListing() {
        var urlInput = document.getElementById('listing-url');
        var url = urlInput ? urlInput.value.trim() : '';
        if (!url) return Promise.reject(new Error('No URL'));
        return fetch(url, { mode: 'cors' })
            .then(function(r) { return r.text(); })
            .then(function(html) {
                var data = parseListingData(html, url);
                // Auto-fill form fields
                if (data.address) {
                    var a = document.getElementById('address-display');
                    if (a) a.textContent = data.address;
                }
                if (data.price) {
                    var p = document.getElementById('price-display');
                    if (p) p.textContent = data.price;
                }
                return data;
            });
    }

    // ── Parse listing HTML for property data + images
    function parseListingData(html, baseUrl) {
        var data = { images: [], address: '', price: '', beds: '', sqft: '' };
        try {
            // JSON-LD
            var jsonld = html.match(/<script[^>]+type=["\']application\/ld\+json["\'][^>]*>([\s\S]*?)<\/script>/gi) || [];
            for (var i = 0; i < jsonld.length; i++) {
                try {
                    var obj = JSON.parse(jsonld[i].replace(/<[^>]+>/g, ''));
                    if (obj.address) {
                        data.address = obj.address.streetAddress || '';
                        if (obj.address.addressLocality) data.address += ', ' + obj.address.addressLocality;
                        if (obj.address.addressRegion) data.address += ', ' + obj.address.addressRegion;
                        if (obj.address.postalCode) data.address += ' ' + obj.address.postalCode;
                        data.address = data.address.trim();
                    }
                    if (obj.price) data.price = obj.price;
                    if (obj.numberOfBedrooms) data.beds = obj.numberOfBedrooms + ' bed';
                    if (obj.floorSize) data.sqft = obj.floorSize.replace(/[^0-9,]/g, '') + ' sq ft';
                    if (obj.image) {
                        if (Array.isArray(obj.image)) data.images = obj.image.slice(0, 15);
                        else data.images = [obj.image];
                    }
                } catch(e) {}
            }
        } catch(e) {}

        // Meta tags
        if (!data.address) {
            var titleMatch = html.match(/<title>([^<]+)<\/title>/i);
            if (titleMatch) {
                var title = titleMatch[1].replace(/\s*\|\s*/g, ' ').trim();
                var parts = title.split(' ');
                var cityIdx = -1;
                for (var j = 0; j < parts.length; j++) {
                    if (parts[j].length === 2 && parts[j] === parts[j].toUpperCase()) { cityIdx = j; break; }
                }
                if (cityIdx > 0) data.address = parts.slice(0, cityIdx).join(' ');
            }
        }

        // Parse images
        return parseAndShowImages(html, baseUrl, data);
    }

    // ── Extract + display images from HTML
    
    function parseAndShowImages(html, baseUrl, data) {
        data = data || {};
        data.images = data.images || [];
        var urls = [];
        var seen = {};

        // ── 1. JSON-LD ─────────────────────────────────────────────────
        var jsonldMatches = html.match(/<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi) || [];
        for (var ji = 0; ji < jsonldMatches.length; ji++) {
            try {
                var raw = jsonldMatches[ji].replace(/<[^>]+>/g, '');
                var objs = JSON.parse(raw);
                if (!Array.isArray(objs)) objs = [objs];
                for (var oi = 0; oi < objs.length; oi++) {
                    var obj = objs[oi];
                    // Direct image field
                    var imgField = obj.image || obj.photo || obj.photos;
                    if (typeof imgField === 'string' && imgField) {
                        if (!seen[imgField] && imgField.match(/\.(jpg|jpeg|png|webp)/i)) { seen[imgField] = true; urls.push(imgField); }
                    } else if (Array.isArray(imgField)) {
                        for (var ii = 0; ii < imgField.length; ii++) {
                            var u = typeof imgField[ii] === 'string' ? imgField[ii] : imgField[ii].url;
                            if (u && !seen[u] && u.match(/\.(jpg|jpeg|png|webp)/i)) { seen[u] = true; urls.push(u); }
                        }
                    } else if (obj['@type'] === 'ImageObject' && obj.url) {
                        if (!seen[obj.url]) { seen[obj.url] = true; urls.push(obj.url); }
                    }
                }
            } catch(e) {}
        }

        // ── 2. __NEXT_DATA__ (Corcoran, Zillow, Realtor) ──────────────
        var nextDataMatch = html.match(/<script[^>]+id=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script>/i);
        if (nextDataMatch) {
            try {
                var nd = JSON.parse(nextDataMatch[1]);
                var listing = nd.props && nd.props.pageProps && nd.props.pageProps.listing
                    ? nd.props.pageProps.listing
                    : nd.props && nd.props.pageProps && nd.props.pageProps.initialReduxState
                    ? JSON.stringify(nd.props.pageProps.initialReduxState)
                    : '';

                // Walk the object for image URLs
                var imgList = [];
                function walk(o) {
                    if (!o || typeof o !== 'object') return;
                    if (Array.isArray(o)) { for (var i = 0; i < o.length; i++) walk(o[i]); return; }
                    // Look for URL fields that look like image URLs
                    for (var k in o) {
                        var v = o[k];
                        if (k === 'url' && typeof v === 'string' && v.match(/\.(jpg|jpeg|png|webp)/i) && !seen[v]) {
                            seen[v] = true; urls.push(v);
                        } else if (k === 'media' && Array.isArray(v)) {
                            for (var m = 0; m < v.length; m++) {
                                var u2 = typeof v[m] === 'string' ? v[m] : v[m].url;
                                if (u2 && !seen[u2] && u2.match(/\.(jpg|jpeg|png|webp)/i)) { seen[u2] = true; urls.push(u2); }
                            }
                        } else if (typeof v === 'object') {
                            walk(v);
                        }
                    }
                }
                if (typeof listing === 'string') {
                    try { walk(JSON.parse(listing)); } catch(e) {}
                } else { walk(listing); }
            } catch(e) {}
        }

        // ── 3. OG:image meta ───────────────────────────────────────────
        var ogMatches = html.match(/<meta[^>]+property=["']og:image["'][^>]+content=["']([^"']+)["'][^>]*/gi) || [];
        for (var gi = 0; gi < ogMatches.length; gi++) {
            var m = ogMatches[gi].match(/content=["']([^"']+)["'/]/);
            if (m && m[1] && !seen[m[1]]) { seen[m[1]] = true; urls.push(m[1]); }
        }

        // ── 4. CloudFront base64-encoded URLs ─────────────────────────
        var cdnMatches = html.match(/https?:\/\/[a-z0-9.\-]*cloudfront\.net[^"'\s>)]+/g) || [];
        for (var ci = 0; ci < cdnMatches.length; ci++) {
            var cdnUrl = cdnMatches[ci];
            // Pattern: /f:webp/rt:fit/w:XXX/BASE64
            var b64M = cdnUrl.match(/\/f:webp\/rt:fit\/w:\d+\/([A-Za-z0-9_=\-]+)/);
            if (b64M) {
                try {
                    var b64 = b64M[1].replace(/_/g, '/').replace(/-/g, '+');
                    while (b64.length % 4) b64 += '=';
                    var decoded = atob(b64);
                    if (decoded && decoded.match(/listingphotos|listing_?images|property_?photos|photos\./i) && !seen[decoded]) {
                        seen[decoded] = true; urls.push(decoded);
                    }
                } catch(e) {}
            }
            // Also push CDN URLs directly if they look like photo URLs
            if (cdnUrl.match(/listingphotos|property_?photos|images\.|photos\./i) && !seen[cdnUrl]) {
                seen[cdnUrl] = true; urls.push(cdnUrl);
            }
        }

        // ── 7. data-src and src from img tags ─────────────────────────
                var bgMatches = html.match(/background-image\s*:\s*url\(([^)]+)\)/gi) || [];
        for (var bi = 0; bi < bgMatches.length; bi++) {
            var m2 = bgMatches[bi].match(/url\(([^)]+)\)/i);
            if (m2 && m2[1]) {
                var u2 = m2[1].replace(/^["']|["']$/g, '');
                if (!seen[u2] && u2.match(/^https?:/) && !u2.match(/logo|icon|avatar/i)) {
                    seen[u2] = true; urls.push(u2);
                }
            }
        }


        var bgMatches = html.match(/background-image\s*:\s*url\(([^)]+)\)/gi) || [];
        for (var bi = 0; bi < bgMatches.length; bi++) {
            var m2 = bgMatches[bi].match(/url\(([^)]+)\)/i);
            if (m2 && m2[1]) {
                var u2 = m2[1].replace(/^["']|["']$/g, '');
                if (!seen[u2] && u2.match(/^https?:/) && !u2.match(/logo|icon|avatar/i)) {
                    seen[u2] = true; urls.push(u2);
                }
            }
        }


        var bgMatches = html.match(/background-image\s*:\s*url\(([^)]+)\)/gi) || [];
        for (var bi = 0; bi < bgMatches.length; bi++) {
            var m2 = bgMatches[bi].match(/url\(([^)]+)\)/i);
            if (m2 && m2[1]) {
                var u2 = m2[1].replace(/^["']|["']$/g, '');
                if (!seen[u2] && u2.match(/^https?:/) && !u2.match(/logo|icon|avatar/i)) {
                    seen[u2] = true; urls.push(u2);
                }
            }
        }


        var bgMatches = html.match(/background-image\s*:\s*url\(([^)]+)\)/gi) || [];
        for (var bi = 0; bi < bgMatches.length; bi++) {
            var m2 = bgMatches[bi].match(/url\(([^)]+)\)/i);
            if (m2 && m2[1]) {
                var u2 = m2[1].replace(/^['"]|['"]$/g, '');
                if (!seen[u2] && u2.match(/^https?:/) && !u2.match(/logo|icon|avatar/i)) {
                    seen[u2] = true; urls.push(u2);
                }
            }
        }


        var bgMatches = html.match(/background-image\s*:\s*url\(([^)]+)\)/gi) || [];
        for (var bi = 0; bi < bgMatches.length; bi++) {
            var m2 = bgMatches[bi].match(/url\(([^)]+)\)/i);
            if (m2 && m2[1]) {
                var u2 = m2[1].replace(/^['"]|['"]$/g, '');
                if (!seen[u2] && u2.match(/^https?:/) && !u2.match(/logo|icon|avatar/i)) {
                    seen[u2] = true; urls.push(u2);
                }
            }
        }

var allImgTags = html.match(/<img[^>]+>/gi) || [];
        for (var im = 0; im < allImgTags.length; im++) {
            var tag = allImgTags[im];
            var srcM = tag.match(/data-src=["']([^"']+)["'/]/) || tag.match(/src=["']([^"']+)["'/]/);
            if (srcM && srcM[1]) {
                var u = srcM[1];
                if (!seen[u] && u.match(/\.(jpg|jpeg|png|webp)/i) &&
                    !u.match(/logo|icon|avatar|banner|nav|header|footer|background|sprite|spacer/i)) {
                    seen[u] = true; urls.push(u);
                }
            }
        }

        // ── 6. data-src from source tags ──────────────────────────────
        var sourceTags = html.match(/<source[^>]+>/gi) || [];
        for (var st = 0; st < sourceTags.length; st++) {
            var srcM = sourceTags[st].match(/src=["']([^"']+)["'/]/);
            if (srcM && srcM[1] && !seen[srcM[1]] && srcM[1].match(/\.(jpg|jpeg|png|webp)/i)) {
                seen[srcM[1]] = true; urls.push(srcM[1]);
            }
        }

        // ── 7. Unsplash/media thumbnails ────────────────────────────────
        var thumbMatches = html.match(/https?:\/\/[a-z0-9.\-]*\.(?:unsplash|media\.licdn|tam\.pm)\.com[^"'\s>)]+/g) || [];
        for (var ti = 0; ti < thumbMatches.length; ti++) {
            var u = thumbMatches[ti];
            if (!seen[u] && u.match(/listingphotos|property|home|house|real.estate|photo/i)) {
                seen[u] = true; urls.push(u);
            }
        }

        // ── img tag src and data-src ───────────────────────────────
        var imgTagMatches = html.match(/<img[^>]+>/gi) || [];
        for (var it = 0; it < imgTagMatches.length; it++) {
            var tag = imgTagMatches[it];
            var srcM = tag.match(/data-src=["']([^"']+)["']/) || tag.match(/src=["']([^"']+)["']/);
            if (srcM && srcM[1]) {
                var u = srcM[1];
                if (!seen[u] && u.match(/\.(jpg|jpeg|png|webp)/i) && !u.match(/logo|icon|avatar|banner|nav/i)) {
                    seen[u] = true; urls.push(u);
                }
            }
        }

        // ── Deduplicate and limit ─────────────────────────────────────
        urls = urls.filter(function(u) { return u && u.length < 2000; });
        // Remove obvious duplicates by normalizing
        var normalized = {};
        var unique = [];
        for (var ui = 0; ui < urls.length; ui++) {
            var norm = urls[ui].split('?')[0].replace(/\/$/, '');
            if (!normalized[norm]) {
                normalized[norm] = true;
                unique.push(urls[ui]);
            }
        }

        if (unique.length > 0) showImageGrid(unique);
        return data;
    }


    // ── Scan modal
    function openScanModal() {
        var m = document.getElementById('scan-modal');
        if (m) { m.style.display = 'block'; m.classList.add('open'); _modalSel = {}; }
    }

    function closeScanModal() {
        var m = document.getElementById('scan-modal');
        if (m) m.style.display = 'none'; m.classList.remove('open');
    }

    function switchTab(tab) {
        var tabs = ['url', 'paste'];
        tabs.forEach(function(t) {
            var el = document.getElementById('tab-' + t);
            if (el) el.style.display = t === tab ? 'block' : 'none';
            var btn = document.getElementById('tab-btn-' + t);
            if (btn) btn.classList.toggle('sel', t === tab);
        });
    }

    // ── Paste HTML
    function extractFromHtml() {
        var ta = document.getElementById('paste-area');
        if (!ta || !ta.value.trim()) {
            setStatus('⚠️ Paste the listing page HTML first (View Source, Ctrl+A, Ctrl+C).', 'err');
            return;
        }
        var urlInput = document.getElementById('listing-url');
        var baseUrl = urlInput ? urlInput.value.trim() : '';
        if (!baseUrl) {
            var urlMatch = ta.value.match(/<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)["']/i);
            if (!urlMatch) urlMatch = ta.value.match(/<meta[^>]+property=["']og:url["'][^>]+content=["']([^"']+)["']/i);
            if (urlMatch) { baseUrl = urlMatch[1]; if (urlInput) urlInput.value = baseUrl; }
        }
        // Try to extract URL from pasted HTML
        if (!baseUrl) {
            var urlMatch = ta.value.match(/<link[^>]+rel=["']canonical["'][^>]+href=["']([^"']+)["']/i);
            if (!urlMatch) urlMatch = ta.value.match(/<meta[^>]+property=["']og:url["'][^>]+content=["']([^"']+)["']/i);
            if (urlMatch) { baseUrl = urlMatch[1]; if (urlInput) urlInput.value = baseUrl; }
        }
        var data = parseListingData(ta.value, baseUrl);
        if (data.images.length === 0) {
            setStatus('⚠️ No images found. Try a different listing URL or paste different HTML.', 'err');
        } else {
            setStatus('✅ Found ' + data.images.length + ' images! Review and confirm.', 'info');
        }
    }

    function addManualUrls() {
        var ta = document.getElementById('manual-urls');
        if (!ta || !ta.value.trim()) return;
        var lines = ta.value.trim().split('\n');
        var valid = [];
        lines.forEach(function(line) {
            var url = line.trim();
            if (url.match(/\.(jpg|jpeg|png|webp)/i)) valid.push(url);
        });
        if (valid.length > 0) showImageGrid(valid);
    }

    // ── Image grid (modal)
    var _imgBatch = [];
    var _imgOffset = 0;
    var _imgBatchSize = 30;

    function showImageGrid(urls) {
        _imgBatch = urls;
        _imgOffset = 0;
        var grid = document.getElementById('img-grid');
        if (grid) grid.innerHTML = '';
        renderBatch();
    }

    function renderBatch() {
        var grid = document.getElementById('img-grid');
        if (!grid) return;
        var end = Math.min(_imgOffset + _imgBatchSize, _imgBatch.length);
        for (var i = _imgOffset; i < end; i++) {
            var url = _imgBatch[i];
            var div = document.createElement('div');
            div.className = 'img-thumb' + (_modalSel[url] ? ' sel' : '');
            div.style.cssText = 'position:relative;cursor:pointer;padding:4px;';
            var img = document.createElement('img');
            img.src = url;
            img.style.cssText = 'width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:6px;opacity:0.8;';
            img.onerror = function() { this.style.opacity = '0.3'; };
            var num = i + 1;
            img.onload = function(n, el) {
                return function() {
                    el.style.opacity = '1';
                    var badge = document.createElement('span');
                    badge.style.cssText = 'position:absolute;top:8px;right:8px;background:rgba(0,0,0,0.6);color:#fff;border-radius:50%;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:12px;';
                    badge.textContent = n;
                    el.parentElement.appendChild(badge);
                };
            }(num, img);
            div.appendChild(img);
            div.onclick = (function(u) {
                return function() { toggleThumb(this, u); };
            })(url);
            grid.appendChild(div);
        }
        _imgOffset = end;
        if (_imgOffset < _imgBatch.length) {
            var more = document.getElementById('load-more');
            if (!more) {
                more = document.createElement('div');
                more.id = 'load-more';
                more.style.cssText = 'text-align:center;padding:12px;color:#666;cursor:pointer;';
                more.textContent = 'Load more...';
                more.onclick = renderBatch;
                grid.parentElement.appendChild(more);
            }
        } else {
            var more = document.getElementById('load-more');
            if (more) more.remove();
        }
        updateConfirmBtn();
    }

    function toggleThumb(el, url) {
        var isSelected = !!_modalSel[url];
        if (isSelected) {
            delete _modalSel[url];
            el.classList.remove('sel');
        } else {
            var count = Object.keys(_modalSel).length;
            if (count >= MAX_IMAGES) {
                setStatus('⚠️ Maximum ' + MAX_IMAGES + ' images allowed.', 'err');
                return;
            }
            _modalSel[url] = true;
            el.classList.add('sel');
        }
        updateConfirmBtn();
    }

    function selectAllModalImages() {
        _modalSel = {};
        var count = 0;
        _imgBatch.forEach(function(url) {
            if (count < MAX_IMAGES) {
                _modalSel[url] = true;
                count++;
            }
        });
        document.querySelectorAll('.img-thumb img').forEach(function(img) {
            img.parentElement.classList.add('sel');
        });
        updateConfirmBtn();
    }

    function updateConfirmBtn() {
        var count = Object.keys(_modalSel).length;
        var btn = document.getElementById('modal-confirm-btn');
        var cnt = document.getElementById('sel-confirm-count');
        if (cnt) cnt.textContent = count;
        if (btn) {
            btn.textContent = 'Confirm (' + count + ')';
            btn.disabled = (count === 0);
            btn.style.opacity = count === 0 ? '0.4' : '1';
        }
    }

    // ── Image download + confirm
    function confirmSelection() {
        var urls = Object.keys(_modalSel);
        if (urls.length === 0) return;
        var prog = document.getElementById('modal-progress');
        var btn = document.getElementById('modal-confirm-btn');
        if (btn) { btn.disabled = true; btn.textContent = 'Downloading...'; }
        if (prog) prog.textContent = 'Starting...';

        _uploadedFiles = [];
        var queue = urls.slice();
        var active = 0;
        var done = 0;
        var failed = 0;
        var total = urls.length;

        function startNext() {
            while (active < CONCURRENT && queue.length > 0) {
                var url = queue.shift();
                active++;
                (function(imgUrl, idx) {
                    // CDN / cloud storage: try direct CORS fetch ONLY for hosts known to support it.
                    // Everything else goes through the server-side proxy to avoid CORS errors.
                    var corsSafe = /cloudfront\.net|cloudinary\.com|imgix\.net|photobucket\.com/i.test(imgUrl);
                    var proxy = 'https://vybord.com/api/proxy-img.php?url=' + encodeURIComponent(imgUrl);
                    var fetchPromise;

                    if (corsSafe) {
                        fetchPromise = fetch(imgUrl, { mode: 'cors' }).then(function(r) {
                            if (!r.ok) throw new Error('HTTP ' + r.status);
                            return r.blob();
                        }).then(function(blob) {
                            return new Promise(function(resolve) {
                                var reader = new FileReader();
                                reader.onloadend = function() { resolve(reader.result); };
                                reader.readAsDataURL(blob);
                            });
                        });
                    } else {
                        fetchPromise = fetch(proxy)
                            .then(function(r) {
                                if (!r.ok) throw new Error('Proxy HTTP ' + r.status);
                                return r.json().catch(function() { return null; });
                            })
                            .then(function(data) {
                                if (data && data.data) return 'data:image/' + (data.ext || 'jpg') + ';base64,' + data.data;
                                throw new Error(data && data.error ? data.error : 'Proxy returned no data');
                            });
                    }

                    fetchPromise
                        .then(function(dataUrl) {
                            var extMatch = imgUrl.match(/\.(jpg|jpeg|png|webp)/i);
                            var ext = extMatch ? extMatch[0].replace('.', '').replace('jpeg', 'jpg') : 'jpg';
                            _uploadedFiles.push({
                                name: 'image_' + String(done + 1).padStart(3, '0') + '.' + ext,
                                data: dataUrl
                            });
                        })
                        .catch(function(e) {
                            failed++;
                            _uploadedFiles.push({
                                name: 'image_' + String(done + 1).padStart(3, '0') + '.jpg',
                                data: imgUrl,
                                _isUrl: true
                            });
                        })
                        .finally(function() {
                            done++;
                            active--;
                            if (prog) prog.textContent = 'Downloaded ' + done + '/' + total + (failed > 0 ? ' (' + failed + ' failed)' : '') + '...';
                            if (queue.length > 0 || active > 0) {
                                startNext();
                            } else {
                                closeScanModal();
                                var count = _uploadedFiles.length;
                                document.getElementById('img-count').textContent = count + ' image(s) selected';
                                setStatus(count + ' images ready' + (failed > 0 ? ' (' + failed + ' failed).' : '.'), 'info');
                                if (btn) { btn.disabled = false; btn.textContent = 'Confirm (' + count + ')'; }
                            }
                        });
                })(url, done);
            }
        }

        startNext();
    }

    // ── Property details from URL slug
    function parseAddressFromUrl(url) {
        try {
            var parts = url.split('/');
            var slug = parts[parts.length - 1] || '';
            var segs = slug.split('-');
            var state = '', zip = '', city = '', street = '';
            for (var i = 0; i < segs.length; i++) {
                if (segs[i].match(/^[A-Z]{2}$/) && i < segs.length - 1 && segs[i+1].match(/^\d{5}$/)) {
                    state = segs[i]; zip = segs[i+1];
                    city = segs.slice(Math.max(0, i-3), i).join(' ');
                    street = segs.slice(0, Math.max(0, i-3)).join(' ');
                    break;
                }
            }
            if (city && state) {
                return { address: street, city: city, state: state, zip: zip };
            }
        } catch(e) {}
        return null;
    }

    function fetchPropertyDetails() {
        var urlInput = document.getElementById('listing-url');
        var url = urlInput ? urlInput.value.trim() : '';
        if (!url) { showLookupStatus('⚠️ Enter a listing URL first', 'err'); return; }
        if (!url.startsWith('http')) { showLookupStatus('⚠️ Enter a full URL starting with http', 'err'); return; }
        var btn = document.getElementById('lookup-btn');
        btn.disabled = true; btn.textContent = '⏳…';
        showLookupStatus('Looking up property details…', 'info');

        fetch('https://vybord.com/lookup.php', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url })
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            btn.disabled = false; btn.textContent = '🔍 Lookup';
            if (data.error) {
                showLookupStatus('⚠️ ' + data.error, 'err'); return;
            }
            var a = document.getElementById('address-display');
            if (a && data.address) a.textContent = data.address;
            var p = document.getElementById('price-display');
            if (p && data.price) p.textContent = '$' + data.price;
            var b = document.getElementById('m-beds');
            if (b) b.value = data.beds || '';
            var bt = document.getElementById('m-baths');
            if (bt) bt.value = data.baths || '';
            var sq = document.getElementById('m-sqft');
            if (sq) sq.value = data.sqft || '';
            var ta = document.getElementById('m-script');
            if (ta && data.script) ta.value = data.script;
            var details = [data.address, data.price, data.beds, data.baths].filter(Boolean).join(' · ');
            showLookupStatus('✅ ' + (details || 'Property details loaded'), 'ok');
        })
        .catch(function(e) {
            btn.disabled = false; btn.textContent = '🔍 Lookup';
            showLookupStatus('⚠️ Connection error: ' + e.message, 'err');
        });
    }

    function showLookupStatus(msg, type) {
        var el = document.getElementById('lookup-status');
        if (!msg) { el.style.display = 'none'; return; }
        el.style.display = 'block';
        el.style.color = type === 'err' ? '#ff6666' : type === 'ok' ? '#00ff88' : '#60a5fa';
        el.textContent = msg;
    }

    // ── YouTube music
    function applyMusicUrl() {
        var input = document.getElementById('music-url');
        if (!input) return;
        var url = input.value.trim();
        s.musicUrl = url;
        // Deselect all music presets
        var musicGroup = document.querySelector('.music-group');
        if (musicGroup) musicGroup.querySelectorAll('.opt-btn').forEach(function(b) { b.classList.remove('sel'); });
        if (url) {
            var ytGroup = document.querySelector('.music-group .opt-btn:last-child');
            if (ytGroup) ytGroup.classList.add('sel');
            setStatus('🎵 YouTube music: ' + url, 'info');
        }
    }

    // ── Submit
    function toB64(file) {
        return new Promise(function(resolve, reject) {
            var reader = new FileReader();
            reader.onload = function(e) { resolve(e.target.result); };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    async function handleSubmit(e) {
        e.preventDefault();
        console.log('handleSubmit called', { uploaded: _uploadedFiles.length, files: document.getElementById('image-files').files.length });
        var btn = document.getElementById('gen-btn');
        if (!btn) { console.error('Button not found'); return; }
        btn.disabled = true;
        btn.textContent = '⏳ Sending...';

        var emailInput = document.getElementById('user-email');
        var email = emailInput ? emailInput.value.trim() : '';
        var address = '';
        var addressEl = document.getElementById('address-display');
        if (addressEl) address = addressEl.textContent.trim();
        var price = '';
        var priceEl = document.getElementById('price-display');
        if (priceEl) price = priceEl.textContent.trim();
        var beds = (document.getElementById('m-beds') || {value:''}).value.trim();
        var baths = (document.getElementById('m-baths') || {value:''}).value.trim();
        var sqft = (document.getElementById('m-sqft') || {value:''}).value.trim();
        var script = (document.getElementById('m-script') || {value:''}).value.trim();

        var images = [];
        var fileInput = document.getElementById('image-files');
        // Collect from _uploadedFiles
        _uploadedFiles.forEach(function(item) {
            if (item._isUrl) return;
            var data = item.data;
            if (data.indexOf('data:') === 0) {
                data = data.split(',')[1];
            }
            images.push({ name: item.name, data: data });
        });

        if (images.length === 0) {
            // Try file input
            if (fileInput && fileInput.files.length > 0) {
                for (var i = 0; i < fileInput.files.length; i++) {
                    var file = fileInput.files[i];
                    var b64 = await toB64(file);
                    images.push({ name: file.name, data: b64.split(',')[1] });
                }
            }
        }

        if (images.length === 0) {
            setStatus('⚠️ No images loaded. Click Scan first, then Confirm.', 'err');
            btn.disabled = false; btn.textContent = '🚀 Generate Video'; return;
        }

        setStatus('🚀 Sending to Vybord pipeline... (images: ' + images.length + ')', 'info');

        var payload = {
            settings: {
                voice: s.voice,
                template: s.template,
                fontSize: s.fontSize,
                textColor: s.textColor.replace('#', ''),
                effect: s.effect,
                music: s.music,
                musicUrl: s.musicUrl,
                transition: s.transition,
                ratio: s.ratio,
                duration: s.duration,
                address: address,
                price: price,
                beds: beds,
                baths: baths,
                sqft: sqft,
                script: script
            },
            userEmail: email,
            images: images,
            musicUrl: s.musicUrl
        };

        var controller = new AbortController();
        var timeout = setTimeout(function() { controller.abort(); }, 60000);

        try {
            var res = await fetch('https://vybord.com/api/send.php', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
                signal: controller.signal
            });

            clearTimeout(timeout);
            var text = await res.text();

            // Parse SSE: multiple JSON lines
            var lastData = {};
            var lines = text.split('\n');
            for (var j = 0; j < lines.length; j++) {
                var line = lines[j].trim();
                if (!line) continue;
                try {
                    var parsed = JSON.parse(line);
                    if (parsed.done) break;
                    if (parsed.job_id) lastData.job_id = parsed.job_id;
                    if (parsed.status) lastData.status = parsed.status;
                    if (parsed.message) lastData.message = parsed.message;
                    if (parsed.error) lastData.error = parsed.error;
                } catch(e) {}
            }

            console.log('Response data:', lastData);
            if (lastData.error) {
                setStatus('⚠️ Error: ' + lastData.error, 'err');
            } else if (lastData.job_id) {
                var reviewUrl = lastData.review_url || ('http://95.111.236.104:7073/review/' + lastData.job_id);
                setStatus('Job <a href="' + reviewUrl + '" target="_blank" style="color:#4f9;color-text-decoration:underline">' + lastData.job_id + '</a> created! <a href="' + reviewUrl + '" target="_blank">Click here to review and generate the video.</a>', 'info');
            } else if (lastData.status) {
                setStatus(lastData.status, 'info');
            } else if (lastData.message) {
                setStatus(lastData.message, 'info');
            } else {
                setStatus('Response received. Check the email ' + email + ' for your video link.', 'info');
            }
        } catch(err) {
            clearTimeout(timeout);
            console.error('handleSubmit error:', err);
            if (err.name === 'AbortError') {
                setStatus('⚠️ Request timed out after 60s. Try again.', 'err');
            } else {
                setStatus('⚠️ Network error: ' + err.message, 'err');
            }
        }

        btn.disabled = false;
        btn.textContent = '🚀 Generate Video';
    }

</script>

<!-- Image Scan Modal -->
<style>
.modal-overlay.open{display:block}
.modal-overlay{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:9999;display:none;overflow-y:auto;padding:20px}
.modal-overlay.open{display:block}
.modal-box{background:#1a1a2e;border:1px solid #333;border-radius:16px;max-width:900px;margin:40px auto;padding:28px;color:#e0e0e0}
.modal-box h2{font-size:1.3rem;margin-bottom:16px;color:#fff}
.modal-tabs{display:flex;gap:8px;margin-bottom:16px}
.modal-tabs button{padding:8px 16px;border-radius:8px;border:1px solid #444;background:#2a2a3e;color:#aaa;cursor:pointer;font-size:0.9rem}
.modal-tabs button.sel{background:#8309EE;color:#fff;border-color:#8309EE}
.modal-close{float:right;background:none;border:none;color:#888;font-size:1.5rem;cursor:pointer;padding:0;line-height:1}
.modal-close:hover{color:#fff}
#tab-url,#tab-paste{display:none}
.modal-actions{display:flex;gap:10px;margin:12px 0;flex-wrap:wrap}
.modal-actions button{padding:9px 18px;border-radius:8px;border:1px solid #555;background:#2a2a3e;color:#e0e0e0;cursor:pointer;font-size:0.88rem}
.modal-actions button:hover{background:#3a3a4e}
.modal-actions button.primary{background:#8309EE;border-color:#8309EE;color:#fff}
.modal-actions button.primary:hover{background:#6b07c7}
#modal-progress{color:#aaa;font-size:0.85rem;margin:8px 0;min-height:20px}
#img-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;max-height:420px;overflow-y:auto;margin-top:12px}
#img-grid .img-thumb.sel{outline:3px solid #8309EE;border-radius:8px}
.img-thumb{position:relative;cursor:pointer}
.img-thumb img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:6px}
</style>
<div id="scan-modal" class="modal-overlay">
<div class="modal-box">
<button class="modal-close" onclick="closeScanModal()">&#215;</button>
<h2>Select Listing Images</h2>
<div class="modal-tabs">
<button id="tab-btn-url" class="sel" onclick="switchTab('url')">Scan URL</button>
<button id="tab-btn-paste" onclick="switchTab('paste')">Paste HTML</button>
</div>
<div id="tab-url">
<div class="modal-actions">
<button class="primary" onclick="fetchPropertyDetails()">&#128269; Fetch from URL</button>
<button onclick="openScanModal()">&#128247; Open Image Selector</button>
</div>
<p style="color:#888;font-size:0.82rem;margin:4px 0 12px">Fetches images automatically. Opens selector to confirm/trim selection.</p>
</div>
<div id="tab-paste">
<div class="modal-actions">
<button class="primary" onclick="extractFromHtml()" style="width:100%;padding:12px;font-size:1rem;font-weight:bold">&#128269; Parse HTML &amp; Extract Images</button>
<button onclick="addManualUrls()">Add Image URLs</button>
</div>
<p style="color:#aaa;font-size:0.82rem;margin-bottom:8px">Open the listing page, press <b>Ctrl+U</b> (View Source), then <b>Ctrl+A</b> → <b>Ctrl+C</b> to copy everything, then paste below.</p>
<textarea id="paste-area" rows="8" style="width:100%;background:#111;border:1px solid #444;color:#ccc;border-radius:8px;padding:10px;font-size:0.82rem;font-family:monospace" placeholder="Ctrl+U, Ctrl+A, Ctrl+V to paste page source here..."></textarea>
<textarea id="manual-urls" rows="3" style="width:100%;background:#111;border:1px solid #333;color:#ccc;border-radius:8px;padding:8px;font-size:0.83rem;margin-top:8px" placeholder="Or paste image URLs (one per line)"></textarea>
</div>
<div id="modal-progress"></div>
<div id="img-grid"></div>
<div class="modal-actions" style="margin-top:12px">
<button onclick="selectAllModalImages()">Select All</button>
<button class="primary" id="modal-confirm-btn" onclick="confirmSelection()" disabled style="opacity:0.4">Confirm (<span id="sel-confirm-count">0</span>)</button>
</div>
</div>
</div>

</body>
</html>
