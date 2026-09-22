// Campus Flow — Interactive Modern Platform JavaScript

document.addEventListener('DOMContentLoaded', () => {
    // ---------------------------------------------------------
    // 1. Alert Auto-Dismissal & Form Toggles
    // ---------------------------------------------------------
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(alert => {
        setTimeout(() => {
            try {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            } catch (e) {}
        }, 6000);
    });

    // Toggle free event pricing input in event creation
    const isFreeCheckbox = document.getElementById('is_free');
    const feeInputGroup = document.getElementById('fee_input_group');
    const feeInput = document.getElementById('registration_fee');

    if (isFreeCheckbox && feeInputGroup) {
        const toggleFee = () => {
            if (isFreeCheckbox.checked) {
                feeInputGroup.style.display = 'none';
                if (feeInput) feeInput.value = '0.0';
            } else {
                feeInputGroup.style.display = 'block';
            }
        };
        isFreeCheckbox.addEventListener('change', toggleFee);
        toggleFee();
    }

    // ---------------------------------------------------------
    // 2. Dynamic Time-Based Greeting
    // ---------------------------------------------------------
    initDynamicGreetings();

    // ---------------------------------------------------------
    // 3. Glassmorphic Frosted Navbar on Scroll
    // ---------------------------------------------------------
    initGlassNavbar();

    // ---------------------------------------------------------
    // 4. Card Depth & 3D Tilt Interaction
    // ---------------------------------------------------------
    initCardTilt();

    // ---------------------------------------------------------
    // 5. Animated Numeric Stat Counters
    // ---------------------------------------------------------
    initStatCounters();

    // ---------------------------------------------------------
    // 6. Scroll-Reveal Animation System
    // ---------------------------------------------------------
    initScrollReveal();

    // ---------------------------------------------------------
    // 7. Click-to-Copy for Passes and Certificates
    // ---------------------------------------------------------
    initCopyButtons();
});


/* ==========================================================================
   Interactive UI Feature Functions
   ========================================================================== */

/**
 * Updates greeting elements with local time-aware greetings:
 * "Good Morning", "Good Afternoon", or "Good Evening".
 */
function initDynamicGreetings() {
    const greetingElements = document.querySelectorAll('.dynamic-greeting, [data-greeting]');
    if (!greetingElements.length) return;

    const hour = new Date().getHours();
    let greetingText = 'Good Morning';
    let greetingIcon = 'bi-brightness-high';

    if (hour >= 12 && hour < 17) {
        greetingText = 'Good Afternoon';
        greetingIcon = 'bi-sun';
    } else if (hour >= 17 || hour < 5) {
        greetingText = 'Good Evening';
        greetingIcon = 'bi-moon-stars';
    }

    greetingElements.forEach(el => {
        const name = el.dataset.userName || '';
        el.innerHTML = `${greetingText}${name ? ', ' + name : ''} 👋`;
    });
}


/**
 * Toggles a frosted glassmorphic state on .ff-navbar when scrolled down.
 */
function initGlassNavbar() {
    const navbar = document.querySelector('.ff-navbar');
    if (!navbar) return;

    const handleScroll = () => {
        if (window.scrollY > 15) {
            navbar.classList.add('navbar-scrolled');
        } else {
            navbar.classList.remove('navbar-scrolled');
        }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    handleScroll();
}


/**
 * Adds subtle 3D tilt-on-hover effect to interactive cards and dashboard stat cards,
 * tracking mouse position across the card surface.
 * Respects prefers-reduced-motion and disables on touch devices.
 */
function initCardTilt() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const isFinePointer = window.matchMedia('(pointer: fine)').matches;
    if (prefersReducedMotion || !isFinePointer) return;

    // Only apply subtle tilt to cards that explicitly request it
    const candidateCards = document.querySelectorAll('.tilt-card');

    candidateCards.forEach(card => {
        // Exclude cards that contain whole data tables or interactive forms
        if (card.querySelector('table') || card.querySelector('form')) return;

        let isHovered = false;

        card.addEventListener('mouseenter', () => {
            isHovered = true;
            card.style.transition = 'transform 0.12s ease-out, box-shadow 0.2s ease, border-color 0.2s ease';
        });

        card.addEventListener('mousemove', (e) => {
            if (!isHovered) return;
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;

            // Gentle, contained rotation limits (max 2.5 degrees, no translateZ)
            const maxTilt = 2.5;
            const tiltX = -((y - centerY) / centerY) * maxTilt;
            const tiltY = ((x - centerX) / centerX) * maxTilt;

            card.style.transform = `rotateX(${tiltX.toFixed(2)}deg) rotateY(${tiltY.toFixed(2)}deg) translateY(-3px)`;
        });

        card.addEventListener('mouseleave', () => {
            isHovered = false;
            card.style.transition = 'transform 0.28s ease, box-shadow 0.25s ease, border-color 0.2s ease';
            card.style.transform = '';
        });
    });
}


