/**
 * Scanner JavaScript - DCS Day '26 Event Ticket Scanner
 * Modular JavaScript for QR code scanning and verification
 */

// ===== Global State =====
const ScannerState = {
    video: null,
    canvas: null,
    context: null,
    stream: null,
    scanning: false,
    deviceRegistered: false,
    deviceInfo: null,
    detection: {
        lastDetected: null,
        consecutiveDetections: 0,
        processingQR: false,
        requiredDetections: 2,
        lastProcessTime: 0
    }
};

// ===== DOM Elements =====
const DOM = {
    // Will be populated on init
    video: null,
    startBtn: null,
    stopBtn: null,
    captureBtn: null,
    statusBadge: null,
    statusText: null,
    resultSection: null,
    resultContent: null,
    verificationModal: null,
    registrationModal: null,
    verificationCode: null,
    codeEmail: null,
    manualData: null,
    manualEmail: null
};

// ===== Initialization =====
document.addEventListener('DOMContentLoaded', initializeScanner);

function initializeScanner() {
    // Cache DOM elements
    DOM.video = document.getElementById('video');
    DOM.startBtn = document.getElementById('startBtn');
    DOM.stopBtn = document.getElementById('stopBtn');
    DOM.captureBtn = document.getElementById('captureBtn');
    DOM.statusBadge = document.getElementById('statusBadge');
    DOM.statusText = document.getElementById('statusText');
    DOM.resultSection = document.getElementById('resultSection');
    DOM.resultContent = document.getElementById('resultContent');
    DOM.verificationModal = document.getElementById('verificationModal');
    DOM.registrationModal = document.getElementById('registrationModal');
    DOM.verificationCode = document.getElementById('verificationCode');
    DOM.codeEmail = document.getElementById('codeEmail');
    DOM.manualData = document.getElementById('manualData');
    DOM.manualEmail = document.getElementById('manualEmail');

    // Set initial state
    ScannerState.video = DOM.video;

    // Setup event listeners
    setupEventListeners();

    // Check camera support
    checkCameraSupport();

    // Show registration prompt on mobile
    setTimeout(showDeviceRegistration, 1500);
}

function setupEventListeners() {
    // Keyboard shortcuts
    document.addEventListener('keydown', handleKeyboardShortcuts);

    // Verification code input formatting
    if (DOM.verificationCode) {
        DOM.verificationCode.addEventListener('input', handleCodeInput);
    }

    // Auto-submit on email completion
    if (DOM.codeEmail) {
        DOM.codeEmail.addEventListener('input', handleEmailAutoSubmit);
    }

    // Touch events for long-press capture
    if (DOM.video) {
        let touchStartTime = 0;
        
        DOM.video.addEventListener('touchstart', () => {
            touchStartTime = Date.now();
        });
        
        DOM.video.addEventListener('touchend', (e) => {
            if (Date.now() - touchStartTime > 500 && !DOM.captureBtn?.disabled) {
                e.preventDefault();
                captureAndScan();
            }
        });
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', stopScanner);
}

function handleKeyboardShortcuts(event) {
    // Spacebar for capture
    if (event.code === 'Space' && !DOM.captureBtn?.disabled) {
        event.preventDefault();
        captureAndScan();
    }

    // Enter for form submission
    if (event.code === 'Enter') {
        if (document.activeElement === DOM.verificationCode || 
            document.activeElement === DOM.codeEmail) {
            event.preventDefault();
            verifyByCodeManual();
        } else if (document.activeElement === DOM.manualData || 
                   document.activeElement === DOM.manualEmail) {
            event.preventDefault();
            verifyManual();
        }
    }

    // Escape to close modals
    if (event.code === 'Escape') {
        closeAllModals();
    }
}

function handleCodeInput(event) {
    let value = event.target.value.replace(/\D/g, '').slice(0, 6);
    event.target.value = value;
    
    if (value.length === 6) {
        setTimeout(() => DOM.codeEmail?.focus(), 100);
    }
}

function handleEmailAutoSubmit(event) {
    const code = DOM.verificationCode?.value;
    const email = event.target.value.trim();
    
    if (code?.length === 6 && email.includes('@') && email.includes('.')) {
        setTimeout(() => {
            if (DOM.verificationCode.value === code && DOM.codeEmail.value.trim() === email) {
                verifyByCodeManual();
            }
        }, 500);
    }
}

// ===== Camera Support =====
function checkCameraSupport() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        updateStatus('Camera not supported', 'error');
        if (DOM.startBtn) DOM.startBtn.disabled = true;
        
        const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
        const message = isMobile 
            ? 'Camera not supported in this browser. Try Chrome or Safari.'
            : 'Camera not supported on this device.';
        
        showResult(`❌ ${message} Use the manual verification option.`, 'error');
        return false;
    }
    return true;
}

// ===== Status Updates =====
function updateStatus(text, type = 'idle') {
    if (DOM.statusBadge) {
        DOM.statusBadge.className = `status-badge ${type}`;
    }
    if (DOM.statusText) {
        DOM.statusText.textContent = text;
    }
}

