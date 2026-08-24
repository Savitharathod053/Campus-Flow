// FastFest In-Browser Camera QR Code Scanner for Attendance Tracking

let html5QrCode = null;
let isScanning = false;
let audioCtx = null;

function getAudioContext() {
    if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return audioCtx;
}

function playSuccessBeep() {
    try {
        const ctx = getAudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(880, ctx.currentTime); // A5
        osc.frequency.setValueAtTime(1174.66, ctx.currentTime + 0.1); // D6
        gain.gain.setValueAtTime(0.2, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.3);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.3);
    } catch (e) {}
}

function playWarningBeep() {
    try {
        const ctx = getAudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(300, ctx.currentTime);
        osc.frequency.setValueAtTime(220, ctx.currentTime + 0.15);
        gain.gain.setValueAtTime(0.3, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.4);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.4);
    } catch (e) {}
}

function showScanResult(type, title, message, studentData = null) {
    const resultBox = document.getElementById('scan-result-box');
    if (!resultBox) return;

    let alertClass = 'alert-info';
    let icon = 'bi-info-circle';

    if (type === 'success') {
        alertClass = 'alert-success border-success';
        icon = 'bi-check-circle-fill';
        playSuccessBeep();
    } else if (type === 'duplicate') {
        alertClass = 'alert-warning border-warning';
        icon = 'bi-exclamation-triangle-fill';
        playWarningBeep();
    } else {
        alertClass = 'alert-danger border-danger';
        icon = 'bi-x-circle-fill';
        playWarningBeep();
    }

    let studentHtml = '';
    if (studentData) {
        studentHtml = `
            <div class="mt-2 pt-2 border-top">
                <div class="row g-2">
                    <div class="col-sm-6"><strong>Student:</strong> ${studentData.student_name}</div>
                    <div class="col-sm-6"><strong>Roll Number:</strong> ${studentData.roll_number || 'N/A'}</div>
                    <div class="col-sm-6"><strong>Department:</strong> ${studentData.department || 'N/A'}</div>
                    <div class="col-sm-6"><strong>Time:</strong> ${studentData.scanned_at}</div>
                </div>
            </div>
        `;
    }

    resultBox.innerHTML = `
        <div class="alert ${alertClass} d-flex align-items-start gap-3 shadow-sm mb-3">
            <i class="bi ${icon} fs-3 flex-shrink-0"></i>
            <div class="flex-grow-1">
                <h5 class="alert-heading mb-1">${title}</h5>
                <p class="mb-0">${message}</p>
                ${studentHtml}
            </div>
        </div>
    `;

    // Add to recent log list
    if (type === 'success' && studentData) {
        const logTable = document.getElementById('recent-attendance-tbody');
        if (logTable) {
            const newRow = document.createElement('tr');
            newRow.className = 'table-success';
            newRow.innerHTML = `
                <td><strong>${studentData.student_name}</strong></td>
                <td><span class="badge bg-light text-dark border">${studentData.roll_number}</span></td>
                <td>${studentData.department} (${studentData.year}-${studentData.section})</td>
                <td>${studentData.scanned_at}</td>
                <td><span class="badge bg-success">Verified</span></td>
            `;
            logTable.insertBefore(newRow, logTable.firstChild);
        }
    }
}

async function verifyAndMarkAttendance(ticketCode, eventId) {
    const statusText = document.getElementById('scanner-status');
    if (statusText) statusText.innerText = 'Verifying ticket code...';

    try {
        const response = await fetch('/organizer/attendance/mark', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                registration_code: ticketCode,
                event_id: eventId
            })
        });

        const data = await response.json();

        if (response.ok && data.status === 'success') {
            showScanResult('success', 'Attendance Marked Successfully!', data.message, data);
        } else if (data.status === 'duplicate') {
            showScanResult('duplicate', 'Duplicate Scan Notice', data.message, data);
        } else {
            showScanResult('error', 'Verification Failed', data.message || 'Invalid or unregistered ticket.');
        }
    } catch (err) {
        showScanResult('error', 'Network Error', 'Could not reach attendance server.');
    } finally {
        if (statusText) statusText.innerText = 'Ready for next scan';
    }
}

function initAttendanceScanner(eventId) {
    const startBtn = document.getElementById('btn-start-camera');
    const stopBtn = document.getElementById('btn-stop-camera');
    const manualForm = document.getElementById('manual-entry-form');
    const manualInput = document.getElementById('manual-ticket-code');

    html5QrCode = new Html5Qrcode("reader");

    const onScanSuccess = (decodedText) => {
        // Pause scanning briefly to prevent rapid duplicate calls
        html5QrCode.pause();
        verifyAndMarkAttendance(decodedText, eventId);
        setTimeout(() => {
            try { html5QrCode.resume(); } catch (e) {}
        }, 2500);
    };

    if (startBtn) {
        startBtn.addEventListener('click', () => {
            const config = { fps: 10, qrbox: { width: 250, height: 250 } };
            html5QrCode.start({ facingMode: "environment" }, config, onScanSuccess)
                .then(() => {
                    isScanning = true;
                    startBtn.classList.add('d-none');
                    stopBtn.classList.remove('d-none');
                    document.getElementById('scanner-status').innerText = 'Camera active. Point at ticket QR code.';
                })
                .catch(err => {
                    alert('Camera access error: ' + err);
                });
        });
    }

    if (stopBtn) {
        stopBtn.addEventListener('click', () => {
            if (isScanning && html5QrCode) {
                html5QrCode.stop().then(() => {
                    isScanning = false;
                    startBtn.classList.remove('d-none');
                    stopBtn.classList.add('d-none');
                    document.getElementById('scanner-status').innerText = 'Camera stopped.';
                });
            }
        });
    }

    if (manualForm) {
        manualForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const code = manualInput.value.trim();
            if (code) {
                verifyAndMarkAttendance(code, eventId);
                manualInput.value = '';
            }
        });
    }
}