/**
 * Animates numeric stat counters from 0 to their target value
 * when they enter the viewport using IntersectionObserver.
 */
function initStatCounters() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const elements = document.querySelectorAll(
        '.count-up, [data-counter], .metric-number, .card.border-start h3, .row.g-3 > [class*="col-"] > .card h3'
    );
    if (!elements.length) return;

    const counterElements = [];
    elements.forEach(el => {
        const text = el.textContent.trim();
        if (/^\d+\+?$/.test(text)) {
            if (!el.dataset.target) {
                el.dataset.target = text.replace(/[^\d]/g, '');
                if (text.includes('+')) el.dataset.plus = 'true';
            }
            counterElements.push(el);
        } else if (el.dataset.target) {
            counterElements.push(el);
        }
    });

    if (!counterElements.length) return;

    if (!('IntersectionObserver' in window) || prefersReducedMotion) {
        counterElements.forEach(el => {
            if (el.dataset.target) {
                const hasPlus = el.dataset.plus === 'true' || el.textContent.includes('+');
                el.textContent = el.dataset.target + (hasPlus ? '+' : '');
            }
        });
        return;
    }

    const counterObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (!entry.isIntersecting) return;
            const el = entry.target;
            observer.unobserve(el);

            const rawTarget = el.dataset.target || el.textContent.replace(/[^\d]/g, '');
            const targetVal = parseInt(rawTarget, 10);
            if (isNaN(targetVal) || targetVal === 0) return;

            const hasPlus = el.dataset.plus === 'true' || el.textContent.includes('+');
            const duration = 1200; // ms
            const startTime = performance.now();

            const updateCount = (currentTime) => {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const easeOut = 1 - Math.pow(1 - progress, 3);
                const currentVal = Math.floor(easeOut * targetVal);

                el.textContent = currentVal.toLocaleString() + (hasPlus ? '+' : '');

                if (progress < 1) {
                    requestAnimationFrame(updateCount);
                } else {
                    el.textContent = targetVal.toLocaleString() + (hasPlus ? '+' : '');
                }
            };

            requestAnimationFrame(updateCount);
        });
    }, { threshold: 0.15 });

    counterElements.forEach(el => counterObserver.observe(el));
}


/**
 * Animates elements smoothly into view as user scrolls down the page.
 */
function initScrollReveal() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion || !('IntersectionObserver' in window)) {
        document.querySelectorAll('.reveal-on-scroll').forEach(el => {
            el.classList.add('is-revealed');
        });
        return;
    }

    document.querySelectorAll(
        '.event-card, .certificate-vault-card'
    ).forEach((card, idx) => {
        if (!card.classList.contains('reveal-on-scroll')) {
            card.classList.add('reveal-on-scroll');
            const delayClass = `reveal-delay-${(idx % 4) + 1}`;
            card.classList.add(delayClass);
        }
    });

    const revealElements = document.querySelectorAll('.reveal-on-scroll');
    if (!revealElements.length) return;

    const revealObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-revealed');
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.08,
        rootMargin: '0px 0px -40px 0px'
    });

    revealElements.forEach(el => revealObserver.observe(el));
}


/**
 * Provides 1-click clipboard copying for ticket pass codes and certificate credentials.
 */