// ===== Result Display =====
function showResult(content, type = 'info') {
    if (!DOM.resultSection || !DOM.resultContent) return;
    
    DOM.resultSection.className = `result-section visible ${type}`;
    DOM.resultContent.innerHTML = content;
    
    // Auto-hide after 10 seconds for non-info messages
    if (type !== 'info') {
        setTimeout(() => {
            DOM.resultSection.classList.remove('visible');
        }, 10000);
    }
}

function hideResult() {
    if (DOM.resultSection) {
        DOM.resultSection.classList.remove('visible');
    }
}

// ===== Camera Device Management =====
let availableCameras = [];
let currentCameraIndex = 0;

async function enumerateCameras() {
    try {
        // Need to get initial permission first
        const tempStream = await navigator.mediaDevices.getUserMedia({ video: true });
        tempStream.getTracks().forEach(track => track.stop());
        
        const devices = await navigator.mediaDevices.enumerateDevices();
        availableCameras = devices.filter(device => device.kind === 'videoinput');
        
        console.log('📷 Available cameras:', availableCameras.map(c => ({
            label: c.label || 'Unnamed Camera',
            id: c.deviceId.slice(0, 8) + '...'
        })));
        
        return availableCameras;
    } catch (error) {
        console.error('Failed to enumerate cameras:', error);
        return [];
    }
}

function showCameraSelector() {
    if (availableCameras.length <= 1) {
        showResult('📷 Only one camera available on this device.', 'info');
        return;
    }
    
    let selectorHTML = `
        <div style="text-align: center;">
            <h3>📷 Select Camera</h3>
            <p style="margin: 12px 0; color: var(--text-muted);">Choose which camera to use:</p>
            <div style="display: flex; flex-direction: column; gap: 10px; max-width: 400px; margin: 0 auto;">
    `;
    
    availableCameras.forEach((camera, index) => {
        const isActive = index === currentCameraIndex;
        const label = camera.label || `Camera ${index + 1}`;
        const isBack = label.toLowerCase().includes('back') || label.toLowerCase().includes('environment');
        const icon = isBack ? '📸' : '🤳';
        
        selectorHTML += `
            <button class="btn ${isActive ? 'btn-primary' : 'btn-secondary'}" 
                    onclick="switchToCamera(${index})"
                    style="text-align: left; padding: 12px 16px;">
                ${icon} ${label} ${isActive ? '✓' : ''}
            </button>
        `;
    });
    
    selectorHTML += `
            </div>
            <button class="btn btn-secondary" onclick="hideResult()" style="margin-top: 16px;">Cancel</button>
        </div>
    `;
    
    showResult(selectorHTML, 'info');
}

