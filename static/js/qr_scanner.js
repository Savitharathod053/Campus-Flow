// Campus Flow Multi-Session QR Code Scanner for Attendance Tracking

let html5QrCode = null;
let isScanning = false;
let audioCtx = null;
let currentEventId = null;

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

function showScanResult(type, title, message, studentData = null, rawCode = null) {
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
    } else if (type === 'session_closed') {
        alertClass = 'alert-warning border-warning';
        icon = 'bi-clock-history';
        playWarningBeep();
    } else {
        alertClass = 'alert-danger border-danger';
        icon = 'bi-x-circle-fill';
        playWarningBeep();
    }

    let studentHtml = '';
    if (studentData && (studentData.student_name || studentData.name || studentData.roll_number)) {
        const studentName = studentData.student_name || studentData.name || studentData.student || 'N/A';
        const rollNumber = studentData.roll_number || studentData.rollNumber || studentData.roll_no || 'N/A';
        const dept = studentData.department || studentData.department_name || studentData.dept || 'N/A';
        const yearSec = (studentData.year && studentData.year !== 'N/A') ? ` (${studentData.year}${studentData.section && studentData.section !== 'N/A' ? '-' + studentData.section : ''})` : '';
        const sessionName = studentData.session_name || studentData.session || 'General Attendance';
        const scannedTime = studentData.scanned_at || studentData.time || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const teamName = studentData.team_name || studentData.team || '';

        studentHtml = `
            <div class="mt-2 pt-2 border-top">
                <div class="row g-2 small">
                    <div class="col-sm-6"><strong>Student:</strong> ${studentName}</div>
                    <div class="col-sm-6"><strong>Roll Number:</strong> <span class="badge bg-light text-dark border">${rollNumber}</span></div>
                    <div class="col-sm-6"><strong>Department:</strong> ${dept}${yearSec}</div>
                    ${teamName ? `<div class="col-sm-6"><strong>Team:</strong> <span class="badge bg-primary bg-opacity-10 text-primary">${teamName}</span></div>` : ''}
                    <div class="col-sm-6"><strong>Session:</strong> <span class="badge bg-info text-dark">${sessionName}</span></div>
                    <div class="col-sm-6"><strong>Time:</strong> ${scannedTime}</div>
                    ${studentData.student_percentage !== undefined ? `<div class="col-sm-6"><strong>Progress:</strong> ${studentData.student_attended_sessions}/${studentData.total_sessions} (${studentData.student_percentage}%)</div>` : ''}
                </div>
            </div>
        `;
    }

    let overrideBtnHtml = '';
    if (type === 'session_closed' && rawCode && studentData && studentData.can_override) {
        overrideBtnHtml = `
            <div class="mt-2">
                <button type="button" class="btn btn-warning btn-sm fw-bold" onclick="overrideSessionTimeScan('${rawCode}')">
                    <i class="bi bi-shield-exclamation me-1"></i> Override Time & Mark Attendance
                </button>
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
                ${overrideBtnHtml}
            </div>
        </div>
    `;

    // Update live count badge
    if (type === 'success' && studentData && studentData.session_present_count !== undefined) {
        const countBadge = document.getElementById('session-present-count');
        if (countBadge) countBadge.innerText = studentData.session_present_count;

        const liveCountBadge = document.getElementById('live-checkin-count');
        if (liveCountBadge) {
            const current = parseInt(liveCountBadge.innerText) || 0;
            liveCountBadge.innerText = `${current + 1} Recorded`;
        }

        // Add to live log
        const logTable = document.getElementById('recent-attendance-tbody');
        if (logTable) {
            const emptyRow = logTable.querySelector('.empty-log-row');
            if (emptyRow) emptyRow.remove();

            const newRow = document.createElement('tr');
            newRow.className = 'table-success';
            newRow.innerHTML = `
                <td>
                    <strong>${studentData.student_name}</strong>
                    ${studentData.team_name ? `<br><span class="badge bg-primary bg-opacity-10 text-primary small">${studentData.team_name}</span>` : ''}
                </td>
                <td><span class="badge bg-light text-dark border">${studentData.roll_number}</span></td>
                <td>${studentData.department} (${studentData.year || ''}-${studentData.section || ''})</td>
                <td><span class="badge bg-info text-dark small">${studentData.session_name}</span></td>
                <td>${studentData.scanned_at}</td>
                <td><span class="badge bg-success">Verified</span></td>
            `;
            logTable.insertBefore(newRow, logTable.firstChild);
        }
    }
}