function initCopyButtons() {
    const copyBtns = document.querySelectorAll('[data-copy-target]');
    copyBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const textToCopy = btn.dataset.copyTarget;
            if (!textToCopy) return;

            navigator.clipboard.writeText(textToCopy).then(() => {
                const originalHtml = btn.innerHTML;
                btn.innerHTML = '<i class="bi bi-check2 text-success me-1"></i> Copied!';
                btn.classList.add('border-success');
                setTimeout(() => {
                    btn.innerHTML = originalHtml;
                    btn.classList.remove('border-success');
                }, 2200);
            }).catch(() => {});
        });
    });
}


/* ==========================================================================
   Campus Flow — In-App Notification System Controller
   Handles real-time read/unread toggling, optimistic UI updates, error rollbacks,
   and navbar badge counter synchronization.
   ========================================================================== */

const inFlightNotificationRequests = new Set();
let isMarkingAllInFlight = false;

/**
 * Updates all visual notification counters, badges, and pill indicators across the UI.
 * @param {number} newCount - The updated unread notifications count
 */
function updateNotificationBadgeUI(newCount) {
    const badge = document.getElementById('notificationBadge');
    const pill = document.getElementById('notificationUnreadPill');
    const countText = document.getElementById('notificationUnreadCountText');
    const markAllBtn = document.getElementById('markAllReadBtn');

    const count = Math.max(0, parseInt(newCount, 10) || 0);

    if (badge) {
        badge.textContent = count;
        if (count > 0) {
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }
    }

    if (pill) {
        if (count > 0) {
            pill.classList.remove('d-none');
        } else {
            pill.classList.add('d-none');
        }
    }

    if (countText) {
        countText.textContent = count;
    }

    if (markAllBtn) {
        if (count > 0) {
            markAllBtn.classList.remove('d-none');
        } else {
            markAllBtn.classList.add('d-none');
        }
    }
}

/**
 * Marks an individual notification as read.
 * Provides immediate optimistic visual feedback, decrements bell count,
 * and rolls back gracefully if backend communication fails.
 *
 * @param {number|string} notificationId - The database ID of the notification
 * @param {HTMLElement|null} btnElement - The button triggering the action (optional)
 * @param {Event|null} event - The triggering DOM event (optional)
 */
function markNotificationRead(notificationId, btnElement, event) {
    if (event) {
        try {
            event.preventDefault();
            event.stopPropagation();
        } catch (e) {}
    }
    if (!notificationId) return;

    const notifIdStr = String(notificationId);
    if (inFlightNotificationRequests.has(notifIdStr)) return;
    inFlightNotificationRequests.add(notifIdStr);

    // Identify related DOM elements
    const dropdownItem = document.getElementById(`notif-dropdown-item-${notificationId}`);
    const dot = document.getElementById(`notif-dot-${notificationId}`);
    const markBtn = btnElement || document.getElementById(`notif-mark-read-btn-${notificationId}`);
    const hodCard = document.getElementById(`alert-card-${notificationId}`);
    const hodRow = document.getElementById(`table-row-${notificationId}`);

    const badge = document.getElementById('notificationBadge');
    const prevBadgeCount = badge ? (parseInt(badge.textContent, 10) || 0) : 0;
    const wasUnread = dropdownItem ? (dropdownItem.dataset.isRead !== 'true') : true;

    // 1. Optimistic UI Updates:
    if (dropdownItem) {
        dropdownItem.classList.remove('notification-unread');
        dropdownItem.classList.add('notification-read');
        dropdownItem.dataset.isRead = 'true';
    }
    if (dot) {
        dot.classList.add('d-none');
    }
    if (markBtn) {
        markBtn.classList.add('d-none');
        markBtn.disabled = true;
    }
    if (hodCard) {
        hodCard.style.opacity = '0.5';
        const cardBtn = hodCard.querySelector('button');
        if (cardBtn) cardBtn.outerHTML = '<span class="badge bg-secondary">Read</span>';
    }
    if (hodRow) {
        hodRow.classList.remove('table-warning-subtle', 'fw-semibold');
        const rBadge = hodRow.querySelector('.badge.bg-danger');
        if (rBadge) {
            rBadge.className = 'badge bg-light text-secondary border';
            rBadge.textContent = 'Read';
        }
        const rowBtn = hodRow.querySelector('button');
        if (rowBtn) rowBtn.remove();
    }

    // Decrement navbar unread badge immediately
    if (wasUnread && prevBadgeCount > 0) {
        updateNotificationBadgeUI(prevBadgeCount - 1);
    }

    // 2. Transmit to Backend API
    fetch(`/notifications/${notificationId}/read`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            if (typeof data.unread_count !== 'undefined') {
                updateNotificationBadgeUI(data.unread_count);
            }
        } else {
            throw new Error(data.message || 'Mark as read failed');
        }
    })
    .catch(err => {
        console.error(`Failed to mark notification ${notificationId} as read:`, err);
        // 3. Rollback UI if backend request failed
        if (dropdownItem && wasUnread) {
            dropdownItem.classList.add('notification-unread');
            dropdownItem.classList.remove('notification-read');
            dropdownItem.dataset.isRead = 'false';
        }
        if (dot && wasUnread) {
            dot.classList.remove('d-none');
        }
        if (markBtn && wasUnread) {
            markBtn.classList.remove('d-none');
            markBtn.disabled = false;
        }
        if (hodCard) {
            hodCard.style.opacity = '1';
        }
        if (wasUnread) {
            updateNotificationBadgeUI(prevBadgeCount);
        }
    })
    .finally(() => {
        inFlightNotificationRequests.delete(notifIdStr);
    });
}