async function switchToCamera(index) {
    if (index >= availableCameras.length) return;
    
    currentCameraIndex = index;
    stopScanner();
    hideResult();
    
    await new Promise(resolve => setTimeout(resolve, 300));
    
    try {
        const camera = availableCameras[index];
        const constraints = {
            video: {
                deviceId: { exact: camera.deviceId },
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        };
        
        await initializeCameraWithConstraints(constraints);
        showResult(`✅ Switched to: ${camera.label || 'Camera ' + (index + 1)}`, 'success');
        
    } catch (error) {
        console.error('Failed to switch camera:', error);
        showResult('❌ Failed to switch camera. Trying default...', 'error');
        await startScanner();
    }
}

// ===== Scanner Controls =====
async function startScanner() {
    if (!checkCameraSupport()) return;
    
    updateStatus('Initializing camera...', 'scanning');
    
    try {
        // First enumerate available cameras
        if (availableCameras.length === 0) {
            await enumerateCameras();
        }
        
        await initializeCamera();
    } catch (error) {
        console.error('Camera initialization failed:', error);
        handleCameraError(error);
    }
}

async function initializeCamera() {
    // Multiple constraint options to try in order
    const constraintOptions = [
        // Option 1: Back camera with exact facingMode
        {
            video: {
                facingMode: { exact: 'environment' },
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        },
        // Option 2: Back camera with ideal facingMode (more flexible)
        {
            video: {
                facingMode: { ideal: 'environment' },
                width: { min: 640, ideal: 1280, max: 1920 },
                height: { min: 480, ideal: 720, max: 1080 }
            }
        },
        // Option 3: Front camera
        {
            video: {
                facingMode: { ideal: 'user' },
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        },
        // Option 4: Any camera with resolution constraints
        {
            video: {
                width: { ideal: 1280 },
                height: { ideal: 720 }
            }
        },
        // Option 5: Most basic - any video
        { video: true }
    ];
    
    let lastError = null;
    
    for (let i = 0; i < constraintOptions.length; i++) {
        try {
            updateStatus(`Trying camera option ${i + 1}/${constraintOptions.length}...`, 'scanning');
            console.log(`📷 Trying constraint option ${i + 1}:`, constraintOptions[i]);
            
            await initializeCameraWithConstraints(constraintOptions[i]);
            
            // Success - show camera info
            const track = ScannerState.stream.getVideoTracks()[0];
            const settings = track.getSettings();
            console.log('✅ Camera initialized:', {
                label: track.label,
                width: settings.width,
                height: settings.height,
                facingMode: settings.facingMode
            });
            
            showResult(`
                <div style="text-align: center;">
                    <div style="font-size: 2rem; margin-bottom: 8px;">✅</div>
                    <h3 style="color: var(--success);">Camera Ready!</h3>
                    <p style="color: var(--text-muted); font-size: 0.9rem; margin: 8px 0;">
                        ${track.label || 'Camera'}<br>
                        ${settings.width}x${settings.height} @ ${Math.round(settings.frameRate || 30)}fps
                    </p>
                    ${availableCameras.length > 1 ? `
                        <button class="btn btn-secondary btn-sm" onclick="showCameraSelector()" style="margin-top: 8px;">
                            🔄 Switch Camera (${availableCameras.length} available)
                        </button>
                    ` : ''}
                </div>
            `, 'success');
            
            return; // Success, exit function
            
        } catch (error) {
            console.log(`❌ Constraint option ${i + 1} failed:`, error.message);
            lastError = error;
            
            // Stop any partial stream
            if (ScannerState.stream) {
                ScannerState.stream.getTracks().forEach(track => track.stop());
                ScannerState.stream = null;
            }
        }
    }
    
    // All options failed
    throw lastError || new Error('All camera access attempts failed');
}

async function initializeCameraWithConstraints(constraints) {
    ScannerState.stream = await navigator.mediaDevices.getUserMedia(constraints);
    
    if (DOM.video) {
        DOM.video.srcObject = ScannerState.stream;
        DOM.video.setAttribute('playsinline', 'true');
        DOM.video.setAttribute('autoplay', 'true');
        DOM.video.setAttribute('muted', 'true');
        
        return new Promise((resolve, reject) => {
            const timeout = setTimeout(() => {
                reject(new Error('Camera video timeout'));
            }, 10000);
            
            DOM.video.onloadedmetadata = () => {
                clearTimeout(timeout);
                DOM.video.play()
                    .then(() => {
                        startActualScanning();
                        resolve();
                    })
                    .catch(reject);
            };
            
            DOM.video.onerror = () => {
                clearTimeout(timeout);
                reject(new Error('Video element error'));
            };
        });
    } else {
        throw new Error('Video element not found');
    }
}

function startActualScanning() {
    ScannerState.canvas = document.createElement('canvas');
    ScannerState.context = ScannerState.canvas.getContext('2d');
    ScannerState.scanning = true;
    
    resetDetectionState();
    
    // Hide camera placeholder to show video feed
    const placeholder = document.getElementById('cameraPlaceholder');
    if (placeholder) {
        placeholder.style.display = 'none';
    }
    
    if (DOM.startBtn) DOM.startBtn.disabled = true;
    if (DOM.stopBtn) DOM.stopBtn.disabled = false;
    if (DOM.captureBtn) DOM.captureBtn.disabled = false;
    
    updateStatus('Scanning for QR codes...', 'scanning');
    requestAnimationFrame(scanQRCode);
}

function stopScanner() {
    ScannerState.scanning = false;
    resetDetectionState();
    
    if (ScannerState.stream) {
        ScannerState.stream.getTracks().forEach(track => track.stop());
        ScannerState.stream = null;
    }
    
    if (DOM.video) {
        DOM.video.srcObject = null;
    }
    
    // Show camera placeholder again
    const placeholder = document.getElementById('cameraPlaceholder');
    if (placeholder) {
        placeholder.style.display = 'flex';
    }
    
    if (DOM.startBtn) DOM.startBtn.disabled = false;
    if (DOM.stopBtn) DOM.stopBtn.disabled = true;
    if (DOM.captureBtn) DOM.captureBtn.disabled = true;
    
    updateStatus('Scanner stopped', 'idle');
    hideResult();
}

function resetDetectionState() {
    ScannerState.detection = {
        lastDetected: null,
        consecutiveDetections: 0,
        processingQR: false,
        requiredDetections: 2,
        lastProcessTime: 0
    };
}

// ===== QR Code Scanning =====
function scanQRCode() {
    if (!ScannerState.scanning || !DOM.video || ScannerState.detection.processingQR) return;
    
    try {
        const video = DOM.video;
        
        if (video.readyState >= video.HAVE_CURRENT_DATA && video.videoWidth > 0) {
            const canvas = ScannerState.canvas;
            const context = ScannerState.context;
            
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            context.drawImage(video, 0, 0, canvas.width, canvas.height);
            
            const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
            const code = jsQR(imageData.data, imageData.width, imageData.height, {
                inversionAttempts: 'attemptBoth'
            });
            
            if (code && code.data) {
                handleQRDetection(code.data);
            }
        }
    } catch (error) {
        console.error('Scan error:', error);
    }
    
    if (ScannerState.scanning && !ScannerState.detection.processingQR) {
        requestAnimationFrame(scanQRCode);
    }
}

function handleQRDetection(qrData) {
    const detection = ScannerState.detection;
    
    if (detection.lastDetected === qrData) {
        detection.consecutiveDetections++;
    } else {
        detection.lastDetected = qrData;
        detection.consecutiveDetections = 1;
    }
    
    if (detection.consecutiveDetections >= detection.requiredDetections) {
        console.log('✅ QR confirmed:', qrData);
        updateStatus('QR Code detected - Processing...', 'success');
        detection.processingQR = true;
        processConfirmedQR(qrData);
    } else {
        updateStatus(`Detecting (${detection.consecutiveDetections}/${detection.requiredDetections})...`, 'scanning');
    }
}

function processConfirmedQR(qrData) {
    console.log('Processing QR:', qrData);
    resetDetectionState();
    ScannerState.detection.processingQR = true;
    
    // Try to parse as JSON
    try {
        const parsed = JSON.parse(qrData);
        
        // New compact format: {"v": "verification_code", "e": "email", "t": "type"}
        if (parsed.v && parsed.e) {
            console.log('Detected new compact QR format with type:', parsed.t || 'registration');
            verifyByCode(parsed.v, parsed.e, parsed.t || 'registration');
            return;
        }
        
        // Legacy format: {"email": ..., "data": ...}
        if (parsed.email && parsed.data) {
            verifyCoupon(parsed.data, parsed.email);
            return;
        }
    } catch (e) {
        // Not JSON, treat as encrypted data
        console.log('QR is not JSON, treating as encrypted data');
    }
    
    // Legacy format - need email from form
    const email = DOM.manualEmail?.value.trim();
    if (email) {
        verifyCoupon(qrData, email);
    } else {
        showEmailPrompt(qrData);
    }
}

function showEmailPrompt(qrData) {
    showResult(`
        <div style="text-align: center;">
            <h3>📧 Email Required</h3>
            <p style="margin: 12px 0;">Enter the attendee's email to verify:</p>
            <input type="email" id="promptEmail" class="form-input" placeholder="attendee@example.com" style="max-width: 300px; margin: 0 auto;">
            <div style="margin-top: 16px;">
                <button class="btn btn-primary" onclick="verifyWithPromptEmail('${qrData}')">Verify</button>
                <button class="btn btn-secondary" onclick="resumeScanning()">Cancel</button>
            </div>
        </div>
    `, 'info');
}

function verifyWithPromptEmail(qrData) {
    const email = document.getElementById('promptEmail')?.value.trim();
    if (email && email.includes('@')) {
        verifyCoupon(qrData, email);
    } else {
        showResult('❌ Please enter a valid email address.', 'error');
        setTimeout(() => showEmailPrompt(qrData), 2000);
    }
}

// ===== Capture and Scan =====
function captureAndScan() {
    if (!DOM.video || DOM.video.readyState < DOM.video.HAVE_CURRENT_DATA) {
        showResult('❌ Camera not ready. Please wait.', 'error');
        return;
    }
    
    if (DOM.video.videoWidth === 0 || DOM.video.videoHeight === 0) {
        showResult('❌ Camera feed not available.', 'error');
        return;
    }
    
    updateStatus('Capturing image...', 'scanning');
    
    try {
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        
        canvas.width = DOM.video.videoWidth;
        canvas.height = DOM.video.videoHeight;
        context.drawImage(DOM.video, 0, 0, canvas.width, canvas.height);
        
        const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(imageData.data, imageData.width, imageData.height, {
            inversionAttempts: 'attemptBoth'
        });
        
        if (code && code.data) {
            updateStatus('QR Code found!', 'success');
            ScannerState.detection.processingQR = true;
            processConfirmedQR(code.data);
        } else {
            updateStatus('No QR code found', 'error');
            showResult('📷 No QR code detected in the captured image. Try again.', 'warning');
            setTimeout(resumeScanning, 2000);
        }
    } catch (error) {
        console.error('Capture error:', error);
        showResult('❌ Capture failed. Please try again.', 'error');
        setTimeout(resumeScanning, 2000);
    }
}

function resumeScanning() {
    console.log('🔄 Resuming scanning...');
    resetDetectionState();
    
    if (DOM.video && DOM.video.srcObject && !DOM.video.paused) {
        ScannerState.scanning = true;
        updateStatus('Scanning for QR codes...', 'scanning');
        requestAnimationFrame(scanQRCode);
    } else {
        console.log('Video not ready, restarting scanner...');
        startScanner();
    }
}

// ===== Verification API =====
async function verifyCoupon(encryptedData, email) {
    updateStatus('Verifying coupon...', 'scanning');
    
    try {
        const response = await fetch('/verify-coupon', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                encrypted_data: encryptedData,
                email: email
            })
        });
        
        const data = await response.json();
        showVerificationResult(data);
        
    } catch (error) {
        console.error('Verification error:', error);
        showVerificationResult({
            success: false,
            error: 'Network error. Please check your connection.'
        });
    }
}