async function verifyAndMarkAttendance(ticketCode, eventId, allowOverride = false) {
    const statusText = document.getElementById('scanner-status');
    const manualBtn = document.querySelector('#manual-entry-form button[type="submit"]');
    const manualInput = document.getElementById('manual-ticket-code');

    if (statusText) statusText.innerText = 'Verifying ticket code...';
    if (manualBtn) {
        manualBtn.disabled = true;
        manualBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span> Verifying...';
    }

    const sessionSelect = document.getElementById('scanner-session-select');
    const sessionId = (sessionSelect && sessionSelect.value) ? sessionSelect.value : null;

    try {
        const response = await fetch('/organizer/attendance/mark', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                registration_code: ticketCode,
                event_id: eventId,
                session_id: sessionId,
                allow_time_override: allowOverride
            })
        });

        const data = await response.json();

        if (response.ok && data.status === 'success') {
            showScanResult('success', 'Attendance Recorded!', data.message, data, ticketCode);
            if (manualInput) manualInput.value = '';
        } else if (data.status === 'duplicate') {
            showScanResult('duplicate', 'Already Marked Present', data.message, data, ticketCode);
        } else if (data.status === 'session_closed') {
            showScanResult('session_closed', 'Session Closed / Inactive', data.message, data, ticketCode);
        } else if (data.status === 'unpaid') {
            showScanResult('error', 'Payment Pending', data.message, data, ticketCode);
        } else {
            showScanResult('error', 'Verification Failed', data.message || 'Invalid or unregistered ticket.', data, ticketCode);
        }
    } catch (err) {
        showScanResult('error', 'Network Error', 'Could not reach attendance server: ' + (err.message || err));
    } finally {
        if (statusText) statusText.innerText = 'Ready for next scan';
        if (manualBtn) {
            manualBtn.disabled = false;
            manualBtn.innerHTML = 'Verify & Mark';
        }
        if (manualInput) {
            manualInput.focus();
        }
    }
}

function overrideSessionTimeScan(ticketCode) {
    if (currentEventId) {
        verifyAndMarkAttendance(ticketCode, currentEventId, true);
    }
}

function initAttendanceScanner(eventId) {
    currentEventId = eventId;
    const startBtn = document.getElementById('btn-start-camera');
    const stopBtn = document.getElementById('btn-stop-camera');
    const manualForm = document.getElementById('manual-entry-form');
    const manualInput = document.getElementById('manual-ticket-code');
    const sessionSelect = document.getElementById('scanner-session-select');

    // 1. Setup Session Selector listener
    if (sessionSelect) {
        sessionSelect.addEventListener('change', function() {
            const url = new URL(window.location.href);
            url.searchParams.set('session_id', this.value);
            window.location.href = url.toString();
        });
    }

    // 2. Setup Manual Entry Form listener FIRST (independent of camera/QR library)
    if (manualForm) {
        manualForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const code = manualInput ? manualInput.value.trim() : '';
            if (code) {
                verifyAndMarkAttendance(code, eventId);
            } else if (manualInput) {
                manualInput.focus();
            }
        });
    }

    // 3. Safely initialize QR Scanner only if library and element are available
    try {
        if (typeof Html5Qrcode !== 'undefined' && document.getElementById("reader")) {
            html5QrCode = new Html5Qrcode("reader");

            const onScanSuccess = (decodedText) => {
                html5QrCode.pause();
                verifyAndMarkAttendance(decodedText, eventId);
                setTimeout(() => {
                    try { html5QrCode.resume(); } catch (e) {}
                }, 1800);
            };

            if (startBtn) {
                startBtn.addEventListener('click', () => {
                    const config = { fps: 10, qrbox: { width: 250, height: 250 } };
                    html5QrCode.start({ facingMode: "environment" }, config, onScanSuccess)
                        .then(() => {
                            isScanning = true;
                            startBtn.classList.add('d-none');
                            if (stopBtn) stopBtn.classList.remove('d-none');
                            const statusElem = document.getElementById('scanner-status');
                            if (statusElem) statusElem.innerText = 'Camera active. Point at attendee QR code.';
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
                            if (startBtn) startBtn.classList.remove('d-none');
                            stopBtn.classList.add('d-none');
                            const statusElem = document.getElementById('scanner-status');
                            if (statusElem) statusElem.innerText = 'Camera stopped.';
                        });
                    }
                });
            }
        }
    } catch (qrErr) {
        console.warn('QR scanner library initialization skipped or failed:', qrErr);
    }
}