/**
 * Marks all notifications for the authenticated user as read.
 * Optimistically updates all visible cards, clears unread dots, hides mark-read buttons,
 * and sets the bell badge to 0.
 *
 * @param {Event|null} event - The triggering DOM event (optional)
 */
function markAllNotificationsRead(event) {
    if (event) {
        try {
            event.preventDefault();
            event.stopPropagation();
        } catch (e) {}
    }
    if (isMarkingAllInFlight) return;
    isMarkingAllInFlight = true;

    const badge = document.getElementById('notificationBadge');
    const prevBadgeCount = badge ? (parseInt(badge.textContent, 10) || 0) : 0;

    // 1. Optimistic UI Updates across all cards in dropdown
    const unreadItems = document.querySelectorAll('.notification-item.notification-unread');
    unreadItems.forEach(item => {
        item.classList.remove('notification-unread');
        item.classList.add('notification-read');
        item.dataset.isRead = 'true';
    });

    const unreadDots = document.querySelectorAll('.notification-dot');
    unreadDots.forEach(dot => dot.classList.add('d-none'));

    const markBtns = document.querySelectorAll('.mark-read-btn');
    markBtns.forEach(btn => btn.classList.add('d-none'));

    updateNotificationBadgeUI(0);

    // 2. Transmit to Backend API
    fetch('/notifications/read-all', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error(`HTTP error ${response.status}`);
        }
        return response.json();
    })
    .then(data => {
        if (data.success) {
            updateNotificationBadgeUI(data.unread_count || 0);
        } else {
            throw new Error(data.message || 'Mark all as read failed');
        }
    })
    .catch(err => {
        console.error('Failed to mark all notifications as read:', err);
        // Rollback
        unreadItems.forEach(item => {
            item.classList.add('notification-unread');
            item.classList.remove('notification-read');
            item.dataset.isRead = 'false';
        });
        unreadDots.forEach(dot => dot.classList.remove('d-none'));
        markBtns.forEach(btn => btn.classList.remove('d-none'));
        updateNotificationBadgeUI(prevBadgeCount);
    })
    .finally(() => {
        isMarkingAllInFlight = false;
    });
}

/**
 * Handles clicks on notification detail links.
 * Proactively marks the notification as read before page navigation.
 *
 * @param {Event} event - The triggering click event
 * @param {number|string} notificationId - The notification ID
 * @param {string} linkUrl - The target URL
 */
function handleNotificationLinkClick(event, notificationId, linkUrl) {
    if (notificationId) {
        const item = document.getElementById(`notif-dropdown-item-${notificationId}`);
        if (item && item.dataset.isRead !== 'true') {
            markNotificationRead(notificationId, null, null);
        }
    }
}