function verifyByCode(code, email = null, qrType = 'registration') {
    const typeLabels = {
        'registration': '🎫 Registration',
        'lunch': '🍽️ Lunch',
        'dinner': '🍱 Dinner'
    };
    updateStatus(`Verifying ${typeLabels[qrType] || qrType} code...`, 'scanning');
    
    const requestData = {
        verification_code: code,
        email: email,
        qr_type: qrType
    };
    console.log('🔍 Sending verification request:', requestData);
    
    fetch('/verify-coupon', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestData)
    })
    .then(response => response.json())
    .then(data => {
        console.log('✅ Verification response:', data);
        showVerificationResult(data);
    })
    .catch(error => {
        console.error('Verification error:', error);
        showVerificationResult({
            success: false,
            error: 'Network error. Please check your connection.'
        });
    });
}

function verifyByCodeManual() {
    const code = DOM.verificationCode?.value.trim();
    const email = DOM.codeEmail?.value.trim() || null;  // Email is optional
    
    if (!code) {
        showResult('❌ Please enter the 6-digit verification code.', 'error');
        return;
    }
    
    if (!/^\d{6}$/.test(code)) {
        showResult('❌ Verification code must be exactly 6 digits.', 'error');
        return;
    }
    
    // Email is optional, but if provided, must be valid
    if (email && !email.includes('@')) {
        showResult('❌ Please enter a valid email address.', 'error');
        return;
    }
    
    // Clear form
    if (DOM.verificationCode) DOM.verificationCode.value = '';
    if (DOM.codeEmail) DOM.codeEmail.value = '';
    
    verifyByCode(code, email);
}

function verifyManual() {
    const data = DOM.manualData?.value.trim();
    const email = DOM.manualEmail?.value.trim();
    
    if (!data) {
        showResult('❌ Please enter the QR code data.', 'error');
        return;
    }
    
    if (!email || !email.includes('@')) {
        showResult('❌ Please enter a valid email address.', 'error');
        return;
    }
    
    verifyCoupon(data, email);
}

// ===== Verification Result =====
function showVerificationResult(result) {
    const modal = DOM.verificationModal;
    const content = document.getElementById('verificationContent');
    
    // Add to scan history
    addToScanHistory(result);
    
    // Play sound feedback
    playFeedbackSound(result.success);
    
    if (!modal || !content) {
        // Fallback to inline result with auto-dismiss
        const typeLabels = {
            'registration': '🎫 Registration',
            'lunch': '🍽️ Lunch',
            'dinner': '🍱 Dinner'
        };
        const qrTypeLabel = typeLabels[result.qr_type] || result.qr_type || '';
        
        if (result.success) {
            updateStatus(`${qrTypeLabel} verified!`, 'success');
            showResult(`
                <div style="text-align: center; padding: 20px;">
                    <div style="font-size: 4rem; margin-bottom: 16px; animation: pulse 0.5s ease-in-out;">✅</div>
                    <h2 style="color: var(--success); margin-bottom: 12px;">${qrTypeLabel} Verified!</h2>
                    <p style="font-size: 1.1rem; margin-bottom: 8px;"><strong>${result.email || ''}</strong></p>
                    <p style="color: var(--text-muted);">Thank you email being sent...</p>
                    <button class="btn btn-success btn-lg" onclick="hideResult(); resumeScanning();" style="margin-top: 20px; padding: 16px 48px; font-size: 1.2rem;">
                        ✓ OK - Next Scan
                    </button>
                </div>
            `, 'success');
        } else {
            updateStatus('Verification failed', 'error');
            showResult(`
                <div style="text-align: center; padding: 20px;">
                    <div style="font-size: 4rem; margin-bottom: 16px;">❌</div>
                    <h2 style="color: var(--error); margin-bottom: 12px;">Verification Failed</h2>
                    <p style="font-size: 1.1rem;">${result.error || 'Unknown error'}</p>
                    ${result.used_at ? `<p style="color: var(--warning); margin-top: 8px;">⚠️ Already used at: ${result.used_at}</p>` : ''}
                    <button class="btn btn-danger btn-lg" onclick="hideResult(); resumeScanning();" style="margin-top: 20px; padding: 16px 48px; font-size: 1.2rem;">
                        ✗ Try Again
                    </button>
                </div>
            `, 'error');
        }
        return;
    }
    
    // Show modal with prominent result
    const typeLabelsModal = {
        'registration': '🎫 Registration Pass',
        'lunch': '🍽️ Lunch Pass',
        'dinner': '🍱 Dinner Pass'
    };
    const qrTypeLabelModal = typeLabelsModal[result.qr_type] || result.qr_type || 'Ticket';
    
    if (result.success) {
        content.innerHTML = `
            <div class="verification-result success" style="text-align: center; padding: 30px;">
                <div class="verification-icon" style="font-size: 5rem; margin-bottom: 20px; animation: bounceIn 0.5s ease-out;">✅</div>
                <div class="verification-title" style="font-size: 2rem; font-weight: 700; color: var(--success); margin-bottom: 12px;">${qrTypeLabelModal} Verified!</div>
                <div class="verification-message" style="color: var(--text-muted); margin-bottom: 20px;">Attendee has been successfully checked in.</div>
                <div class="verification-details" style="background: var(--bg-tertiary); border-radius: 12px; padding: 16px; margin-bottom: 24px;">
                    <div class="detail-row" style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border);">
                        <span class="detail-label" style="color: var(--text-muted);">Email</span>
                        <span class="detail-value" style="font-weight: 600;">${result.email || 'N/A'}</span>
                    </div>
                    <div class="detail-row" style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border);">
                        <span class="detail-label" style="color: var(--text-muted);">Pass Type</span>
                        <span class="detail-value">${qrTypeLabelModal}</span>
                    </div>
                    <div class="detail-row" style="display: flex; justify-content: space-between; padding: 8px 0;">
                        <span class="detail-label" style="color: var(--text-muted);">Thank You Email</span>
                        <span class="detail-value" style="color: var(--success);">📧 Sending...</span>
                    </div>
                </div>
                <button class="btn btn-success" onclick="closeVerificationModal()" style="padding: 20px 60px; font-size: 1.3rem; font-weight: 700; border-radius: 12px;">
                    ✓ OK - Continue Scanning
                </button>
            </div>
        `;
        updateStatus(`${qrTypeLabelModal} verified!`, 'success');
    } else {
        content.innerHTML = `
            <div class="verification-result error" style="text-align: center; padding: 30px;">
                <div class="verification-icon" style="font-size: 5rem; margin-bottom: 20px;">❌</div>
                <div class="verification-title" style="font-size: 2rem; font-weight: 700; color: var(--error); margin-bottom: 12px;">Verification Failed</div>
                <div class="verification-message" style="font-size: 1.1rem; margin-bottom: 20px;">${result.error || 'The ticket could not be verified.'}</div>
                ${result.used_at ? `
                    <div class="verification-details" style="background: rgba(239, 68, 68, 0.1); border-radius: 12px; padding: 16px; margin-bottom: 24px; border: 1px solid rgba(239, 68, 68, 0.3);">
                        <div style="color: var(--warning); font-weight: 600;">⚠️ This ticket was already used</div>
                        <div style="color: var(--text-muted); margin-top: 8px;">Used at: ${result.used_at}</div>
                    </div>
                ` : ''}
                <button class="btn btn-danger" onclick="closeVerificationModal()" style="padding: 20px 60px; font-size: 1.3rem; font-weight: 700; border-radius: 12px;">
                    ✗ Try Again
                </button>
            </div>
        `;
        updateStatus('Verification failed', 'error');
    }
    
    modal.classList.add('visible');
}

function closeVerificationModal() {
    if (DOM.verificationModal) {
        DOM.verificationModal.classList.remove('visible');
    }
    setTimeout(resumeScanning, 500);
}

function closeAllModals() {
    document.querySelectorAll('.modal-overlay').forEach(modal => {
        modal.classList.remove('visible');
    });
}

// ===== Device Registration =====
function showDeviceRegistration() {
    const isMobile = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent);
    const isLocal = /^(192\.168\.|10\.|localhost|127\.0\.0\.1)/.test(window.location.hostname);
    
    if ((isMobile || isLocal) && DOM.registrationModal) {
        DOM.registrationModal.classList.add('visible');
    }
}

function registerDevice() {
    const staffEmail = document.getElementById('staffEmail')?.value.trim();
    const deviceName = document.getElementById('deviceName')?.value.trim();
    const eventName = document.getElementById('eventName')?.value.trim() || 'DCS Day \'26';
    
    if (!staffEmail || !deviceName) {
        alert('Please fill in all required fields.');
        return;
    }
    
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(staffEmail)) {
        alert('Please enter a valid email address.');
        return;
    }
    
    ScannerState.deviceInfo = { staffEmail, deviceName, eventName };
    ScannerState.deviceRegistered = true;
    
    if (DOM.registrationModal) {
        DOM.registrationModal.classList.remove('visible');
    }
    
    showResult(`
        <div style="text-align: center;">
            ✅ <strong>Device Registered!</strong><br><br>
            <strong>Staff:</strong> ${staffEmail}<br>
            <strong>Device:</strong> ${deviceName}<br>
            <strong>Event:</strong> ${eventName}
        </div>
    `, 'success');
}

function skipRegistration() {
    if (DOM.registrationModal) {
        DOM.registrationModal.classList.remove('visible');
    }
    
    showResult('⚠️ Device registration skipped. You can still scan tickets.', 'warning');
}

// ===== Camera Error Handling =====
function handleCameraError(error) {
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    const isAndroid = /Android/i.test(navigator.userAgent);
    const isMobile = isIOS || isAndroid;
    
    let errorTitle = '❌ Camera Access Failed';
    let errorMessage = '';
    let troubleshooting = '';
    
    if (error.name === 'NotAllowedError') {
        errorMessage = '<strong>Permission Denied:</strong> Camera access was blocked.';
        
        if (isIOS) {
            troubleshooting = `
                <strong>📱 For iOS (Safari):</strong><br>
                1. When prompted, tap "Allow"<br>
                2. If no prompt: Settings → Safari → Camera → Allow<br>
                3. Return and refresh this page<br><br>
                
                <strong>For other browsers:</strong><br>
                • Brave: Tap shield icon → Enable Camera<br>
                • Chrome: Tap lock icon → Permissions → Camera → Allow
            `;
        } else if (isAndroid) {
            troubleshooting = `
                <strong>📱 For Android (Chrome):</strong><br>
                1. Tap the lock icon (🔒) in address bar<br>
                2. Tap "Permissions"<br>
                3. Enable "Camera"<br>
                4. Refresh this page<br><br>
                
                <strong>For Brave Browser:</strong><br>
                • Tap the shield icon (🛡️)<br>
                • Toggle "Camera" to ON<br>
                • Refresh the page
            `;
        } else {
            troubleshooting = `
                <strong>🖥️ For Desktop:</strong><br>
                1. Click the camera icon in the address bar<br>
                2. Select "Allow" for camera access<br>
                3. Refresh the page if needed<br><br>
                
                <strong>Browser Settings:</strong><br>
                • Chrome: Settings → Privacy → Site Settings → Camera<br>
                • Firefox: Settings → Privacy → Permissions → Camera
            `;
        }
    } else if (error.name === 'NotFoundError') {
        errorMessage = '<strong>No Camera Found:</strong> No camera detected on this device.';
        troubleshooting = `
            <strong>Possible Solutions:</strong><br>
            1. Check if another app is using the camera<br>
            2. Close all camera apps and try again<br>
            3. Restart your browser<br>
            4. Restart your device<br>
            5. Check if camera works in other apps
        `;
    } else if (error.name === 'NotReadableError') {
        errorMessage = '<strong>Camera Busy:</strong> Camera is being used by another application.';
        troubleshooting = `
            <strong>Solutions:</strong><br>
            1. Close all other apps using the camera<br>
            2. Close other browser tabs with camera access<br>
            3. Restart your browser<br>
            4. Wait a few seconds and try again
        `;
    } else if (error.name === 'NotSupportedError') {
        errorMessage = '<strong>Not Supported:</strong> Camera not supported in this browser.';
        troubleshooting = `
            <strong>Try these browsers:</strong><br>
            • Chrome (recommended)<br>
            • Firefox<br>
            • Safari (iOS)<br>
            • Edge
        `;
    } else {
        errorMessage = `<strong>Error:</strong> ${error.message}`;
        troubleshooting = `
            <strong>General Troubleshooting:</strong><br>
            1. Refresh the page and try again<br>
            2. Check camera permissions<br>
            3. Try a different browser<br>
            4. Restart your device
        `;
    }
    
    updateStatus('Camera error', 'error');
    
    showResult(`
        <div style="text-align: left;">
            <h3 style="color: var(--error); margin-bottom: 16px;">${errorTitle}</h3>
            <p style="margin-bottom: 16px;">${errorMessage}</p>
            
            <div style="background: rgba(0,0,0,0.2); padding: 16px; border-radius: 8px; margin-bottom: 16px;">
                ${troubleshooting}
            </div>
            
            <div style="background: rgba(99, 102, 241, 0.1); padding: 16px; border-radius: 8px; margin-bottom: 16px; border: 1px solid rgba(99, 102, 241, 0.3);">
                <strong>💡 Alternative:</strong> Use Manual Verification below to verify tickets without camera.
            </div>
            
            <div style="text-align: center;">
                <button class="btn btn-primary" onclick="location.reload()" style="margin-right: 8px;">
                    🔄 Refresh & Retry
                </button>
                <button class="btn btn-secondary" onclick="document.querySelector('.manual-panel')?.scrollIntoView({behavior: 'smooth'})">
                    📝 Manual Entry
                </button>
            </div>
        </div>
    `, 'error');
    
    // Auto-scroll to manual entry after delay
    setTimeout(() => {
        document.querySelector('.manual-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 3000);
}

// ===== Camera Help =====
function showCameraHelp() {
    const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
    const isAndroid = /Android/i.test(navigator.userAgent);
    
    let help = '<h3>📷 Camera Troubleshooting</h3><br>';
    
    if (isIOS) {
        help += `
            <strong>For iOS:</strong><br>
            1. Use Safari browser<br>
            2. Go to Settings → Safari → Camera<br>
            3. Select "Allow" for this website<br>
            4. Refresh the page<br>
        `;
    } else if (isAndroid) {
        help += `
            <strong>For Android:</strong><br>
            1. Tap the lock icon in the address bar<br>
            2. Enable Camera permission<br>
            3. Refresh the page<br>
        `;
    } else {
        help += `
            <strong>For Desktop:</strong><br>
            1. Click the camera icon in the address bar<br>
            2. Allow camera access<br>
            3. Refresh if needed<br>
        `;
    }
    
    help += '<br><button class="btn btn-secondary btn-sm" onclick="hideResult()">Close</button>';
    
    showResult(help, 'info');
}

// ===== Scan History & Statistics =====
const ScanHistory = {
    scans: [],
    maxHistory: 50
};

function addToScanHistory(result) {
    const scan = {
        timestamp: new Date().toLocaleTimeString(),
        email: result.email || 'Unknown',
        success: result.success,
        error: result.error || null,
        event: result.event_name || "DCS Day '26"
    };
    
    ScanHistory.scans.unshift(scan);
    
    // Keep only last N scans
    if (ScanHistory.scans.length > ScanHistory.maxHistory) {
        ScanHistory.scans.pop();
    }
    
    // Update stats display
    updateScanStats();
}

function updateScanStats() {
    const statsContainer = document.getElementById('scanStats');
    if (!statsContainer) return;
    
    const total = ScanHistory.scans.length;
    const successful = ScanHistory.scans.filter(s => s.success).length;
    const failed = total - successful;
    
    const lastScan = ScanHistory.scans[0];
    
    statsContainer.innerHTML = `
        <div class="stats-grid">
            <div class="stat-card success">
                <div class="stat-number">${successful}</div>
                <div class="stat-label">Verified</div>
            </div>
            <div class="stat-card error">
                <div class="stat-number">${failed}</div>
                <div class="stat-label">Failed</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">${total}</div>
                <div class="stat-label">Total Scans</div>
            </div>
        </div>
        ${lastScan ? `
            <div class="last-scan ${lastScan.success ? 'success' : 'error'}">
                <div class="last-scan-label">Last Scan:</div>
                <div class="last-scan-email">${lastScan.success ? '✅' : '❌'} ${lastScan.email}</div>
                <div class="last-scan-time">${lastScan.timestamp}</div>
            </div>
        ` : ''}
        ${ScanHistory.scans.length > 0 ? `
            <button class="btn btn-secondary btn-sm" onclick="showScanHistory()" style="margin-top: 12px; width: 100%;">
                📋 View Full History (${total})
            </button>
        ` : ''}
    `;
}

function showScanHistory() {
    let historyHTML = `
        <div style="max-height: 400px; overflow-y: auto;">
            <h3 style="margin-bottom: 16px;">📋 Scan History</h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 0.9rem;">
                <thead>
                    <tr style="border-bottom: 2px solid var(--border);">
                        <th style="text-align: left; padding: 8px;">Status</th>
                        <th style="text-align: left; padding: 8px;">Email</th>
                        <th style="text-align: right; padding: 8px;">Time</th>
                    </tr>
                </thead>
                <tbody>
    `;
    
    ScanHistory.scans.forEach(scan => {
        historyHTML += `
            <tr style="border-bottom: 1px solid var(--border);">
                <td style="padding: 8px;">${scan.success ? '✅' : '❌'}</td>
                <td style="padding: 8px; word-break: break-all;">${scan.email}</td>
                <td style="padding: 8px; text-align: right; white-space: nowrap;">${scan.timestamp}</td>
            </tr>
        `;
    });
    
    historyHTML += `
                </tbody>
            </table>
            <button class="btn btn-secondary" onclick="hideResult()" style="margin-top: 16px; width: 100%;">Close</button>
        </div>
    `;
    
    showResult(historyHTML, 'info');
}

// ===== Sound Feedback =====
function playFeedbackSound(success) {
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);
        
        if (success) {
            // Success: Two-tone rising beep
            oscillator.frequency.setValueAtTime(523.25, audioContext.currentTime); // C5
            oscillator.frequency.setValueAtTime(659.25, audioContext.currentTime + 0.1); // E5
            gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.3);
            oscillator.start(audioContext.currentTime);
            oscillator.stop(audioContext.currentTime + 0.3);
        } else {
            // Error: Low buzz
            oscillator.frequency.setValueAtTime(200, audioContext.currentTime);
            oscillator.type = 'square';
            gainNode.gain.setValueAtTime(0.2, audioContext.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.4);
            oscillator.start(audioContext.currentTime);
            oscillator.stop(audioContext.currentTime + 0.4);
        }
    } catch (e) {
        console.log('Audio feedback not available:', e.message);
    }
}

// Export functions for HTML onclick handlers
window.startScanner = startScanner;
window.stopScanner = stopScanner;
window.captureAndScan = captureAndScan;
window.resumeScanning = resumeScanning;
window.verifyByCodeManual = verifyByCodeManual;
window.verifyManual = verifyManual;
window.verifyWithPromptEmail = verifyWithPromptEmail;
window.showCameraHelp = showCameraHelp;
window.closeVerificationModal = closeVerificationModal;
window.registerDevice = registerDevice;
window.skipRegistration = skipRegistration;
window.showCameraSelector = showCameraSelector;
window.switchToCamera = switchToCamera;
window.hideResult = hideResult;
window.showScanHistory = showScanHistory;
